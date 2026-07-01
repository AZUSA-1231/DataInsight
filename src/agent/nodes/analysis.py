from __future__ import annotations

import json
import logging
import os
import tempfile

from src.agent.llm import get_llm
from src.agent.state import AgentState, ExecutionPlan
from src.agent.utils import _extract_code_block, register_temp_path
from src.sandbox.executor import SandboxResult, run_script
from src.sandbox.static_guard import check_static

logger = logging.getLogger(__name__)


def _serialize_analysis_steps(execution_plan: object) -> str:
    """Extract analysis_steps from ExecutionPlan as JSON string."""
    if isinstance(execution_plan, ExecutionPlan):
        return json.dumps(execution_plan.analysis_steps, indent=2, ensure_ascii=False)
    return "[]"


def _build_analysis_code_prompt(execution_plan: object, file_path: str, output_dir: str) -> str:
    steps_text = _serialize_analysis_steps(execution_plan)
    return f"""You are a senior data analyst. Write a COMPLETE, runnable Python script
that executes the data analysis steps listed below.

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
 "statistics": {{"correlations": {{...}}, "distributions": {{...}}}},
 "insights": ["insight1", "insight2", ...]}}

10. Do NOT write anything to stdout except the final JSON line. Use stderr for
   progress and debug messages.
11. Verify column existence and dtypes before operating — the analysis steps may
   reference columns that don't exist in the actual data.
12. Include `if __name__ == "__main__":` guard.

---

**ANALYSIS STEPS (JSON):**

{steps_text}

---

**DATA FILE PATH:** {file_path}
**OUTPUT DIRECTORY:** {output_dir}
"""


def _build_analysis_react_fix_prompt(
    execution_plan: object,
    previous_code: str,
    error_message: str,
    file_path: str,
    output_dir: str,
) -> str:
    steps_text = _serialize_analysis_steps(execution_plan)
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
   - **Wrong column names**: check the analysis steps for actual column names.
   - **Type mismatches / NaN**: add pd.to_numeric(), fillna(), or dropna().
   - **Path / encoding issues**: verify the file exists and encoding is correct.
   - **Timeout (120s)**: the script was too slow. Replace ALL .iterrows() or nested
     Python for loops with vectorized pandas. For large datasets, sample down to
     30K rows first.
3. Fix ONLY what's broken — do not rewrite the entire analysis logic.

Same rules as before:
- Two CLI args: sys.argv[1] = data file, sys.argv[2] = output dir
- matplotlib.use('Agg') before importing pyplot
- Chinese font rcParams
- No network, no subprocess, try/except wrapper
- Save charts as .png to output_dir
- Print ONLY one JSON line to stdout

---

**ANALYSIS STEPS (JSON):**

{steps_text}

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


def analysis_node(state: AgentState) -> dict[str, object]:
    """Stage 3b — Analysis: generate analysis code, run in sandbox,
    ReAct retry on error.

    Reads: state.execution_plan.analysis_steps, state.preprocessing_result,
           state.file_path
    Writes: state.analysis_result, state.error
    """
    execution_plan = state.execution_plan

    if not execution_plan:
        logger.error("Analysis: execution_plan is missing from state")
        return {
            "error": "Analysis: execution_plan not available (Decision Match may have failed)",
            "analysis_result": {"retry_count": 3, "attempts": []},
        }

    if not execution_plan.analysis_steps:
        logger.info("Analysis: no analysis steps — skipping")
        return {
            "analysis_result": {
                "retry_count": 0,
                "attempts": [],
                "skipped": True,
                "charts": [],
                "statistics": {},
                "insights": [],
            },
            "error": None,
        }

    # Resolve input data path: prefer cleaned data from preprocessing
    pre_result = state.preprocessing_result or {}
    parsed = pre_result.get("parsed_output") or {}
    data_path = (
        pre_result.get("cleaned_data_path") or parsed.get("cleaned_data_path") or state.file_path
    )

    an_result = state.analysis_result or {}
    retry_count = an_result.get("retry_count", 0)
    attempts: list[dict[str, str]] = an_result.get("attempts", [])

    output_dir = an_result.get("output_dir") or tempfile.mkdtemp(prefix="datainsight_analysis_")
    if "output_dir" not in an_result:
        register_temp_path(output_dir)

    if retry_count > 0 and attempts:
        last = attempts[-1]
        prompt = _build_analysis_react_fix_prompt(
            execution_plan, last["code"], last["error"], data_path, output_dir
        )
        logger.info("Analysis: ReAct retry %d/3", retry_count)
    else:
        prompt = _build_analysis_code_prompt(execution_plan, data_path, output_dir)
        logger.info("Analysis: generating analysis script (fresh)")

    try:
        llm = get_llm(temperature=0)
        response = llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        code = str(raw) if not isinstance(raw, str) else raw
    except Exception as e:
        logger.error("Analysis: LLM call failed: %s", e)
        return {
            "error": f"Analysis LLM error: {e}",
            "analysis_result": {
                "retry_count": retry_count + 1,
                "attempts": attempts,
                "output_dir": output_dir,
            },
        }

    code = _extract_code_block(code)

    safe, reason = check_static(code)
    if not safe:
        logger.error("Analysis: static guard rejected code: %s", reason)
        attempts.append({"code": code, "error": reason})
        return {
            "error": f"Analysis: unsafe code rejected — {reason}",
            "analysis_result": {
                "retry_count": retry_count + 1,
                "attempts": attempts,
                "output_dir": output_dir,
            },
        }

    fd, script_path = tempfile.mkstemp(suffix=".py", prefix="datainsight_analysis_")
    register_temp_path(script_path)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(code)
    logger.info("Analysis: script written to %s (%d bytes)", script_path, len(code))

    result: SandboxResult = run_script(script_path, [data_path, output_dir])

    if result.exit_code == 0:
        try:
            parsed = json.loads(result.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            error_msg = (
                "Analysis script exited 0 but produced invalid JSON. "
                f"stdout preview: {result.stdout[:300]}"
            )
            logger.error("Analysis: %s", error_msg)
            attempts.append({"code": code, "error": error_msg})
            return {
                "error": error_msg,
                "analysis_result": {
                    "retry_count": retry_count + 1,
                    "attempts": attempts,
                    "output_dir": output_dir,
                },
            }

        logger.info("Analysis: SUCCESS (attempt %d)", retry_count + 1)
        return {
            "analysis_result": {
                "retry_count": retry_count,
                "attempts": attempts,
                "script_path": script_path,
                "output_dir": output_dir,
                "stdout": result.stdout,
                "parsed_output": parsed,
            },
            "error": None,
        }

    error_msg = (
        (result.stderr or "").strip()
        or (result.stdout or "").strip()
        or f"Exit code {result.exit_code}"
    )
    if result.timed_out:
        error_msg = f"[TIMEOUT after 120s]\n{error_msg}"

    logger.error("Analysis: FAILED (attempt %d/3): %s", retry_count + 1, error_msg[:200])
    attempts.append({"code": code, "error": error_msg})

    return {
        "error": f"Analysis error (attempt {retry_count + 1}/3): {error_msg[:500]}",
        "analysis_result": {
            "retry_count": retry_count + 1,
            "attempts": attempts,
            "output_dir": output_dir,
        },
    }
