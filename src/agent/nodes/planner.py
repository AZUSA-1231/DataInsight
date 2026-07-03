from __future__ import annotations

import json
import logging
import re

from src.agent.llm import get_llm
from src.agent.state import AgentState, Plan, PlanUnit

logger = logging.getLogger(__name__)

_PLAN_SCHEMA = """{
  "cleaning": {
    "purpose": "具体的清洗目标（如：处理缺失值、统一日期格式、移除异常值）",
    "model": null,
    "cautious": "清洗时需注意的事项（如：0值可能是实际销售数据而非缺失）",
    "depends_on": []
  },
  "units": [
    {
      "unit_id": 1,
      "purpose": "分析目标描述（如：按区域和季度分析销售趋势）",
      "model": "推荐方法（如：线性回归 / KMeans / SHAP / 皮尔逊相关）",
      "cautious": "执行该分析时需注意的事项",
      "depends_on": []
    }
  ],
  "alignment_notes": "MANDATORY: 诚实声明数据能否回答用户问题，假设、限制、替代方案"
}"""


def _build_planner_prompt(
    data_profile_json: str, cleaning_insights: str, analysis_intent_json: str
) -> str:
    return f"""You are a data-analysis orchestrator. Your job is to decompose a business
question into a structured execution Plan with one cleaning unit + N independent
analysis units.

CRITICAL RULES:
1. NEVER invent columns that do not appear in the Data Profile.
2. The cleaning unit MUST include a reasoned strategy — explain WHY these
   specific cleaning actions are needed given the data quality issues found.
3. Each analysis unit represents one distinct analytical angle. Every unit
   MUST have a clear, specific purpose. If there's only one thing to analyze,
   output one unit. Don't pad.
4. The "cautious" field on every unit MUST contain concrete, data-aware
   warnings (e.g. "column X has 30% nulls — results may be biased"). Do NOT
   write generic boilerplate like "注意数据质量".
5. The "model" field should recommend a specific method where applicable
   (e.g. "KMeans", "scipy.stats.ttest_ind", "sklearn.linear_model.LinearRegression").
   Use null if no specific model applies.
6. alignment_notes: MANDATORY — explicitly state what the business wants to
   know vs. what the data can actually answer, assumptions made, limitations,
   and a one-sentence honesty statement.
7. Use "expanded_question" (if present in the Intent) as additional context
   alongside "core_question". The expanded version may surface dimensions the
   user didn't explicitly name.
8. The "suggestions" in the Intent are STRONG HINTS from a business analyst.
   Consider each one seriously — adopt those the data supports, reject only
   with a specific data-backed reason (noted in alignment_notes).
9. Use "complexity" to guide unit count: simple → 1-2 units, moderate → 2-3,
   complex → 3-5. More units are NOT better — only add units that answer a
   distinct part of the question.
10. The "caution_notes" in the Intent are general analytical pitfalls. Echo
    relevant ones in per-unit "cautious" fields where applicable.

OUTPUT: ONLY a single JSON object matching this EXACT schema (no markdown fences,
no surrounding text). Every field is required.

Schema:
{_PLAN_SCHEMA}

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


def _build_planner_prompt_with_feedback(
    data_profile_json: str,
    cleaning_insights: str,
    analysis_intent_json: str,
    previous_plan_json: str,
    feedback: str,
) -> str:
    return f"""You are a data-analysis orchestrator. The user has reviewed a previous
analysis report and provided FEEDBACK. Your job is to REVISE the execution Plan
to address the feedback, while staying grounded in the data and business intent.

USER FEEDBACK:
{feedback}

PREVIOUS PLAN (JSON):
{previous_plan_json}

INSTRUCTIONS:
1. Address the user's feedback FIRST — add, remove, or modify units as needed.
2. Keep units that the user did not complain about.
3. Follow ALL CRITICAL RULES from the original plan prompt (rules 1-10).
4. In alignment_notes, note what was revised and why.
5. The "suggestions" in the Intent remain valid — re-check them against the
   revised plan and note any that were newly adopted or rejected.

OUTPUT: ONLY a single JSON object matching this EXACT schema (no markdown fences,
no surrounding text). Every field is required.

Schema:
{_PLAN_SCHEMA}

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
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def planner_node(state: AgentState) -> dict[str, object]:
    """Stage 2 — Planner: decompose business question into structured Plan
    with one cleaning unit + N independent analysis units.

    Reads: state.data_profile, state.cleaning_insights, state.analysis_intent,
           state.feedback, state.plan
    Writes: state.plan (Plan)
    Consumes: state.feedback
    """
    data_profile = state.data_profile
    cleaning_insights = state.cleaning_insights
    analysis_intent = state.analysis_intent
    feedback = state.feedback

    if not data_profile:
        logger.error("Planner: data_profile is missing from state")
        return {"error": "Planner: data_profile not available (Data Track may have failed)"}

    if not analysis_intent:
        logger.error("Planner: analysis_intent is missing from state")
        return {"error": "Planner: analysis_intent missing (Business Track may have failed)"}

    data_profile_json = data_profile.model_dump_json(indent=2)
    insights_text = cleaning_insights or ""
    intent_json = analysis_intent.model_dump_json(indent=2)

    if feedback:
        logger.info("Planner: revising plan based on user feedback (%d chars)", len(feedback))
        prev = state.plan
        previous_plan_json = prev.model_dump_json(indent=2) if prev else "{}"
        prompt = _build_planner_prompt_with_feedback(
            data_profile_json, insights_text, intent_json, previous_plan_json, feedback
        )
    else:
        logger.info(
            "Planner: planning (profile=%d cols, intent=%s)",
            len(data_profile.columns),
            analysis_intent.analysis_type,
        )
        prompt = _build_planner_prompt(data_profile_json, insights_text, intent_json)

    try:
        llm = get_llm(temperature=0, node="planner")
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        content = str(content) if not isinstance(content, str) else content
    except Exception as e:
        logger.error("Planner: LLM call failed: %s", e)
        return {"error": f"Planner LLM error: {e}", "feedback": None}

    json_text = _extract_json(content)

    try:
        parsed = json.loads(json_text)
        cleaning_raw = parsed["cleaning"]
        cleaning = PlanUnit(
            unit_id=0,
            purpose=cleaning_raw["purpose"],
            model=cleaning_raw.get("model"),
            cautious=cleaning_raw["cautious"],
            depends_on=cleaning_raw.get("depends_on", []),
        )
        units = [
            PlanUnit(
                unit_id=u["unit_id"],
                purpose=u["purpose"],
                model=u.get("model"),
                cautious=u["cautious"],
                depends_on=u.get("depends_on", []),
            )
            for u in parsed["units"]
        ]
        plan = Plan(
            cleaning=cleaning,
            units=units,
            alignment_notes=parsed["alignment_notes"],
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error("Planner: failed to parse Plan JSON: %s", e)
        logger.debug("Planner: raw LLM output (first 500 chars): %s", content[:500])
        return {
            "error": f"Planner: failed to parse structured output: {e}",
            "feedback": None,
        }

    logger.info(
        "Planner: plan generated — cleaning + %d analysis unit(s)",
        len(plan.units),
    )

    return {"plan": plan, "feedback": None}
