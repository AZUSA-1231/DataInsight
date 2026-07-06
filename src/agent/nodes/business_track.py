from __future__ import annotations

import json
import logging

from src.agent.llm import get_llm
from src.agent.state import AgentState, AnalysisIntent, Suggestion

logger = logging.getLogger(__name__)

_INTENT_SCHEMA = """{
  "core_question": "string — the user's business question restated precisely",
  "target_variable": "string | null — the main metric/KPI to explain or predict",
  "analysis_type": "string — one of: descriptive, diagnostic, predictive, comparative, trend",
  "dimensions": ["string", ...] — segmentation dimensions (time, region, category, etc.)",
  "comparison_baseline": "string | null — baseline period or group to compare against",
  "complexity": "string — 'simple', 'moderate', or 'complex'",
  "expanded_question": "string | null — enriched for short questions; null if already detailed",
  "suggestions": [
    {
      "category": "dimension|method|comparison|caution",
      "content": "具体的建议（如：按时间维度分解以发现季节性模式）",
      "rationale": "为什么这个建议是合理的"
    }
  ],
  "caution_notes": "string | null — analytical pitfalls (e.g. 'correlation != causation')"
}"""


def _build_intent_prompt(user_requirement: str) -> str:
    return f"""You are a precision business analyst. Your job is to understand the user's
business question and produce a structured analysis brief with intelligent
suggestions for the downstream Planner.

PHASE 1 — CLASSIFY the question:
- "simple": 1-2 words, no dimension mentioned (e.g. "分析销售", "看看数据")
- "moderate": has a clear target or dimension, but not multi-part
- "complex": multi-part question, nested conditions, or requires multiple analytical angles

PHASE 2 — EXPAND short questions:
If the question is simple/vague, produce an `expanded_question` that adds
plausible business dimensions a competent analyst would consider (time trends,
geographic breakdown, category comparison, segment analysis). Do NOT invent
topics the user didn't ask about — only add dimensions that naturally apply.

PHASE 3 — STRUCTURE complex questions:
If the question is complex, break it into its constituent analytical angles.
The `dimensions` field should capture ALL segmentation axes mentioned or implied.

PHASE 4 — GENERATE suggestions:
For EVERY question (simple, moderate, or complex), produce 2-5 suggestions
for the Planner. These are strong hints, NOT requirements — the Planner may
reject them if the data doesn't support them. Each suggestion must have:
- category: "dimension" (segmentation), "method" (analytical technique),
  "comparison" (baseline/benchmark), or "caution" (pitfall to avoid)
- content: a specific, actionable recommendation
- rationale: WHY this suggestion makes sense for THIS question

CRITICAL RULES:
1. Output ONLY the JSON object. No markdown fences, no preamble.
2. Do NOT invent column names — you have NO access to the data.
3. analysis_type MUST be one of: descriptive, diagnostic, predictive, comparative, trend
4. dimensions should be conceptual (e.g. "time period", "region"), not column names
5. expanded_question: set to null if the original question is already detailed enough
6. suggestions: 2-5 entries; prioritize the MOST impactful angles first
7. caution_notes: mention general analytical pitfalls (NOT data-specific — Planner handles that)

JSON schema:
{_INTENT_SCHEMA}

---

USER'S BUSINESS QUESTION:

{user_requirement}
"""


def _parse_suggestions(raw: list[dict[str, object]]) -> list[Suggestion]:
    """Parse a list of raw suggestion dicts into Suggestion models.

    Entries missing category, content, or rationale are silently skipped.
    """
    suggestions: list[Suggestion] = []
    for item in raw:
        try:
            category = str(item.get("category", ""))
            content = str(item.get("content", ""))
            rationale = str(item.get("rationale", ""))
            if not category or not content or not rationale:
                continue
            suggestions.append(
                Suggestion(category=category, content=content, rationale=rationale)
            )
        except (KeyError, TypeError, ValueError):
            continue
    return suggestions


def _build_contextualized_intent_prompt(
    user_requirement: str,
    workspace_plan_json: str,
    unified_columns: list[str],
    feedback: str | None = None,
) -> str:
    columns_list = "\n".join(f"  - {c}" for c in unified_columns)
    feedback_section = ""
    if feedback:
        feedback_section = f"""
---

**USER FEEDBACK (from previous report):**

{feedback}
"""
    return f"""You are a precision business analyst. The user has an EXISTING workspace Plan
and is providing additional dialogue (and optionally feedback). Your job is to
produce a Contextualized AnalysisIntent that understands the dialogue RELATIVE
to the workspace.

WORKSPACE PLAN (JSON):
{workspace_plan_json}

AVAILABLE COLUMNS:
{columns_list}
{feedback_section}

TASK:
1. Analyze the user's dialogue against the workspace. Which unit(s) are they
   referring to? What change are they requesting?
2. If the user says "推倒重来/全部重做/重新开始", mark `reset_workspace: true`
   in the Intent.
3. If the user mentions specific column names, verify they exist in AVAILABLE
   COLUMNS. If the workspace unit's related_fields don't include them, note this.
4. Produce a structured AnalysisIntent where:
   - `core_question`: the user's request contextualized against the workspace
   - `suggestions`: grouped by unit_id, each suggesting what to change
   - Other fields follow the standard Intent schema

CRITICAL RULES:
1. Output ONLY the JSON object. No markdown fences, no preamble.
2. Understand that this is a REVISION context — the user is modifying existing work.
3. If the user's dialogue is vague ("改进一下"), infer from the workspace what
   could be improved and suggest specific changes.
4. If feedback is provided, treat it as the PRIMARY signal — the user saw the
   report and is telling you what's wrong.

JSON schema:
{_INTENT_SCHEMA}

---

USER'S DIALOGUE:

{user_requirement}
"""


def business_track_node(state: AgentState) -> dict[str, object]:
    """Stage 1b — Business Track: extract structured AnalysisIntent.

    Workspace-aware: when state.plan is present, the user's dialogue is
    interpreted relative to the workspace (Contextualized Intent). When
    workspace is empty, operates as a pure NL→Intent translator.

    Reads: state.user_requirement, state.plan, state.unified_columns, state.feedback
    Writes: state.analysis_intent
    Consumes: state.feedback
    """
    workspace_plan = state.plan
    unified_columns = state.unified_columns
    feedback = state.feedback

    if workspace_plan is not None and unified_columns:
        logger.info(
            "Business Track: workspace-aware intent (%d units, %d cols, feedback=%s)",
            len(workspace_plan.units),
            len(unified_columns),
            bool(feedback),
        )
        prompt = _build_contextualized_intent_prompt(
            state.user_requirement,
            workspace_plan.model_dump_json(indent=2),
            unified_columns,
            feedback=feedback,
        )
    else:
        logger.info("Business Track: pure translator mode (%d chars)", len(state.user_requirement))
        prompt = _build_intent_prompt(state.user_requirement)

    try:
        llm = get_llm(temperature=0)
        response = llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        raw = str(raw) if not isinstance(raw, str) else raw
    except Exception as e:
        logger.error("Business Track: LLM call failed: %s", e)
        return {"error": f"Business Track LLM error: {e}"}

    # Strip markdown code fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        data = json.loads(raw)
        intent = AnalysisIntent(
            core_question=str(data.get("core_question", "")),
            target_variable=data.get("target_variable"),
            analysis_type=str(data.get("analysis_type", "descriptive")),
            dimensions=[str(d) for d in data.get("dimensions", [])],
            comparison_baseline=data.get("comparison_baseline"),
            # M3: new fields with backward-compatible defaults
            expanded_question=data.get("expanded_question"),
            complexity=str(data.get("complexity", "moderate")),
            suggestions=_parse_suggestions(data.get("suggestions", [])),
            caution_notes=data.get("caution_notes"),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error("Business Track: failed to parse intent JSON: %s", e)
        return {"error": f"Business Track: intent JSON parse failed: {e}"}

    logger.info(
        "Business Track: intent parsed (type=%s, complexity=%s, %d dimensions, %d suggestions)",
        intent.analysis_type,
        intent.complexity,
        len(intent.dimensions),
        len(intent.suggestions),
    )
    return {"analysis_intent": intent, "feedback": None}
