from __future__ import annotations

import json
import logging
import os
import re
import tempfile

from src.agent.llm import get_llm
from src.agent.state import AgentState
from src.sandbox.executor import SandboxResult, run_script

logger = logging.getLogger(__name__)


def _extract_code_block(text: str) -> str:
    """Extract Python code from a markdown code fence if present."""
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _build_code_gen_prompt(
    execution_plan: str, file_path: str, output_dir: str
) -> str:
    return f"""You are a senior data engineer. Write a COMPLETE, runnable Python script
that executes the analysis plan below.

CRITICAL RULES:
1. The script MUST accept exactly two CLI arguments: sys.argv[1] = data file path,
   sys.argv[2] = output directory for chart images.
2. Use matplotlib 'Agg' backend (non-interactive). Set it BEFORE importing pyplot:
   `import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt`.
3. For Chinese text in charts, set font fallback (see example below).
   Example: `plt.rcParams['font.sans-serif'] = ['SimHei', 'sans-serif']`
   Also set `plt.rcParams['axes.unicode_minus'] = False`
4. NO network calls, NO subprocess, NO os.system, NO file deletes.
5. Wrap main logic in try/except so errors are printed to stderr clearly.
6. Save all chart images to the output_dir (second CLI arg) as .png files.
7. The LAST line of stdout MUST be a single line of valid JSON:

{{"cleaned_shape": {{"rows": N, "cols": M}},
 "cleaning_actions": ["action1", "action2", ...],
 "charts": ["output_dir/chart1.png", ...],
 "statistics": {{"correlations": {{...}}, "distributions": {{...}}}},
 "insights": ["insight1", "insight2", ...]}}

8. For the data file: detect CSV (with encoding fallback: utf-8, gbk, latin-1) or
   Excel (.xls/.xlsx). Print encoding used as first line (stderr is fine).
9. Do NOT write anything to stdout except the final JSON line. Use stderr for
   progress and debug messages.
10. For datasets with >10,000 rows, use VECTORIZED pandas operations (groupby,
   pivot_table, value_counts, .explode()) instead of .iterrows() or Python for
   loops. Nested for loops on DataFrames are FORBIDDEN — they will timeout.
11. Always verify column data types before calling .explode() or .str accessor.
12. Include `if __name__ == "__main__":` guard.

---

**ANALYSIS EXECUTION PLAN:**

{execution_plan}

---

**DATA FILE PATH:** {file_path}
**OUTPUT DIRECTORY:** {output_dir}
"""


def _build_react_fix_prompt(
    execution_plan: str,
    previous_code: str,
    error_message: str,
    file_path: str,
    output_dir: str,
) -> str:
    return f"""You are a debugging specialist. The Python script below was generated to
execute a data analysis plan, but it FAILED. Your job: diagnose the root cause
and produce a FIXED, complete Python script.

FAILURE ANALYSIS:
1. Identify the root cause from the error message.
2. Common causes and fixes:
   - **ImportError / ModuleNotFoundError**: the package is NOT installed. Remove the
     import entirely and reimplement using ONLY pandas, numpy, and Python stdlib.
     DO NOT try a different import name — the package is simply not available.
   - **Wrong column names**: check the execution plan for actual column names.
   - **Type mismatches / NaN**: add pd.to_numeric(), fillna(), or dropna().
   - **Path / encoding issues**: verify the file exists and encoding is correct.
   - **Timeout (120s)**: the script was too slow. Replace ALL .iterrows() or nested
     Python for loops with vectorized pandas (groupby, pivot_table, value_counts,
     .explode(), .apply()). For large datasets, sample down to 30K rows first.
3. Fix ONLY what's broken — do not rewrite the entire analysis logic.

Same rules as before:
- Two CLI args: sys.argv[1] = data file, sys.argv[2] = output dir
- Agg backend, Chinese font fallback, no network, try/except wrapper
- Save charts to output_dir, print ONLY one JSON line to stdout

---

**ORIGINAL EXECUTION PLAN:**

{execution_plan}

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


def execution_node(state: AgentState) -> AgentState:
    """Stage 3 — Execution: generate analysis code, run in sandbox, ReAct retry on error.

    Reads: state["execution_plan"], state["file_path"], state["execution_result"]
    Writes: state["execution_result"], state["error"]
    """
    execution_plan = state.get("execution_plan")
    file_path = state["file_path"]

    if not execution_plan:
        logger.error("Execution: execution_plan is missing from state")
        return {
            **state,
            "error": "Execution: execution_plan not available (Decision Match may have failed)",
            "execution_result": {
                "retry_count": 3,  # Prevent infinite retry — this is a permanent error
                "attempts": [],
            },
        }

    exec_result = state.get("execution_result", {})
    retry_count = exec_result.get("retry_count", 0)
    attempts: list[dict[str, str]] = exec_result.get("attempts", [])

    # Reuse output dir across retries
    output_dir = exec_result.get("output_dir", tempfile.mkdtemp(prefix="datainsight_"))

    # Choose prompt: fresh generation vs ReAct fix
    if retry_count > 0 and attempts:
        last = attempts[-1]
        prompt = _build_react_fix_prompt(
            execution_plan, last["code"], last["error"], file_path, output_dir
        )
        logger.info("Execution: ReAct retry %d/3", retry_count)
    else:
        prompt = _build_code_gen_prompt(execution_plan, file_path, output_dir)
        logger.info("Execution: generating analysis script (fresh)")

    # LLM generates code
    try:
        llm = get_llm(temperature=0)
        response = llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        code = raw if isinstance(raw, str) else str(raw)
    except Exception as e:
        logger.error("Execution: LLM call failed: %s", e)
        return {
            **state,
            "error": f"Execution LLM error: {e}",
            "execution_result": {
                "retry_count": retry_count + 1,
                "attempts": attempts,
                "output_dir": output_dir,
            },
        }

    code = _extract_code_block(code)

    # Write to temp script file
    fd, script_path = tempfile.mkstemp(suffix=".py", prefix="datainsight_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(code)
    logger.info("Execution: script written to %s (%d bytes)", script_path, len(code))

    # Run in sandbox
    result: SandboxResult = run_script(script_path, [file_path, output_dir])

    if result.exit_code == 0:
        # Parse JSON output — last non-empty line should be the JSON
        try:
            parsed = json.loads(result.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            error_msg = (
                f"Script exited 0 but produced invalid JSON. "
                f"stdout preview: {result.stdout[:300]}"
            )
            logger.error("Execution: %s", error_msg)
            attempts.append({"code": code, "error": error_msg})
            return {
                **state,
                "error": error_msg,
                "execution_result": {
                    "retry_count": retry_count + 1,
                    "attempts": attempts,
                    "output_dir": output_dir,
                },
            }

        logger.info("Execution: SUCCESS (attempt %d)", retry_count + 1)
        new_state = {
            **state,
            "execution_result": {
                "retry_count": retry_count,
                "attempts": attempts,
                "script_path": script_path,
                "output_dir": output_dir,
                "stdout": result.stdout,
                "parsed_output": parsed,
            },
        }
        # Clear error from prior failed attempts on success
        new_state.pop("error", None)
        return new_state  # type: ignore[return-value]

    # Sandbox failure — build error for ReAct
    error_msg = (
        (result.stderr or "").strip()
        or (result.stdout or "").strip()
        or f"Exit code {result.exit_code}"
    )
    if result.timed_out:
        error_msg = f"[TIMEOUT after 120s]\n{error_msg}"

    logger.error("Execution: FAILED (attempt %d/3): %s", retry_count + 1, error_msg[:200])
    attempts.append({"code": code, "error": error_msg})

    return {
        **state,
        "error": f"Execution error (attempt {retry_count + 1}/3): {error_msg[:500]}",
        "execution_result": {
            "retry_count": retry_count + 1,
            "attempts": attempts,
            "output_dir": output_dir,
        },
    }
