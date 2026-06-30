from __future__ import annotations

import logging

from src.agent.llm import get_llm
from src.agent.state import AgentState

logger = logging.getLogger(__name__)


def _build_decision_prompt(
    data_profile_json: str, cleaning_insights: str, analysis_intent_json: str
) -> str:
    return f"""You are a data-analysis architect. Your job is to bridge business goals with
data reality. You receive a structured Data Profile (columns, types, statistics),
Cleaning Insights (quality issues found), and a structured Analysis Intent
(the user's analytical goal in JSON). Your output is a concrete, prioritized
Execution Plan.

CRITICAL RULES:
1. NEVER invent columns that do not appear in the Data Profile.
2. When a business metric cannot be computed from available data, you MUST flag it
   as **[不可实现]** and propose the closest feasible alternative.
3. If a column flagged as **[严重缺失/建议禁用]** (>90% missing) appears essential
   to a core metric, flag it as **[阻塞]** and explain why the pipeline cannot proceed.
4. Use the Cleaning Insights to prioritize preprocessing steps.

Report structure (use exactly these headings in Chinese):

## 分析执行计划

### 1. 指标可行性映射
For each dimension and target in the Analysis Intent:
- Which column(s) from the Data Profile can compute it?
- Feasibility: **[可直接实现]** / **[需清洗后实现]** / **[需替代方案]** / **[不可实现]**
- Confidence: High / Medium / Low

### 2. 数据缺口与替代方案
- Intent dimensions that have NO matching data column → flag as gap
- Proposed alternative: what is the closest approximation we CAN compute?
- If a gap is a showstopper, say so explicitly.

### 3. 清洗优先级
Based on the Cleaning Insights, rank cleaning actions by urgency:
- **[阻断项]**: must clean before ANY analysis (e.g., >90% missing key column)
- **[高优先]**: strongly affects result quality
- **[低优先]**: cosmetic or optional

### 4. 分析执行步骤
Numbered, ordered list of concrete steps to execute in the sandbox:
1. Data loading & type correction
2. Cleaning steps (drop, impute, encode — be specific per column)
3. EDA steps (correlations, distributions, group-bys)
4. Modeling steps (if applicable)
5. Chart generation (specific charts with specific columns)

### 5. 数据与业务对齐备忘
This section is MANDATORY. Explicitly state:
- What the business wants to know vs. what the data can actually answer
- Any assumptions made in bridging the gap
- Limitations the report reader should be aware of
- A one-sentence honesty statement: "基于当前数据，本报告能够/无法完全回答用户问题，原因在于..."

---

**DATA PROFILE (JSON):**

{data_profile_json}

---

**CLEANING INSIGHTS:**

{cleaning_insights}

---

**ANALYSIS INTENT (JSON):**

{analysis_intent_json}
"""


def _build_decision_prompt_with_feedback(
    data_profile_json: str,
    cleaning_insights: str,
    analysis_intent_json: str,
    previous_execution_plan: str,
    feedback: str,
) -> str:
    return f"""You are a data-analysis architect. The user has reviewed a previous analysis
report and provided FEEDBACK. Your job is to REVISE the execution plan to address
the feedback, while staying grounded in the data profile and analysis intent.

USER FEEDBACK:
{feedback}

PREVIOUS EXECUTION PLAN:
{previous_execution_plan}

INSTRUCTIONS:
1. Address the user's feedback FIRST — revise relevant sections of the plan.
2. Keep sections that the user did not complain about.
3. Follow the same structure and rules as the original plan.
4. The user's feedback may require different charts, different groupings,
   different cleaning approaches, or different metrics — be flexible.

Report structure (same as before, use exactly these headings in Chinese):

## 分析执行计划 [修订版]

### 1. 指标可行性映射
(Updated based on feedback. Mark changed items with **[已修订]**)

### 2. 数据缺口与替代方案

### 3. 清洗优先级

### 4. 分析执行步骤

### 5. 数据与业务对齐备忘

---

**DATA PROFILE (JSON):**

{data_profile_json}

---

**CLEANING INSIGHTS:**

{cleaning_insights}

---

**ANALYSIS INTENT (JSON):**

{analysis_intent_json}
"""


def decision_match_node(state: AgentState) -> dict[str, object]:
    """Stage 2 — Decision Match (Planner): align structured analysis intent with
    available data, produce execution plan. Supports feedback-driven revision.

    Reads: state.data_profile, state.cleaning_insights, state.analysis_intent,
           state.feedback, state.execution_plan
    Writes: state.execution_plan
    Consumes: state.feedback
    """
    data_profile = state.data_profile
    cleaning_insights = state.cleaning_insights
    analysis_intent = state.analysis_intent
    feedback = state.feedback

    if not data_profile:
        logger.error("Decision Match: data_profile is missing from state")
        return {"error": "Decision Match: data_profile not available (Data Track may have failed)"}

    if not analysis_intent:
        logger.error("Decision Match: analysis_intent is missing from state")
        return {"error": "Decision Match: analysis_intent missing (Business Track may have failed)"}

    data_profile_json = data_profile.model_dump_json(indent=2)
    insights_text = cleaning_insights or ""
    intent_json = analysis_intent.model_dump_json(indent=2)

    if feedback:
        logger.info(
            "Decision Match: revising plan based on user feedback (%d chars)", len(feedback)
        )
        previous_plan = state.execution_plan or ""
        prompt = _build_decision_prompt_with_feedback(
            data_profile_json, insights_text, intent_json, previous_plan, feedback
        )
    else:
        logger.info(
            "Decision Match: aligning (profile=%d cols, intent=%s)",
            len(data_profile.columns),
            analysis_intent.analysis_type,
        )
        prompt = _build_decision_prompt(data_profile_json, insights_text, intent_json)

    try:
        llm = get_llm(temperature=0)
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        content = str(content) if not isinstance(content, str) else content
    except Exception as e:
        logger.error("Decision Match: LLM call failed: %s", e)
        return {"error": f"Decision Match LLM error: {e}"}

    logger.info("Decision Match: execution plan generated (%d chars)", len(content))

    return {"execution_plan": content, "feedback": None}
