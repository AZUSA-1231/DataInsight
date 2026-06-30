from __future__ import annotations

import json
import logging
import re

from src.agent.llm import get_llm
from src.agent.state import AgentState, ExecutionPlan

logger = logging.getLogger(__name__)

_EXECUTION_PLAN_SCHEMA = """{
  "feasibility_map": [
    {
      "intent_dimension": "dimension name",
      "matched_columns": ["col1"],
      "feasibility": "可直接实现",
      "confidence": "High",
      "reasoning": "why this mapping works or doesn't"
    }
  ],
  "model_selections": [
    {
      "analysis_step": "step name",
      "method": "scipy.stats.ttest_ind / sklearn.linear_model.LinearRegression / ...",
      "reasoning": "why this method given the data types and column availability",
      "feasibility": "可直接实现 | 需清洗后实现 | 需替代方案 | 不可实现"
    }
  ],
  "preprocessing_steps": [
    {
      "step": 1,
      "action": "drop_null_columns | impute_median | encode_onehot | ...",
      "target_columns": ["col1", "col2"],
      "urgency": "阻断项 | 高优先 | 低优先",
      "reason": "based on Cleaning Insights"
    }
  ],
  "analysis_steps": [
    {
      "step": 1,
      "action": "compute_correlation | groupby_aggregate | run_ttest | ...",
      "target_columns": ["col1"],
      "method": "pandas .corr() / scipy.stats.ttest_ind / ...",
      "expected_output": "correlation matrix / p-value / chart"
    }
  ],
  "alignment_notes": "MANDATORY honesty statement about what the data can vs cannot answer"
}"""


def _build_decision_prompt(
    data_profile_json: str, cleaning_insights: str, analysis_intent_json: str
) -> str:
    return f"""You are a data-analysis architect. Your job is to bridge business goals with
data reality. You receive a structured Data Profile (columns, types, statistics),
Cleaning Insights (quality issues found), and a structured Analysis Intent
(the user's analytical goal in JSON).

CRITICAL RULES:
1. NEVER invent columns that do not appear in the Data Profile.
2. When a business metric cannot be computed from available data, mark its feasibility
   as "不可实现" and propose the closest feasible alternative in reasoning.
3. If a column flagged as >90% missing appears essential to a core metric, mark it
   as "阻塞" in the preprocessing urgency field.
4. Use the Cleaning Insights to prioritize preprocessing steps.
5. model_selections: for each analysis step, recommend a specific concrete method
   (e.g. "scipy.stats.ttest_ind", "sklearn.linear_model.LinearRegression",
   "pandas.DataFrame.corr"). Include the reasoning chain.
6. alignment_notes: MANDATORY section — explicitly state what the business wants to
   know vs. what the data can actually answer, assumptions made, limitations, and a
   one-sentence honesty statement about whether the data can fully answer the question.

OUTPUT: ONLY a single JSON object matching this EXACT schema (no markdown fences,
no surrounding text). Every field is required.

Schema:
{_EXECUTION_PLAN_SCHEMA}

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
    previous_execution_plan_json: str,
    feedback: str,
) -> str:
    return f"""You are a data-analysis architect. The user has reviewed a previous analysis
report and provided FEEDBACK. Your job is to REVISE the execution plan to address
the feedback, while staying grounded in the data profile and analysis intent.

USER FEEDBACK:
{feedback}

PREVIOUS EXECUTION PLAN (JSON):
{previous_execution_plan_json}

INSTRUCTIONS:
1. Address the user's feedback FIRST — revise relevant parts of the plan.
2. Keep sections that the user did not complain about.
3. Follow the same schema and rules as the original plan.
4. The user's feedback may require different charts, different groupings,
   different cleaning approaches, or different metrics — be flexible.
5. In alignment_notes, note what was revised and why.

OUTPUT: ONLY a single JSON object matching this EXACT schema (no markdown fences,
no surrounding text). Every field is required.

Schema:
{_EXECUTION_PLAN_SCHEMA}

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


def _extract_json(text: str) -> str:
    """Extract JSON object from LLM output, handling markdown fences."""
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    # Try to find first { to last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def decision_match_node(state: AgentState) -> dict[str, object]:
    """Stage 2 — Decision Match (Planner): align structured analysis intent with
    available data, produce structured ExecutionPlan. Supports feedback-driven revision.

    Reads: state.data_profile, state.cleaning_insights, state.analysis_intent,
           state.feedback, state.execution_plan
    Writes: state.execution_plan (ExecutionPlan)
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
        prev = state.execution_plan
        previous_plan_json = prev.model_dump_json(indent=2) if prev else "{}"
        prompt = _build_decision_prompt_with_feedback(
            data_profile_json, insights_text, intent_json, previous_plan_json, feedback
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

    json_text = _extract_json(content)

    try:
        parsed = json.loads(json_text)
        execution_plan = ExecutionPlan(
            feasibility_map=parsed["feasibility_map"],
            model_selections=parsed["model_selections"],
            preprocessing_steps=parsed["preprocessing_steps"],
            analysis_steps=parsed["analysis_steps"],
            alignment_notes=parsed["alignment_notes"],
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error("Decision Match: failed to parse ExecutionPlan JSON: %s", e)
        logger.debug("Decision Match: raw LLM output (first 500 chars): %s", content[:500])
        return {
            "error": f"Decision Match: failed to parse structured output: {e}",
            "feedback": None,
        }

    logger.info(
        "Decision Match: execution plan generated — %d feasibility items, %d models, "
        "%d preproc steps, %d analysis steps",
        len(execution_plan.feasibility_map),
        len(execution_plan.model_selections),
        len(execution_plan.preprocessing_steps),
        len(execution_plan.analysis_steps),
    )

    return {"execution_plan": execution_plan, "feedback": None}
