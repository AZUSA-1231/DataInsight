from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any

import pandas as pd

from src.agent.llm import get_llm
from src.agent.state import AgentState, ExecutionMode, PlanUnit, UnitType
from src.agent.templates import dispatch as _template_dispatch
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
            "unit_type": unit.unit_type,
            "execution_mode": unit.execution_mode,
            "purpose": unit.purpose,
            "model": unit.model_hint or "auto",
            "template_name": unit.template_name,
            "cautious": unit.cautious,
            "input_columns": unit.input_columns,
            "output_columns": unit.output_columns,
            "related_fields": unit.related_fields,
        },
        indent=2,
        ensure_ascii=False,
    )


def _common_sandbox_rules() -> str:
    """Sandbox rules shared by all unit types."""
    return """\
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
8. Detect CSV (encoding fallback: utf-8, gbk, latin-1) or Excel (.xls/.xlsx)."""


def _type_specific_rules(unit: PlanUnit) -> str:
    """Return the in-process function contract for a Transform or Filter."""
    if unit.unit_type == UnitType.TRANSFORM:
        return """
**UNIT TYPE: TRANSFORM** — You are adding NEW columns to the DataFrame.

TYPE-SPECIFIC RULES:
T1. Row count MUST NOT change. Every row in = every row out. Use .transform()
    or direct column operations, NEVER .agg() or .groupby().agg().
T2. Do NOT modify existing columns — only ADD new ones declared in output_columns.
T3. Read ONLY from input_columns and related_fields.
T4. Every returned Series MUST preserve df.index exactly.

RETURN VALUE:
{"columns": {"new_col_1": pandas_series, ...},
 "artifacts": [],
 "statistics": {"optional_metric": value},
 "insights": ["optional concise finding"]}"""

    if unit.unit_type == UnitType.FILTER:
        return """
**UNIT TYPE: FILTER** — You are selecting a SUBSET of rows from the DataFrame.

TYPE-SPECIFIC RULES:
F1. Column set MUST NOT change. Every input column must appear in output.
F2. Each row must still represent its original sample — no aggregation, no joins.
F3. Read ONLY from input_columns and related_fields.
F4. Preserve the original row index; return only a subset of input rows.
F5. snapshot_name must contain only letters, digits, underscores, or hyphens.

RETURN VALUE:
{"filtered_df": filtered_dataframe,
 "snapshot_name": "descriptive_name",
 "artifacts": [],
 "statistics": {"row_count_before": N, "row_count_after": M},
 "insights": ["optional concise finding"]}"""

    # Terminal units never use the in-process path.
    return """
**UNIT TYPE: TERMINAL** — You are producing ARTIFACTS (charts, reports, etc.).

Terminal units execute in the subprocess path, not as in-process functions."""


def _terminal_sandbox_rules() -> str:
    """Return the subprocess contract used only by Terminal units."""
    return """
**UNIT TYPE: TERMINAL** — You are producing ARTIFACTS (charts, reports, etc.).

TYPE-SPECIFIC RULES:
T1. Do NOT produce data columns or snapshots. You are a leaf node.
T2. Do NOT save output.csv — downstream units will NOT read from you.
T3. Read from input_columns and related_fields. Produce charts/reports/models.
T4. The output_dir is for your artifact files (.png, .html, .json, etc.).

STDOUT JSON (LAST line, one line only):
{"charts": ["output_dir/chart1.png", ...],
 "statistics": {"key": "value", ...},
 "insights": ["insight1", "insight2", ...]}"""


def _build_unit_code_prompt(
    unit: PlanUnit,
    file_path: str,
    output_dir: str,
    upstream_context: str | None = None,
) -> str:
    unit_text = _serialize_unit(unit)
    upstream_section = ""
    if upstream_context:
        upstream_section = f"""
**UPSTREAM DATA:**

{upstream_context}

The input file for this unit already contains columns produced by previous
analysis steps. Use these columns as needed but do NOT overwrite them.
"""
    type_section = _terminal_sandbox_rules()

    return f"""You are a senior data analyst. Write a COMPLETE, runnable Python script
that executes the SINGLE analysis task described below. Focus ONLY on this one task.

CRITICAL RULES (ALL unit types):
{_common_sandbox_rules()}
9. Do NOT write anything to stdout except the final JSON line. Use stderr for
   progress and debug messages.
10. Verify column existence and dtypes before operating — the analysis task may
    reference columns that don't exist in the actual data.
11. The "related_fields" list specifies which columns this analysis should focus
    on. Prioritize these columns — they are the user's intended analytical
    dimensions. Other columns may be used as needed for context.
12. Include `if __name__ == "__main__":` guard.
13. When UPSTREAM DATA section is present, the input file already contains columns
    produced by previous analysis steps. Use these columns as needed but do NOT
    overwrite them.

{type_section}

---

**ANALYSIS TASK (JSON):**

{unit_text}
{upstream_section}
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
    upstream_context: str | None = None,
) -> str:
    unit_text = _serialize_unit(unit)
    upstream_section = ""
    if upstream_context:
        upstream_section = f"""

**UPSTREAM DATA:**

{upstream_context}

The input file already contains columns from previous analysis steps.
Use them as needed but do NOT overwrite them.
"""
    type_section = _terminal_sandbox_rules()

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

{type_section}

---

**ANALYSIS TASK (JSON):**

{unit_text}
{upstream_section}
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


def _build_upstream_context(unit: PlanUnit) -> str | None:
    """Build upstream context string for the code-gen prompt.

    Describes what new columns are available from upstream units
    and what this unit is expected to produce.
    """
    parts: list[str] = []
    if unit.input_columns:
        parts.append(
            f"Input columns available: {', '.join(unit.input_columns)}"
        )
    if unit.output_columns:
        parts.append(
            f"Expected output columns to produce: {', '.join(unit.output_columns)}"
        )
    if unit.depends_on:
        parts.append(
            f"This unit depends on units {unit.depends_on}. "
            "Their output columns are already in the input file."
        )
    return "\n".join(parts) if parts else None


def _load_input_data(data_path: str) -> pd.DataFrame:
    """Load input data from CSV or Parquet, falling back to CSV on Parquet errors."""
    if data_path.endswith(".parquet"):
        try:
            return pd.read_parquet(data_path)
        except Exception:
            logger.warning(
                "Parquet load failed for %s, trying CSV fallback", data_path,
            )
    return pd.read_csv(data_path)


def _model_name(llm: object, node: str) -> str:
    """Return the concrete configured LLM name for persisted result metadata."""
    for attribute in ("model_name", "model"):
        value = getattr(llm, attribute, None)
        if isinstance(value, str) and value:
            return value
    suffix = node.upper()
    return (
        os.environ.get(f"DATAINSIGHT_LLM_MODEL_{suffix}")
        or os.environ.get("DATAINSIGHT_LLM_MODEL")
        or "unknown"
    )


# ── in-process LLM execution (Transform / Filter) ────────────────────────────


def _build_inprocess_prompt(
    unit: PlanUnit,
    retry_context: dict[str, str] | None = None,
) -> str:
    """Prompt for generating a single ``_unit`` function body (no script boilerplate).

    The LLM must define ``def _unit(df, input_columns, params):`` returning
    the per-unit-type dict contract.  The framework handles data loading,
    checkpoint saving, and contract validation.
    """
    unit_text = _serialize_unit(unit)
    type_rules = _type_specific_rules(unit)
    prefix = "FIX " if retry_context else ""

    retry_section = ""
    if retry_context:
        retry_section = f"""
**PREVIOUS ATTEMPT (FAILED):**

```python
{retry_context['code']}
```

**ERROR:** {retry_context['error']}

Fix the error and produce a corrected ``_unit`` function.
"""

    label = f"{prefix}{unit.unit_type.value.upper()}"
    return f"""Write a Python function body for a {label} analysis unit.

DEFINE THIS FUNCTION:
```python
def _unit(df, input_columns, params):
    # df: pd.DataFrame — the input wide table
    # input_columns: list[str] — columns this unit reads
    # params: dict — extra parameters from template_params
    ...
    return ...  # see contract below
```

RULES:
- Use ONLY pandas (as ``pd``) and numpy (as ``np``). No other imports.
- No file I/O, no network, no subprocess, no print() to stdout.
- Return a dict matching the contract below. Do NOT write output.csv.
- Keep the function body short and focused — typically 5-20 lines.

{type_rules}
{retry_section}
---

**UNIT CONTEXT (JSON):**

{unit_text}
"""


def _execute_inprocess_llm(
    unit: PlanUnit,
    data_path: str,
    output_dir: str,
    retry_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a Transform or Filter unit via in-process LLM code generation.

    LLM → exec_llm_function → call fn → _build_template_result.
    ReAct retry (max 3) re-invokes the LLM with error context.
    """
    from src.agent.templates import _build_template_result, exec_llm_function

    unit_id = unit.unit_id
    retry_count = retry_state.get("retry_count", 0) if retry_state else 0
    attempts: list[dict[str, str]] = retry_state.get("attempts", []) if retry_state else []
    df = _load_input_data(data_path)
    model_used = "unknown"

    while retry_count < _MAX_RETRIES:
        retry_ctx: dict[str, str] | None = None
        if attempts:
            last = attempts[-1]
            retry_ctx = {"code": last["code"], "error": last["error"]}

        prompt = _build_inprocess_prompt(unit, retry_context=retry_ctx)

        try:
            llm = get_llm(temperature=0, node="analysis_transform")
            model_used = _model_name(llm, "analysis_transform")
            response = llm.invoke(prompt)
            raw = response.content if hasattr(response, "content") else str(response)
            code = str(raw) if not isinstance(raw, str) else raw
        except Exception as e:
            logger.error("In-process unit [%d]: LLM call failed: %s", unit_id, e)
            retry_count += 1
            attempts.append({"code": "", "error": f"LLM error: {e}"})
            if retry_count >= _MAX_RETRIES:
                break
            continue

        code = _extract_code_block(code)
        logger.info(
            "In-process unit [%d]: generated code (%d chars, attempt %d)",
            unit_id, len(code), retry_count + 1,
        )

        # Compile and run
        try:
            fn = exec_llm_function(code)
        except ValueError as e:
            logger.error("In-process unit [%d]: compile failed: %s", unit_id, e)
            retry_count += 1
            attempts.append({"code": code, "error": str(e)})
            if retry_count >= _MAX_RETRIES:
                break
            continue

        try:
            template_output = fn(df, unit.input_columns, unit.template_params or {})
        except Exception as e:
            logger.error(
                "In-process unit [%d]: function raised: %s", unit_id, e,
            )
            retry_count += 1
            attempts.append({"code": code, "error": str(e)})
            if retry_count >= _MAX_RETRIES:
                break
            continue

        if not isinstance(template_output, dict):
            retry_count += 1
            msg = f"Expected dict return, got {type(template_output).__name__}"
            attempts.append({"code": code, "error": msg})
            if retry_count >= _MAX_RETRIES:
                break
            continue

        # Success — build and validate through the same path as templates
        try:
            result = _build_template_result(unit, template_output, output_dir, df)
        except ValueError as e:
            logger.error("In-process unit [%d]: contract failed: %s", unit_id, e)
            retry_count += 1
            attempts.append({"code": code, "error": str(e)})
            if retry_count >= _MAX_RETRIES:
                break
            continue
        result["source_code"] = code
        result["model_used"] = model_used
        result["retry_count"] = retry_count
        result["scripts"] = []
        result["stdout"] = ""
        logger.info("In-process unit [%d]: SUCCESS (attempt %d)", unit_id, retry_count + 1)
        return result

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
        "scripts": [],
        "stdout": "",
        "output_dir": output_dir,
        "source_code": attempts[-1]["code"] if attempts else None,
        "model_used": model_used,
    }


def _execute_unit(
    unit: PlanUnit,
    data_path: str,
    parent_output_dir: str,
    unit_retry_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a unit through template, in-process LLM, or terminal sandbox.

    Template-mode units run in-process via _template_dispatch and return
    immediately. Transform/Filter LLM units compile a restricted temporary
    function. Terminal LLM units retain subprocess isolation.

    Returns a dict with: unit_id, status, parsed_output, charts, insights,
    error, retry_count, scripts, stdout.
    """
    unit_id = unit.unit_id
    unit_output_dir = os.path.join(parent_output_dir, f"unit_{unit_id}")
    os.makedirs(unit_output_dir, exist_ok=True)
    register_temp_path(unit_output_dir)

    # ── Template dispatch (in-process, no LLM/sandbox) ──
    if unit.execution_mode == ExecutionMode.TEMPLATE:
        try:
            df = _load_input_data(data_path)
        except Exception as e:
            logger.error("Template unit [%d]: data load failed: %s", unit_id, e)
            return {
                "unit_id": unit_id,
                "status": "failed",
                "parsed_output": None,
                "charts": [],
                "insights": [],
                "statistics": {},
                "error": f"Failed to load input data: {e}",
                "retry_count": 0,
                "scripts": [],
                "stdout": "",
                "output_dir": unit_output_dir,
            }
        template_result = _template_dispatch(unit, df, unit_output_dir)
        if template_result is not None:
            return template_result

    # ── In-process LLM (Transform / Filter) ──
    if unit.unit_type in (UnitType.TRANSFORM, UnitType.FILTER):
        return _execute_inprocess_llm(
            unit, data_path, unit_output_dir, unit_retry_state,
        )

    # ── Terminal: subprocess sandbox (kept for creative code generation) ──
    retry_count = 0
    attempts: list[dict[str, str]] = []
    scripts: list[str] = []
    model_used = "unknown"

    if unit_retry_state:
        retry_count = unit_retry_state.get("retry_count", 0)
        attempts = unit_retry_state.get("attempts", [])
        scripts = unit_retry_state.get("scripts", [])

    upstream_context = _build_upstream_context(unit)

    while retry_count < _MAX_RETRIES:
        # Build prompt
        if retry_count > 0 and attempts:
            last = attempts[-1]
            prompt = _build_unit_react_fix_prompt(
                unit, last["code"], last["error"], data_path, unit_output_dir,
                upstream_context=upstream_context,
            )
            logger.info("Analysis unit [%d]: ReAct retry %d/%d", unit_id, retry_count, _MAX_RETRIES)
        else:
            prompt = _build_unit_code_prompt(
                unit, data_path, unit_output_dir, upstream_context=upstream_context,
            )
            logger.info("Analysis unit [%d]: generating script (fresh)", unit_id)

        # LLM call
        try:
            llm = get_llm(temperature=0, node="analysis_terminal")
            model_used = _model_name(llm, "analysis_terminal")
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
                "source_code": code,
                "model_used": model_used,
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
        "source_code": attempts[-1]["code"] if attempts else None,
        "model_used": model_used,
    }


def analysis_node(state: AgentState) -> dict[str, object]:
    """Stage 3 — Analysis: execute PlanUnits in DAG order via topological sort.

    Reads: state.plan.units, state.file_path, state.unified_columns
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
        "Analysis: executing %d unit(s) via DAG executor",
        len(units),
    )

    from src.agent.dag import execute_dag

    dag_result = execute_dag(
        state, parent_output_dir, prev_unit_results, _execute_unit,
    )

    errors: list[str] = []
    for ur in dag_result.get("unit_results", []):
        if ur["status"] == "failed":
            errors.append(
                f"Unit {ur['unit_id']}: {ur.get('error', 'unknown')}"
            )

    return {
        "analysis_result": dag_result,
        "error": "; ".join(errors) if errors else None,
    }
