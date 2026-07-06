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
    analysis_intent_json: str | None,
    unified_columns: list[str],
    workspace_plan_json: str | None,
) -> str:
    columns_list = "\n".join(f"  - {c}" for c in unified_columns)

    intent_section = ""
    if analysis_intent_json:
        intent_section = f"""

---

**ANALYSIS INTENT (JSON):**

{analysis_intent_json}
"""

    workspace_section = ""
    if workspace_plan_json:
        workspace_section = f"""

---

**CURRENT WORKSPACE PLAN (JSON):**

{workspace_plan_json}
"""

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
12. If WORKSPACE PLAN is present: the user has an existing workspace. Respect
    the user's built structure — only revise what the user explicitly asked to
    change. If the Intent signals `reset_workspace: true`, ignore the workspace
    and generate a fresh Plan from the Intent + Data Profile.
13. If WORKSPACE PLAN is absent: generate a fresh Plan from the Intent and
    Data Profile.
14. If WORKSPACE PLAN has incomplete units (purpose empty but related_fields
    populated), complete the purpose and model fields.

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
{workspace_section}
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
    """Stage 2 — Planner: unified Plan decision maker.

    Always consumes: workspace_plan, analysis_intent, data_profile, unified_columns.
    LLM decides: generate from scratch, revise existing, or audit + correct.

    Reads: state.data_profile, state.unified_columns, state.analysis_intent, state.plan
    Writes: state.plan (Plan)
    """
    data_profile = state.data_profile
    unified_columns = state.unified_columns
    workspace_plan = state.plan
    analysis_intent = state.analysis_intent

    if not data_profile:
        logger.error("Planner: data_profile is missing from state")
        return {"error": "Planner: data_profile not available (Data Track may have failed)"}

    if not unified_columns:
        logger.error("Planner: unified_columns is empty — Data Track may have failed")
        return {"error": "Planner: unified_columns not available (Data Track may have failed)"}

    data_profile_json = data_profile.model_dump_json(indent=2)
    intent_json = analysis_intent.model_dump_json(indent=2) if analysis_intent else None
    workspace_json = workspace_plan.model_dump_json(indent=2) if workspace_plan else None

    logger.info(
        "Planner: unified path — intent=%s, workspace=%s, cols=%d",
        bool(intent_json),
        bool(workspace_json),
        len(unified_columns),
    )

    prompt = _build_planner_prompt(
        data_profile_json, intent_json, unified_columns, workspace_json,
    )

    try:
        llm = get_llm(temperature=0, node="planner")
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        content = str(content) if not isinstance(content, str) else content
    except Exception as e:
        logger.error("Planner: LLM call failed: %s", e)
        return {"error": f"Planner LLM error: {e}"}

    json_text = _extract_json(content)

    try:
        parsed = json.loads(json_text)
        plan = _parse_plan_from_json(parsed)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error("Planner: failed to parse Plan JSON: %s", e)
        logger.debug("Planner: raw LLM output (first 500 chars): %s", content[:500])
        return {
            "error": f"Planner: failed to parse structured output: {e}",
        }

    logger.info(
        "Planner: plan generated — cleaning + %d analysis unit(s)",
        len(plan.units),
    )

    return {"plan": plan}
