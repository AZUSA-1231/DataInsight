from __future__ import annotations

import json
import logging
import os
import tempfile

from src.agent.llm import get_llm
from src.agent.state import AgentState, PlanUnit
from src.agent.utils import _extract_code_block, _extract_json, register_temp_path
from src.sandbox.executor import DEFAULT_TIMEOUT, SandboxResult, run_script
from src.sandbox.static_guard import check_static

logger = logging.getLogger(__name__)

_CLEANING_TIMEOUT: int
try:
    _CLEANING_TIMEOUT = int(os.environ.get("DATAINSIGHT_TIMEOUT_CLEANING", "180"))
except ValueError:
    _CLEANING_TIMEOUT = DEFAULT_TIMEOUT
    logger.warning(
        "Invalid DATAINSIGHT_TIMEOUT_CLEANING, falling back to %ds", DEFAULT_TIMEOUT
    )


def _serialize_cleaning_unit(cleaning: PlanUnit) -> str:
    """Serialize the cleaning PlanUnit as JSON for prompt inclusion."""
    return json.dumps(
        {
            "unit_id": cleaning.unit_id,
            "purpose": cleaning.purpose,
            "cautious": cleaning.cautious,
            "related_fields": cleaning.related_fields,
        },
        indent=2,
        ensure_ascii=False,
    )


def _build_clean_code_prompt(cleaning: PlanUnit, file_path: str, output_dir: str) -> str:
    steps_text = _serialize_cleaning_unit(cleaning)
    return f"""You are a data cleaning specialist. Write a COMPLETE, runnable Python script
that executes the data cleaning steps listed below.

CRITICAL RULES:
1. The script MUST accept exactly two CLI arguments: sys.argv[1] = data file path,
   sys.argv[2] = output directory.
2. Detect CSV (with encoding fallback: utf-8, gbk, latin-1) or Excel (.xls/.xlsx).
   Print the detected encoding as the first line to stderr.
3. NO network calls, NO subprocess, NO os.system, NO file deletes.
4. Wrap main logic in try/except so errors are printed to stderr clearly.
5. For datasets with >10,000 rows, use VECTORIZED pandas operations (groupby,
   dropna, fillna, astype, etc.). Nested for loops and .iterrows() on DataFrames
   are FORBIDDEN — they will timeout.
6. Save the cleaned data to output_dir as "cleaned_data.csv" (UTF-8 with BOM
   for Excel compatibility: df.to_csv(path, index=False, encoding='utf-8-sig')).
7. The LAST line of stdout MUST be a single line of valid JSON:

{{"cleaned_shape": {{"rows": N, "cols": M}},
 "cleaning_actions": ["action1", "action2", ...],
 "cleaned_data_path": "output_dir/cleaned_data.csv"}}

8. Do NOT write anything to stdout except the final JSON line. Use stderr for
   progress and debug messages.
9. Always verify column existence before operating on them — the cleaning steps
   may reference columns that don't exist in the actual data.
10. The "related_fields" list specifies which columns this cleaning step should
    focus on. Prioritize these columns for quality checks, but don't ignore
    other columns that may need attention.
11. Include `if __name__ == "__main__":` guard.

---

**DATA CLEANING UNIT (JSON):**

{steps_text}

---

**DATA FILE PATH:** {file_path}
**OUTPUT DIRECTORY:** {output_dir}
"""


def _build_clean_react_fix_prompt(
    cleaning: PlanUnit,
    previous_code: str,
    error_message: str,
    file_path: str,
    output_dir: str,
) -> str:
    steps_text = _serialize_cleaning_unit(cleaning)
    return f"""You are a debugging specialist. The Python cleaning script below FAILED.
Diagnose the root cause and produce a FIXED, complete Python script.

FAILURE ANALYSIS:
1. Identify the root cause from the error message.
2. Common causes and fixes:
   - **ImportError / ModuleNotFoundError**: the package is NOT installed. Remove the
     import entirely and reimplement using ONLY pandas, numpy, and Python stdlib.
     DO NOT try a different import name — the package is simply not available.
   - **Wrong column names**: check the cleaning steps for actual column names.
   - **Type mismatches / NaN**: add pd.to_numeric(), fillna(), or dropna().
   - **Path / encoding issues**: verify the file exists and encoding is correct.
   - **Timeout ({_CLEANING_TIMEOUT}s)**: the script was too slow. Replace ALL
     .iterrows() or nested Python for loops with vectorized pandas. For large
     datasets, sample down to 30K rows first.
3. Fix ONLY what's broken — do not rewrite the entire cleaning logic.

Same rules as before:
- Two CLI args: sys.argv[1] = data file, sys.argv[2] = output dir
- No network, no subprocess, try/except wrapper
- Save cleaned data as "cleaned_data.csv" to output_dir
- Print ONLY one JSON line to stdout

---

**CLEANING UNIT (JSON):**

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


def preprocessing_node(state: AgentState) -> dict[str, object]:
    """Stage 3a — Preprocessing: generate data cleaning code, run in sandbox,
    ReAct retry on error.

    Reads: state.plan.cleaning, state.file_path
    Writes: state.preprocessing_result, state.error
    """
    plan = state.plan
    file_path = state.file_path

    if not plan:
        logger.error("Preprocessing: no Plan available")
        return {
            "error": "Preprocessing: plan not available (Planner may have failed)",
            "preprocessing_result": {"retry_count": 3, "attempts": []},
        }

    cleaning = plan.cleaning

    pre_result = state.preprocessing_result or {}
    retry_count = pre_result.get("retry_count", 0)
    attempts: list[dict[str, str]] = pre_result.get("attempts", [])

    output_dir = pre_result.get("output_dir") or tempfile.mkdtemp(prefix="datainsight_clean_")
    if "output_dir" not in pre_result:
        register_temp_path(output_dir)

    # Choose prompt: fresh generation vs ReAct fix
    if retry_count > 0 and attempts:
        last = attempts[-1]
        prompt = _build_clean_react_fix_prompt(
            cleaning, last["code"], last["error"], file_path, output_dir
        )
        logger.info("Preprocessing: ReAct retry %d/3", retry_count)
    else:
        prompt = _build_clean_code_prompt(cleaning, file_path, output_dir)
        logger.info("Preprocessing: generating cleaning script (fresh)")

    # LLM generates code
    try:
        llm = get_llm(temperature=0)
        response = llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        code = str(raw) if not isinstance(raw, str) else raw
    except Exception as e:
        logger.error("Preprocessing: LLM call failed: %s", e)
        attempts.append({"code": "", "error": f"LLM error: {e}"})
        return {
            "error": f"Preprocessing LLM error: {e}",
            "preprocessing_result": {
                "retry_count": retry_count + 1,
                "attempts": attempts,
                "output_dir": output_dir,
            },
        }

    code = _extract_code_block(code)

    safe, reason = check_static(code)
    if not safe:
        logger.error("Preprocessing: static guard rejected code: %s", reason)
        attempts.append({"code": code, "error": reason})
        return {
            "error": f"Preprocessing: unsafe code rejected — {reason}",
            "preprocessing_result": {
                "retry_count": retry_count + 1,
                "attempts": attempts,
                "output_dir": output_dir,
            },
        }

    fd, script_path = tempfile.mkstemp(suffix=".py", prefix="datainsight_clean_")
    register_temp_path(script_path)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(code)
    logger.info("Preprocessing: script written to %s (%d bytes)", script_path, len(code))

    result: SandboxResult = run_script(
        script_path, [file_path, output_dir], timeout_seconds=_CLEANING_TIMEOUT
    )

    if result.exit_code == 0:
        try:
            json_text = _extract_json(result.stdout)
            parsed = json.loads(json_text)
        except (json.JSONDecodeError, IndexError):
            error_msg = (
                f"Cleaning script exited 0 but produced invalid JSON. "
                f"stdout preview: {result.stdout[:300]}"
            )
            logger.error("Preprocessing: %s", error_msg)
            attempts.append({"code": code, "error": error_msg})
            return {
                "error": error_msg,
                "preprocessing_result": {
                    "retry_count": retry_count + 1,
                    "attempts": attempts,
                    "output_dir": output_dir,
                },
            }

        logger.info("Preprocessing: SUCCESS (attempt %d)", retry_count + 1)
        return {
            "preprocessing_result": {
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
        error_msg = f"[TIMEOUT after {_CLEANING_TIMEOUT}s]\n{error_msg}"

    logger.error("Preprocessing: FAILED (attempt %d/3): %s", retry_count + 1, error_msg[:200])
    attempts.append({"code": code, "error": error_msg})

    return {
        "error": f"Preprocessing error (attempt {retry_count + 1}/3): {error_msg[:500]}",
        "preprocessing_result": {
            "retry_count": retry_count + 1,
            "attempts": attempts,
            "output_dir": output_dir,
        },
    }
