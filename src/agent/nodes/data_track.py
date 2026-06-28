from __future__ import annotations

import json
import logging
import os

from src.agent.llm import get_llm
from src.agent.state import AgentState
from src.sandbox.executor import SandboxResult, run_script

logger = logging.getLogger(__name__)

_INSPECTION_SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "..", "sandbox", "inspection_script.py"
)


def _build_audit_prompt(inspection_json: str) -> str:
    return f"""You are a strict data auditor. Your ONLY job is to analyze the raw
structural metadata below and produce a 《Data Technical Audit Report》.

DO NOT suggest business metrics, DO NOT recommend analysis methods, DO NOT
mention the user's business question. You are the DATA track — stay in your lane.

Report structure (use exactly these headings in Chinese):

## 数据技术盘报告

### 1. 字段总览
List every column with its dtype, null count, null percentage, and unique count.
Flag columns with >30% missing as **[高缺失]** and columns with >90% missing
as **[严重缺失/建议禁用]**.

### 2. 缺失值诊断
For each column with nulls:
- How many missing? What percentage?
- Is the column likely optional (e.g. many rows missing) or structural (few missing)?
- Could zeros or empty strings be disguised missing values? Check if min is 0.

### 3. 异常值隐患
- Columns where unique count is suspiciously low (potential categorical
  masquerading as numeric)?
- Outliers visible from descriptive statistics (mean vs 50% large gap)?
- Any dtypes that look wrong (e.g. numeric stored as object)?

### 4. 需强清洗字段清单
List columns that MUST be cleaned before any analysis, with concrete action items:
- Drop? Impute (mean/median/mode)? Leave as-is?
- For each cleaning action, state the risk if NOT cleaned.

### 5. 整体数据质量评分
Assign a grade (A/B/C/D/F) and one-sentence justification.

---

**INSPECTION DATA (JSON):**

{inspection_json}
"""


def data_track_node(state: AgentState) -> AgentState:
    """Stage 1 — Data Track: run deterministic inspection, produce audit report.

    Reads: state["file_path"], state["user_requirement"]
    Writes: state["data_report"]
    """
    file_path = state["file_path"]
    logger.info("Data Track: inspecting %s", file_path)

    result: SandboxResult = run_script(_INSPECTION_SCRIPT, [file_path])

    if result.exit_code != 0:
        logger.error("Inspection script failed: %s", result.stderr)
        return {**state, "error": f"Inspection script error: {result.stderr}"}

    try:
        json.loads(result.stdout)
    except json.JSONDecodeError as e:
        logger.error("Inspection output is not valid JSON: %s", e)
        return {**state, "error": f"Failed to parse inspection output: {e}"}

    prompt = _build_audit_prompt(result.stdout)
    llm = get_llm(temperature=0)
    response = llm.invoke(prompt)
    content = response.content if hasattr(response, "content") else str(response)
    data_report = content if isinstance(content, str) else str(content)

    logger.info("Data Track: report generated (%d chars)", len(data_report))
    return {**state, "data_report": data_report}
