from __future__ import annotations

import json
import logging
import os

from src.agent.llm import get_llm
from src.agent.state import AgentState, ColumnProfile, DataProfile
from src.sandbox.executor import SandboxResult, run_script

logger = logging.getLogger(__name__)

_INSPECTION_SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "..", "sandbox", "inspection_script.py"
)


def _parse_data_profile(inspection_json: str) -> DataProfile:
    """Parse inspection script output into a structured DataProfile."""
    raw = json.loads(inspection_json)

    columns = [
        ColumnProfile(
            name=col["name"],
            dtype=col["dtype"],
            null_count=col["null_count"],
            null_pct=col["null_pct"],
            unique_count=col["unique_count"],
            unique_pct=col["unique_pct"],
        )
        for col in raw["columns"]
    ]

    return DataProfile(
        file_path=raw["file_path"],
        shape=(raw["shape"]["rows"], raw["shape"]["cols"]),
        columns=columns,
        statistics=raw.get("statistics", {}),
        head_sample=raw.get("head", []),
        encoding=raw.get("encoding"),
    )


def _build_cleaning_insights_prompt(data_profile: DataProfile) -> str:
    """Build a prompt asking the LLM for concise cleaning recommendations only."""
    profile_json = data_profile.model_dump_json(indent=2)
    return f"""You are a strict data quality specialist. Your ONLY job is to review the
structured data profile below and produce concise, actionable cleaning recommendations.

DO NOT produce a full audit report. DO NOT suggest business metrics or analysis methods.
You are the DATA track — stay in your lane.

Output structure (use exactly these headings in Chinese):

## 数据清洗建议

### 1. 需强清洗字段
For each column with data quality issues (high null%, wrong dtype, outliers):
- Column name, what is wrong, and the specific cleaning action
- Flag: **[高缺失]** (>30% null), **[严重缺失/建议禁用]** (>90% null), **[类型问题]** (wrong dtype)

### 2. 清洗策略
Concrete, ordered steps for preprocessing:
- Drop columns/rows: which ones and under what threshold?
- Impute missing values: which method (mean/median/mode/forward-fill) per column?
- Type conversions: which columns need dtype fixes?
- Encode categoricals: which columns and which method (one-hot/label)?

### 3. 数据质量总评
One grade (A/B/C/D/F) and one-sentence justification. Be brief.

---
**DATA PROFILE (JSON):**

{profile_json}
"""


def data_track_node(state: AgentState) -> dict[str, object]:
    """Stage 1a — Data Track: deterministic inspection → structured profile,
    then LLM produces concise cleaning insights.

    Reads: state.file_path
    Writes: state.data_profile, state.cleaning_insights
    """
    file_path = state.file_path
    logger.info("Data Track: inspecting %s", file_path)

    result: SandboxResult = run_script(_INSPECTION_SCRIPT, [file_path])

    if result.exit_code != 0:
        logger.error("Inspection script failed: %s", result.stderr)
        return {"error": f"Inspection script error: {result.stderr}"}

    try:
        data_profile = _parse_data_profile(result.stdout)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error("Failed to parse inspection output: %s", e)
        return {"error": f"Failed to parse inspection output: {e}"}

    logger.info(
        "Data Track: profile parsed — %d columns, shape=%s",
        len(data_profile.columns),
        data_profile.shape,
    )

    prompt = _build_cleaning_insights_prompt(data_profile)
    try:
        llm = get_llm(temperature=0)
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        cleaning_insights = str(content) if not isinstance(content, str) else content
    except Exception as e:
        logger.error("Data Track: LLM call failed: %s", e)
        return {
            "error": f"Data Track LLM error: {e}",
            "data_profile": data_profile,
        }

    logger.info("Data Track: cleaning insights generated (%d chars)", len(cleaning_insights))
    return {"data_profile": data_profile, "cleaning_insights": cleaning_insights}
