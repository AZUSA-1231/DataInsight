"""Active session-scoped API entry point for the bounded Copilot."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from fastapi import APIRouter, HTTPException, Request

from src.agent.copilot import (
    CopilotInvalidMessageError,
    CopilotSessionNotFoundError,
    CopilotThreadNotFoundError,
    CopilotTurnHandler,
    CopilotTurnResult,
)
from src.agent.copilot_tools import PlanEditGateway, build_copilot_tool_bindings
from src.api.schemas import CopilotTurnRequest
from src.api.session import SessionStore

router = APIRouter(prefix="/api/sessions/{session_id}/copilot", tags=["copilot"])


def _get_store(request: Request) -> SessionStore:
    return cast(SessionStore, request.app.state.sessions)


def _build_handler(request: Request, store: SessionStore) -> CopilotTurnHandler:
    """Build one request handler with optional app-state test/development wiring."""

    llm_factory = getattr(request.app.state, "copilot_llm_factory", None)
    plan_edit_gateway = getattr(request.app.state, "copilot_plan_edit_gateway", None)
    typed_llm_factory = cast(Callable[[], object] | None, llm_factory)
    typed_gateway = cast(PlanEditGateway | None, plan_edit_gateway)
    return CopilotTurnHandler(
        store,
        llm_factory=typed_llm_factory,
        tools=build_copilot_tool_bindings(typed_gateway),
    )


@router.post("", response_model=CopilotTurnResult)
async def send_copilot_turn(
    session_id: str,
    body: CopilotTurnRequest,
    request: Request,
) -> CopilotTurnResult:
    """Handle one normal or slash-skilled Copilot turn."""

    store = _get_store(request)
    handler = _build_handler(request, store)
    try:
        return handler.handle(
            session_id,
            body.message,
            thread_id=body.thread_id,
        )
    except CopilotSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except CopilotThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agent Thread not found") from exc
    except CopilotInvalidMessageError as exc:
        raise HTTPException(status_code=422, detail="Message must not be blank") from exc
