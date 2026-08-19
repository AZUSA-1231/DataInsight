from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from src.agent.input_guard import sanitize_user_input
from src.agent.llm import get_llm
from src.agent.nodes.business_track import business_track_node
from src.agent.state import PlannerInstruction
from src.api.schemas import DialogueRequest, DialogueResponse
from src.api.session import SessionStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}/dialogue", tags=["dialogue"])


def _get_store(request: Request) -> SessionStore:
    return cast(SessionStore, request.app.state.sessions)


def _thread_history(thread: object) -> list[dict[str, str]]:
    """Project a Thread for the legacy Business Track adapter only."""

    messages = getattr(thread, "messages", [])
    history: list[dict[str, str]] = []
    for message in messages:
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        if role in {"user", "assistant"} and isinstance(content, str) and content:
            history.append({"role": role, "content": content})
    return history


@router.post("", response_model=DialogueResponse)
async def send_message(
    session_id: str, body: DialogueRequest, request: Request
) -> DialogueResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    thread = store.ensure_default_thread(session_id)
    user_message = sanitize_user_input(body.message, 2000)
    store.update(session_id, {"user_requirement": user_message})
    updated = store.get(session_id)
    assert updated is not None

    compatibility_history = _thread_history(thread)
    compatibility_history.append({"role": "user", "content": user_message})
    bt_state = updated.model_copy(update={"dialogue_history": compatibility_history})

    result, bt_meta = business_track_node(bt_state)
    if "error" in result:
        raise HTTPException(400, str(result["error"]))

    # Save state fields to session
    state_update: dict[str, object] = {}
    if "analysis_intent" in result and result["analysis_intent"] is not None:
        state_update["analysis_intent"] = result["analysis_intent"]
    if "planner_instruction" in result and result["planner_instruction"] is not None:
        state_update["planner_instruction"] = result["planner_instruction"]
    if "feedback" in result:
        state_update["feedback"] = result["feedback"]

    # Append the compatibility turn to the addressed Project Thread. The
    # legacy global dialogue_history field remains untouched after migration.
    bt_response: str = str(bt_meta.get("_bt_response", ""))
    if bt_response:
        store.append_agent_turn(session_id, thread.thread_id, user_message, bt_response)

    if state_update:
        store.update(session_id, state_update)

    final = store.get(session_id)
    assert final is not None

    tool_called = bool(bt_meta.get("_bt_tool_called", False))
    instruction = result.get("planner_instruction")

    if tool_called and isinstance(instruction, PlannerInstruction):
        inst_dict: dict[str, object] = instruction.model_dump()
        return DialogueResponse(
            action="confirm",
            message=bt_response,
            instruction=inst_dict,
            is_contextualized=final.plan is not None
            and bool(final.unified_columns or final.snapshot_registry),
        )

    return DialogueResponse(
        action="chat",
        message=bt_response,
        is_contextualized=final.plan is not None
        and bool(final.unified_columns or final.snapshot_registry),
    )


def _extract_chunk_text(chunk: Any) -> str:  # noqa: ANN401
    """Extract text from a LangChain streaming chunk robustly."""
    content = getattr(chunk, "content", None)
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)

    return str(content)


def _build_fallback_prompt(user_message: str) -> str:
    """Simple conversational prompt used when BT fails — no structured output."""
    return f"""You are a friendly data analyst assistant. The user said:

{user_message}

Respond conversationally in 2-4 sentences. Match the user's language.
Do NOT output JSON or code fences — just natural language."""


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

    message = sanitize_user_input(message, 2000)
    thread = store.ensure_default_thread(session_id)
    store.update(session_id, {"user_requirement": message})

    updated = store.get(session_id)
    assert updated is not None

    compatibility_history = _thread_history(thread)
    compatibility_history.append({"role": "user", "content": message})
    bt_state = updated.model_copy(update={"dialogue_history": compatibility_history})

    # BT Agent call (non-streaming, with agent loop for tool calling)
    bt_result, bt_meta = business_track_node(bt_state)

    # Save state fields to session
    state_update: dict[str, object] = {}
    if "error" not in bt_result:
        if "analysis_intent" in bt_result and bt_result["analysis_intent"] is not None:
            state_update["analysis_intent"] = bt_result["analysis_intent"]
        if "planner_instruction" in bt_result and bt_result["planner_instruction"] is not None:
            state_update["planner_instruction"] = bt_result["planner_instruction"]
        if "feedback" in bt_result:
            state_update["feedback"] = bt_result["feedback"]

    # Persist successful compatibility turns in the Project Thread, not in the
    # retired global history field.
    explanation: str = str(bt_meta.get("_bt_response", ""))
    if "error" not in bt_result and explanation:
        store.append_agent_turn(session_id, thread.thread_id, message, explanation)

    if state_update:
        store.update(session_id, state_update)

    instruction = bt_result.get("planner_instruction")
    tool_called: bool = bool(bt_meta.get("_bt_tool_called", False))
    bt_error: str | None = str(bt_result["error"]) if "error" in bt_result else None

    async def _event_stream() -> Any:  # noqa: ANN401
        try:
            if bt_error or not explanation:
                # Fallback: BT failed — call LLM directly with simple prompt
                logger.warning(
                    "Dialogue: BT failed, using fallback streaming. Error: %s", bt_error
                )
                llm = get_llm(temperature=0)
                fallback_prompt = _build_fallback_prompt(message)
                full = ""
                async for chunk in llm.astream(fallback_prompt):
                    text = _extract_chunk_text(chunk)
                    if text:
                        full += text
                        yield f"event: token\ndata: {json.dumps(text)}\n\n"
                store.append_agent_turn(
                    session_id,
                    thread.thread_id,
                    message,
                    full.strip() or "No assistant response was generated.",
                )
                fb_done = json.dumps({"action": "chat", "full_text": full.strip()})
                yield f"event: done\ndata: {fb_done}\n\n"
                return

            # Emit status: thinking
            yield f"event: status\ndata: {json.dumps({'status': 'thinking'})}\n\n"

            # Stream explanation character by character (simulated typing)
            full = ""
            for char in explanation:
                full += char
                yield f"event: token\ndata: {json.dumps(char)}\n\n"
                await asyncio.sleep(0.01)

            # Emit tool_call event if BT called a tool
            if tool_called and isinstance(instruction, PlannerInstruction):
                inst_dict: dict[str, object] = instruction.model_dump()
                tc_data = json.dumps({
                    "name": "submit_planner_instruction",
                    "args": inst_dict,
                })
                yield f"event: tool_call\ndata: {tc_data}\n\n"

            # Emit done event
            action = "confirm" if tool_called else "chat"
            done_data: dict[str, object] = {"action": action, "full_text": full.strip()}
            if tool_called and isinstance(instruction, PlannerInstruction):
                done_data["instruction"] = instruction.model_dump()
            yield f"event: done\ndata: {json.dumps(done_data)}\n\n"

        except Exception as e:
            logger.error("Dialogue SSE error: %s", e)
            yield f"event: sse_error\ndata: {json.dumps(str(e))}\n\n"

    return StreamingResponse(_event_stream(), media_type="text/event-stream")
