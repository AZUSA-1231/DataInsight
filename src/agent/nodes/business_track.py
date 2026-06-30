from __future__ import annotations

import json
import logging

from src.agent.llm import get_llm
from src.agent.state import AgentState, AnalysisIntent

logger = logging.getLogger(__name__)

_ANALYSIS_INTENT_SCHEMA = """{
  "core_question": "string — the user's business question restated precisely",
  "target_variable": "string | null — the main metric/KPI to explain or predict",
  "analysis_type": "string — one of: descriptive, diagnostic, predictive, comparative, trend",
  "dimensions": ["string", ...] — segmentation dimensions (time, region, category, etc.)",
  "comparison_baseline": "string | null — baseline period or group to compare against"
}"""


def _build_intent_prompt(user_requirement: str) -> str:
    return f"""You are a precision business analyst. Your ONLY job is to extract a concise,
structured analytical intent from the user's business question. Output VALID JSON
matching the schema below — nothing else.

CRITICAL RULES:
1. Output ONLY the JSON object. No markdown fences, no explanations, no preamble.
2. Do NOT invent column names or assume data fields — you have NO access to the data.
3. Do NOT design metrics beyond what the user's question requires.
4. Keep the analysis_type narrow: descriptive, diagnostic, predictive, comparative, or trend.
5. dimensions should be conceptual (e.g. "time period", "region", "product category")
   not concrete column names.
6. If the user's question does not mention a target variable or baseline, use null.

JSON schema:
{_ANALYSIS_INTENT_SCHEMA}

---

USER'S BUSINESS QUESTION:

{user_requirement}
"""


def business_track_node(state: AgentState) -> dict[str, object]:
    """Stage 1 (parallel) — Business Track: extract structured AnalysisIntent
    from the user's business question.

    Reads: state.user_requirement
    Writes: state.analysis_intent
    """
    logger.info("Business Track: parsing intent (%d chars)", len(state.user_requirement))

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
        raw = raw.split("\n", 1)[-1]  # drop opening fence line
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
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error("Business Track: failed to parse intent JSON: %s", e)
        return {"error": f"Business Track: intent JSON parse failed: {e}"}

    logger.info(
        "Business Track: intent parsed (type=%s, %d dimensions)",
        intent.analysis_type,
        len(intent.dimensions),
    )
    return {"analysis_intent": intent}
