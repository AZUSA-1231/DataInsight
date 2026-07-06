from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from src.agent.llm import get_llm
from src.agent.nodes.business_track import (
    _build_contextualized_intent_prompt,
    _build_intent_prompt,
    business_track_node,
)
from src.api.schemas import DialogueRequest, DialogueResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}/dialogue", tags=["dialogue"])


def _get_store(request: Request) -> Any:
    return request.app.state.sessions


@router.post("", response_model=DialogueResponse)
async def send_message(
    session_id: str, body: DialogueRequest, request: Request
) -> DialogueResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    store.update(session_id, {"user_requirement": body.message})
    updated = store.get(session_id)
    assert updated is not None

    result = business_track_node(updated)
    if "error" in result:
        raise HTTPException(400, str(result["error"]))
    store.update(session_id, result)

    final = store.get(session_id)
    assert final is not None
    intent = final.analysis_intent
    assert intent is not None
    return DialogueResponse(
        intent=intent,
        is_contextualized=final.plan is not None and bool(final.unified_columns),
    )


@router.get("/stream")
async def stream_intent(
    session_id: str,
    request: Request,
    message: str = Query(..., description="User message to stream"),
) -> StreamingResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    store.update(session_id, {"user_requirement": message})
    updated = store.get(session_id)
    assert updated is not None

    if updated.plan is not None and updated.unified_columns:
        prompt = _build_contextualized_intent_prompt(
            message,
            updated.plan.model_dump_json(indent=2),
            updated.unified_columns,
            feedback=updated.feedback,
        )
    else:
        prompt = _build_intent_prompt(message)

    async def _event_stream() -> Any:  # noqa: ANN401
        try:
            llm = get_llm(temperature=0)
            full = ""
            async for chunk in llm.astream(prompt):
                c = chunk.content if hasattr(chunk, "content") else str(chunk)
                if c:
                    text = c if isinstance(c, str) else str(c)
                    full += text
                    yield f"data: {json.dumps({'event': 'token', 'data': text})}\n\n"

            raw = full.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()

            yield f"data: {json.dumps({'event': 'done', 'data': raw})}\n\n"
        except Exception as e:
            logger.error("Dialogue SSE error: %s", e)
            yield f"data: {json.dumps({'event': 'error', 'data': str(e)})}\n\n"

    return StreamingResponse(_event_stream(), media_type="text/event-stream")
