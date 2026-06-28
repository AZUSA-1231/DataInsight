from __future__ import annotations

import logging

from src.agent.llm import get_llm
from src.agent.state import AgentState

logger = logging.getLogger(__name__)


def _build_business_prompt(user_requirement: str) -> str:
    return f"""You are a senior business analyst. Your ONLY job is to derive an ideal analysis
framework from the user's business question. You do NOT have access to the data yet —
think purely from business logic.

DO NOT mention specific column names, DO NOT reference the data file, DO NOT
suggest data cleaning steps. You are the BUSINESS track — stay in your lane.

Report structure (use exactly these headings in Chinese):

## 业务分析蓝图

### 1. 业务问题重述
Restate the user's business question in your own words. Clarify any implicit
assumptions and define the scope of analysis.

### 2. 理想指标体系
List the KPIs and metrics that would best answer this question (assuming perfect data):
- For each metric: define it precisely, explain WHY it matters, and specify the
  ideal granularity (daily/weekly/monthly? by segment or overall?).
- Mark metrics as **[核心]** (must-have) or **[补充]** (nice-to-have).

### 3. 维度与切分
What dimensions, filters, and comparison baselines are needed:
- Time dimension: what period? Year-over-year? Month-over-month?
- Segment dimensions: by category? by region? by user type?
- Comparison baselines: what is the "normal" to compare against?

### 4. 理想图表方案
Describe the ideal visualization strategy to tell this story:
- Chart types (bar, line, scatter, heatmap, etc.) and what each communicates
- Dashboard layout logic (which charts should be viewed together?)
- Key insights each chart should reveal

### 5. 数据需求清单
Abstract data requirements (do NOT reference specific columns):
- What fields are essential (e.g., "a timestamp column for time-series analysis")?
- What fields would be helpful but not essential?
- What external data would improve the analysis if available?

---

**USER'S BUSINESS QUESTION:**

{user_requirement}
"""


def business_track_node(state: AgentState) -> AgentState:
    """Stage 1 (parallel) — Business Track: derive ideal metrics from user's business question.

    Reads: state["user_requirement"]
    Writes: state["business_plan"]
    """
    user_requirement = state["user_requirement"]
    logger.info("Business Track: analyzing requirement (%d chars)", len(user_requirement))

    prompt = _build_business_prompt(user_requirement)

    try:
        llm = get_llm(temperature=0)
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        content = content if isinstance(content, str) else str(content)
    except Exception as e:
        logger.error("Business Track: LLM call failed: %s", e)
        return {**state, "error": f"Business Track LLM error: {e}"}

    logger.info("Business Track: plan generated (%d chars)", len(content))
    return {**state, "business_plan": content}
