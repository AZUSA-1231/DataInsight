from __future__ import annotations

import logging
from typing import cast

from fastapi import APIRouter, HTTPException, Request

from src.agent.nodes.report_gen import report_gen_node
from src.api.schemas import ReportResponse
from src.api.session import SessionStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}/report", tags=["report"])


def _get_store(request: Request) -> SessionStore:
    return cast(SessionStore, request.app.state.sessions)


@router.post("/generate", response_model=ReportResponse)
async def generate_report(
    session_id: str, request: Request
) -> ReportResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    result = report_gen_node(state)
    store.update(session_id, result)

    final = store.get(session_id)
    assert final is not None
    return ReportResponse(report=final.final_report, error=final.error)


@router.get("", response_model=ReportResponse)
async def get_report(session_id: str, request: Request) -> ReportResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")
    return ReportResponse(report=state.final_report, error=state.error)
