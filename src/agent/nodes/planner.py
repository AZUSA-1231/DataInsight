from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.agent.llm import get_llm
from src.agent.state import AgentState, Plan, PlanUnit

logger = logging.getLogger(__name__)

_PLAN_SCHEMA = """{
  "cleaning": {
    "purpose": "具体的清洗目标（如：处理缺失值、统一日期格式、移除异常值）",
    "model": null,
    "cautious": "清洗时需注意的事项（如：0值可能是实际销售数据而非缺失）",
    "depends_on": [],
    "related_fields": ["涉及的列名"]
  },
  "units": [
    {
      "unit_id": 1,
      "purpose": "分析目标描述（如：按区域和季度分析销售趋势）",
      "model": "推荐方法（如：线性回归 / KMeans / SHAP / 皮尔逊相关）",
      "cautious": "执行该分析时需注意的事项",
      "depends_on": [],
      "related_fields": ["本单元涉及的列名1", "列名2"]
    }
  ],
  "alignment_notes": "MANDATORY: 诚实声明数据能否回答用户问题，假设、限制、替代方案"
}"""


def _build_planner_prompt(
    data_profile_json: str,
    analysis_intent_json: str,
    unified_columns: list[str],
) -> str:
    columns_list = "\n".join(f"  - {c}" for c in unified_columns)
    return f"""You are a data-analysis orchestrator. Your job is to decompose a business
question into a structured execution Plan with one cleaning unit + N independent
analysis units.

CRITICAL RULES:
1. NEVER invent columns that do not appear in AVAILABLE COLUMNS below. Use exact
   column names only.
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
11. Each unit MUST specify "related_fields" — list the columns from
    AVAILABLE COLUMNS that this unit directly operates on. Never invent
    column names. Use exact names from AVAILABLE COLUMNS. The cleaning
    unit should also list columns it will clean.

OUTPUT: ONLY a single JSON object matching this EXACT schema (no markdown fences,
no surrounding text). Every field is required.

Schema:
{_PLAN_SCHEMA}

---

**AVAILABLE COLUMNS:**

{columns_list}

---

**DATA PROFILE (JSON):**

{data_profile_json}

---

**ANALYSIS INTENT (JSON):**

{analysis_intent_json}
"""


def _build_planner_prompt_with_feedback(
    data_profile_json: str,
    analysis_intent_json: str,
    unified_columns: list[str],
    previous_plan_json: str,
    feedback: str,
) -> str:
    columns_list = "\n".join(f"  - {c}" for c in unified_columns)
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
3. Follow ALL CRITICAL RULES from the original plan prompt (rules 1-11).
4. In alignment_notes, note what was revised and why.
5. The "suggestions" in the Intent remain valid — re-check them against the
   revised plan and note any that were newly adopted or rejected.

OUTPUT: ONLY a single JSON object matching this EXACT schema (no markdown fences,
no surrounding text). Every field is required.

Schema:
{_PLAN_SCHEMA}

---

**AVAILABLE COLUMNS:**

{columns_list}

---

**DATA PROFILE (JSON):**

{data_profile_json}

---

**ANALYSIS INTENT (JSON):**

{analysis_intent_json}
"""


def _build_planner_review_prompt(
    draft_plan_json: str,
    data_profile_json: str,
    unified_columns: list[str],
    analysis_intent_json: str | None,
) -> str:
    columns_list = "\n".join(f"  - {c}" for c in unified_columns)
    intent_section = ""
    if analysis_intent_json:
        intent_section = f"""
---

**ANALYSIS INTENT (JSON, for reference):**

{analysis_intent_json}
"""

    return f"""You are a data-analysis orchestrator in REVIEW mode. The user has
submitted a draft analysis Plan. Your job is to AUDIT and CORRECT it against
the available data.

USER'S DRAFT PLAN (JSON):
{draft_plan_json}

CRITICAL RULES:
1. Validate ALL "related_fields" in every unit against AVAILABLE COLUMNS below.
   Flag any field names that don't exist — replace them with the closest match
   from AVAILABLE COLUMNS, or remove them if no match exists.
2. Check each unit's "purpose" against its "related_fields" — if the purpose
   mentions a dimension or metric that isn't in "related_fields", add the
   missing column(s).
3. If "purpose" mentions an operation on a column type mismatch (e.g.,
   "按地区分组" but no region/category column in related_fields), add it.
4. If "model" is specified and clearly inappropriate for the field types
   (e.g., linear regression on a categorical target with high cardinality),
   suggest a correction and note it in alignment_notes.
5. Preserve the user's original structure as much as possible — only correct
   ACTUAL ERRORS. Do not rewrite units that are valid.
6. If the user omitted the cleaning unit's "related_fields", populate it
   with columns that need cleaning based on the Data Profile (high null%,
   wrong dtype, etc.).
7. "alignment_notes" MUST include a review summary: what was checked, what
   was changed, and why. Format: "审核摘要: [N]处修正 | 修正项: ..."

OUTPUT: ONLY a single JSON object matching this EXACT schema (no markdown fences,
no surrounding text). Every field is required.

Schema:
{_PLAN_SCHEMA}

---

**AVAILABLE COLUMNS:**

{columns_list}

---

**DATA PROFILE (JSON):**

{data_profile_json}
{intent_section}
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


def _parse_plan_from_json(parsed: dict[str, Any]) -> Plan:
    """Build a Plan from parsed JSON, including related_fields."""
    cleaning_raw = parsed["cleaning"]
    cleaning = PlanUnit(
        unit_id=0,
        purpose=cleaning_raw["purpose"],
        model=cleaning_raw.get("model"),
        cautious=cleaning_raw["cautious"],
        depends_on=cleaning_raw.get("depends_on", []),
        related_fields=cleaning_raw.get("related_fields", []),
    )
    units = [
        PlanUnit(
            unit_id=u["unit_id"],
            purpose=u["purpose"],
            model=u.get("model"),
            cautious=u["cautious"],
            depends_on=u.get("depends_on", []),
            related_fields=u.get("related_fields", []),
        )
        for u in parsed["units"]
    ]
    return Plan(
        cleaning=cleaning,
        units=units,
        alignment_notes=parsed["alignment_notes"],
    )


def planner_node(state: AgentState) -> dict[str, object]:
    """Stage 2 — Planner: decompose business question into structured Plan.

    Three modes (checked in priority order):
    1. Feedback mode — user feedback on a previous report → revise Plan
    2. Review mode — draft_plan present → audit & correct
    3. Generate mode — analysis_intent → generate Plan from scratch

    Reads: state.data_profile, state.unified_columns, state.analysis_intent,
           state.draft_plan, state.feedback, state.plan
    Writes: state.plan (Plan)
    Consumes: state.feedback
    """
    data_profile = state.data_profile
    analysis_intent = state.analysis_intent
    unified_columns = state.unified_columns
    draft_plan = state.draft_plan
    feedback = state.feedback

    if not data_profile:
        logger.error("Planner: data_profile is missing from state")
        return {"error": "Planner: data_profile not available (Data Track may have failed)"}

    if not unified_columns:
        logger.error("Planner: unified_columns is empty — Data Track may have failed")
        return {"error": "Planner: unified_columns not available (Data Track may have failed)"}

    data_profile_json = data_profile.model_dump_json(indent=2)

    # Priority: feedback > draft_plan (review mode) > normal generation
    if feedback:
        logger.info("Planner: revising plan based on user feedback (%d chars)", len(feedback))
        previous_plan_json = state.plan.model_dump_json(indent=2) if state.plan else "{}"
        intent_json = analysis_intent.model_dump_json(indent=2) if analysis_intent else "{}"
        prompt = _build_planner_prompt_with_feedback(
            data_profile_json, intent_json, unified_columns,
            previous_plan_json, feedback,
        )
    elif draft_plan is not None:
        logger.info(
            "Planner: REVIEW mode — auditing user draft_plan (%d unit(s))",
            len(draft_plan.units),
        )
        intent_json_rv = analysis_intent.model_dump_json(indent=2) if analysis_intent else None
        prompt = _build_planner_review_prompt(
            draft_plan.model_dump_json(indent=2),
            data_profile_json,
            unified_columns,
            intent_json_rv,
        )
    else:
        if not analysis_intent:
            logger.error("Planner: analysis_intent missing (generate mode requires it)")
            return {"error": "Planner: analysis_intent missing (Business Track may have failed)"}
        logger.info(
            "Planner: GENERATE mode — planning (profile=%d cols, intent=%s)",
            len(data_profile.columns),
            analysis_intent.analysis_type,
        )
        intent_json = analysis_intent.model_dump_json(indent=2)
        prompt = _build_planner_prompt(data_profile_json, intent_json, unified_columns)

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
        plan = _parse_plan_from_json(parsed)
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
