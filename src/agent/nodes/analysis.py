from __future__ import annotations

import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from src.agent.llm import get_llm
from src.agent.state import AgentState, PlanUnit
from src.agent.utils import _extract_code_block, _extract_json, register_temp_path
from src.sandbox.executor import DEFAULT_TIMEOUT, SandboxResult, run_script
from src.sandbox.static_guard import check_static

logger = logging.getLogger(__name__)

_ANALYSIS_TIMEOUT: int
try:
    _ANALYSIS_TIMEOUT = int(os.environ.get("DATAINSIGHT_TIMEOUT_ANALYSIS", "120"))
except ValueError:
    _ANALYSIS_TIMEOUT = DEFAULT_TIMEOUT
    logger.warning(
        "Invalid DATAINSIGHT_TIMEOUT_ANALYSIS, falling back to %ds", DEFAULT_TIMEOUT
    )

_MAX_WORKERS = 3
_MAX_RETRIES = 3


def _serialize_unit(unit: PlanUnit) -> str:
    """Serialize a single PlanUnit as JSON for prompt inclusion."""
    return json.dumps(
        {
            "unit_id": unit.unit_id,
            "purpose": unit.purpose,
            "model": unit.model or "auto",
            "cautious": unit.cautious,
            "related_fields": unit.related_fields,
        },
        indent=2,
        ensure_ascii=False,
    )


def _build_unit_code_prompt(unit: PlanUnit, file_path: str, output_dir: str) -> str:
    unit_text = _serialize_unit(unit)
    return f"""You are a senior data analyst. Write a COMPLETE, runnable Python script
that executes the SINGLE analysis task described below. Focus ONLY on this one task.

CRITICAL RULES:
1. The script MUST accept exactly two CLI arguments: sys.argv[1] = data file path,
   sys.argv[2] = output directory for charts.
2. Call `matplotlib.use('Agg')` BEFORE `import matplotlib.pyplot as plt`.
3. Set Chinese-aware fonts:
   plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'sans-serif']
   plt.rcParams['axes.unicode_minus'] = False
4. NO network calls, NO subprocess, NO os.system, NO file deletes.
5. Wrap main logic in try/except so errors are printed to stderr clearly.
6. Save charts to output_dir as .png files.
7. For datasets with >10,000 rows, use VECTORIZED pandas operations. Nested for
   loops and .iterrows() on DataFrames are FORBIDDEN — they will timeout.
8. Detect CSV (encoding fallback: utf-8, gbk, latin-1) or Excel (.xls/.xlsx).
9. The LAST line of stdout MUST be a single line of valid JSON:

{{"charts": ["output_dir/chart1.png", ...],
 "statistics": {{"key": "value", ...}},
 "insights": ["insight1", "insight2", ...]}}

10. Do NOT write anything to stdout except the final JSON line. Use stderr for
   progress and debug messages.
11. Verify column existence and dtypes before operating — the analysis task may
   reference columns that don't exist in the actual data.
12. The "related_fields" list specifies which columns this analysis should focus
    on. Prioritize these columns — they are the user's intended analytical
    dimensions. Other columns may be used as needed for context.
13. Include `if __name__ == "__main__":` guard.

---

**ANALYSIS TASK (JSON):**

{unit_text}

---

**DATA FILE PATH:** {file_path}
**OUTPUT DIRECTORY:** {output_dir}
"""


def _build_unit_react_fix_prompt(
    unit: PlanUnit,
    previous_code: str,
    error_message: str,
    file_path: str,
    output_dir: str,
) -> str:
    unit_text = _serialize_unit(unit)
    return f"""You are a debugging specialist. The Python analysis script below FAILED.
Diagnose the root cause and produce a FIXED, complete Python script.

FAILURE ANALYSIS:
1. Identify the root cause from the error message.
2. Common causes and fixes:
   - **ImportError / ModuleNotFoundError**: the package is NOT installed. Remove the
     import entirely and reimplement using ONLY pandas, numpy, matplotlib, scipy,
     scikit-learn, and Python stdlib. DO NOT try a different import name.
   - **Missing Agg backend**: add `matplotlib.use('Agg')` BEFORE importing pyplot.
   - **Chinese font crash**: add SimHei/DejaVu Sans fallback in rcParams.
   - **Wrong column names**: check the analysis task for actual column names.
   - **Type mismatches / NaN**: add pd.to_numeric(), fillna(), or dropna().
   - **Path / encoding issues**: verify the file exists and encoding is correct.
   - **Timeout ({_ANALYSIS_TIMEOUT}s)**: the script was too slow. Replace ALL
     .iterrows() or nested Python for loops with vectorized pandas. For large
     datasets, sample down to 30K rows first.
3. Fix ONLY what's broken — do not rewrite the entire analysis logic.

Same rules as before:
- Two CLI args: sys.argv[1] = data file, sys.argv[2] = output dir
- matplotlib.use('Agg') before importing pyplot
- Chinese font rcParams
- No network, no subprocess, try/except wrapper
- Save charts as .png to output_dir
- Print ONLY one JSON line to stdout

---

**ANALYSIS TASK (JSON):**

{unit_text}

---

**FAILED CODE:**

```python
{previous_code}
```

---

**ERROR MESSAGE:**

{error_message}

---

**DATA FILE PATH:** {file_path}
**OUTPUT DIRECTORY:** {output_dir}

Output the FIXED complete Python script (with ```python fence).
"""


def _execute_unit(
    unit: PlanUnit,
    data_path: str,
    parent_output_dir: str,
    unit_retry_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a single PlanUnit: LLM gen → static guard → sandbox → ReAct retry ×3.

    Returns a dict with: unit_id, status, parsed_output, charts, insights,
    error, retry_count, scripts, stdout.
    """
    unit_id = unit.unit_id
    unit_output_dir = os.path.join(parent_output_dir, f"unit_{unit_id}")
    os.makedirs(unit_output_dir, exist_ok=True)
    register_temp_path(unit_output_dir)

    retry_count = 0
    attempts: list[dict[str, str]] = []
    scripts: list[str] = []

    if unit_retry_state:
        retry_count = unit_retry_state.get("retry_count", 0)
        attempts = unit_retry_state.get("attempts", [])
        scripts = unit_retry_state.get("scripts", [])

    while retry_count < _MAX_RETRIES:
        # Build prompt
        if retry_count > 0 and attempts:
            last = attempts[-1]
            prompt = _build_unit_react_fix_prompt(
                unit, last["code"], last["error"], data_path, unit_output_dir
            )
            logger.info("Analysis unit [%d]: ReAct retry %d/%d", unit_id, retry_count, _MAX_RETRIES)
        else:
            prompt = _build_unit_code_prompt(unit, data_path, unit_output_dir)
            logger.info("Analysis unit [%d]: generating script (fresh)", unit_id)

        # LLM call
        try:
            llm = get_llm(temperature=0, node="analysis")
            response = llm.invoke(prompt)
            raw = response.content if hasattr(response, "content") else str(response)
            code = str(raw) if not isinstance(raw, str) else raw
        except Exception as e:
            logger.error("Analysis unit [%d]: LLM call failed: %s", unit_id, e)
            retry_count += 1
            attempts.append({"code": "", "error": f"LLM error: {e}"})
            if retry_count >= _MAX_RETRIES:
                break
            continue

        code = _extract_code_block(code)

        # Static guard
        safe, reason = check_static(code)
        if not safe:
            logger.error("Analysis unit [%d]: static guard rejected: %s", unit_id, reason)
            retry_count += 1
            attempts.append({"code": code, "error": reason})
            if retry_count >= _MAX_RETRIES:
                break
            continue

        # Write script
        fd, script_path = tempfile.mkstemp(
            suffix=".py", prefix=f"datainsight_analysis_u{unit_id}_"
        )
        register_temp_path(script_path)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)
        scripts.append(script_path)
        logger.info(
            "Analysis unit [%d]: script written to %s (%d bytes)",
            unit_id, script_path, len(code),
        )

        # Sandbox execution
        result: SandboxResult = run_script(
            script_path, [data_path, unit_output_dir], timeout_seconds=_ANALYSIS_TIMEOUT
        )

        if result.exit_code == 0:
            try:
                json_text = _extract_json(result.stdout)
                parsed = json.loads(json_text)
            except (json.JSONDecodeError, IndexError):
                error_msg = (
                    f"Analysis script exited 0 but produced invalid JSON. "
                    f"stdout preview: {result.stdout[:300]}"
                )
                logger.error("Analysis unit [%d]: %s", unit_id, error_msg)
                retry_count += 1
                attempts.append({"code": code, "error": error_msg})
                if retry_count >= _MAX_RETRIES:
                    break
                continue

            logger.info("Analysis unit [%d]: SUCCESS (attempt %d)", unit_id, retry_count + 1)
            return {
                "unit_id": unit_id,
                "status": "success",
                "parsed_output": parsed,
                "charts": parsed.get("charts", []),
                "insights": parsed.get("insights", []),
                "statistics": parsed.get("statistics", {}),
                "error": None,
                "retry_count": retry_count,
                "scripts": scripts,
                "stdout": result.stdout,
                "output_dir": unit_output_dir,
            }

        error_msg = (
            (result.stderr or "").strip()
            or (result.stdout or "").strip()
            or f"Exit code {result.exit_code}"
        )
        if result.timed_out:
            error_msg = f"[TIMEOUT after {_ANALYSIS_TIMEOUT}s]\n{error_msg}"

        logger.error(
            "Analysis unit [%d]: FAILED (attempt %d/%d): %s",
            unit_id, retry_count + 1, _MAX_RETRIES, error_msg[:200],
        )
        retry_count += 1
        attempts.append({"code": code, "error": error_msg})

    # Exhausted retries
    return {
        "unit_id": unit_id,
        "status": "failed",
        "parsed_output": None,
        "charts": [],
        "insights": [],
        "statistics": {},
        "error": (
            f"Unit {unit_id} failed after {_MAX_RETRIES} retries: "
            f"{attempts[-1]['error'][:300] if attempts else 'unknown'}"
        ),
        "retry_count": retry_count,
        "scripts": scripts,
        "stdout": "",
        "output_dir": unit_output_dir,
    }


def analysis_node(state: AgentState) -> dict[str, object]:
    """Stage 3b — Analysis: execute each PlanUnit independently with parallel
    sandbox via ThreadPoolExecutor.

    Reads: state.plan.units, state.preprocessing_result, state.file_path
    Writes: state.analysis_result, state.error
    """
    plan = state.plan

    if not plan:
        logger.error("Analysis: no Plan available")
        return {
            "error": "Analysis: plan not available (Planner may have failed)",
            "analysis_result": {"unit_results": [], "status": "failed"},
        }

    units = plan.units
    if not units:
        logger.info("Analysis: no analysis units — skipping")
        return {
            "analysis_result": {
                "unit_results": [],
                "status": "complete",
                "skipped": True,
            },
            "error": None,
        }

    # Resolve input data path: prefer cleaned data from preprocessing
    pre_result = state.preprocessing_result or {}
    parsed = pre_result.get("parsed_output") or {}
    data_path = parsed.get("cleaned_data_path") or state.file_path

    # Shared parent output dir for all units
    an_result = state.analysis_result or {}
    parent_output_dir = an_result.get("output_dir") or tempfile.mkdtemp(
        prefix="datainsight_analysis_"
    )
    if "output_dir" not in an_result:
        register_temp_path(parent_output_dir)

    # Restore per-unit retry state from previous partial runs
    prev_unit_results: dict[int, dict[str, Any]] = {}
    for ur in an_result.get("unit_results", []):
        prev_unit_results[ur["unit_id"]] = ur

    logger.info(
        "Analysis: executing %d unit(s) with ThreadPoolExecutor(max_workers=%d)",
        len(units), _MAX_WORKERS,
    )

    unit_results: list[dict[str, Any]] = []
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {}
        for unit in units:
            prev = prev_unit_results.get(unit.unit_id)
            future = executor.submit(_execute_unit, unit, data_path, parent_output_dir, prev)
            futures[future] = unit.unit_id

        for future in as_completed(futures):
            unit_id = futures[future]
            try:
                result = future.result()
                unit_results.append(result)
                if result["status"] == "failed":
                    errors.append(f"Unit {unit_id}: {result.get('error', 'unknown')}")
            except Exception as e:
                logger.error("Analysis unit [%d]: executor failed: %s", unit_id, e)
                unit_results.append({
                    "unit_id": unit_id,
                    "status": "failed",
                    "parsed_output": None,
                    "charts": [],
                    "insights": [],
                    "statistics": {},
                    "error": f"Executor error: {e}",
                    "retry_count": 0,
                    "scripts": [],
                    "stdout": "",
                    "output_dir": os.path.join(parent_output_dir, f"unit_{unit_id}"),
                })
                errors.append(f"Unit {unit_id}: executor error: {e}")

    # Sort by unit_id for deterministic output
    unit_results.sort(key=lambda r: r["unit_id"])

    all_success = all(r["status"] == "success" for r in unit_results)
    status = "complete" if all_success else "partial"

    logger.info(
        "Analysis: %d/%d units succeeded (status=%s)",
        sum(1 for r in unit_results if r["status"] == "success"),
        len(unit_results),
        status,
    )

    return {
        "analysis_result": {
            "unit_results": unit_results,
            "status": status,
            "output_dir": parent_output_dir,
        },
        "error": "; ".join(errors) if errors else None,
    }
