from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from src.agent.nodes.analysis import analysis_node
from src.agent.nodes.preprocessing import preprocessing_node
from src.api.schemas import ExecutionResultResponse, ExecutionStatusResponse, UnitResultResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}/execution", tags=["execution"])

OUTPUT_DIR = Path("data/output")
MAX_RETRIES = 3


def _get_store(request: Request) -> Any:
    return request.app.state.sessions


async def _run_execution(session_id: str, store: Any) -> None:
    """Background task: preprocessing → analysis with ReAct retry."""
    state = store.get(session_id)
    if state is None:
        return

    store.update(session_id, {"error": None})

    for _attempt in range(1, MAX_RETRIES + 1):
        result = preprocessing_node(state)
        store.update(session_id, result)
        state = store.get(session_id)
        assert state is not None

        if not state.error:
            break
        await asyncio.sleep(0.5)

    if state.error:
        msg = f"Preprocessing failed after {MAX_RETRIES} retries: {state.error}"
        store.update(session_id, {"error": msg})
        return

    result = analysis_node(state)
    store.update(session_id, result)


@router.post("/run")
async def run_execution(session_id: str, request: Request) -> dict[str, str]:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")
    if state.plan is None:
        raise HTTPException(400, "No plan to execute — generate a plan first")

    pre_result = state.preprocessing_result
    if pre_result and pre_result.get("status") == "running":
        raise HTTPException(409, "Execution already in progress")

    store.update(
        session_id,
        {"preprocessing_result": {"status": "running"}, "error": None},
    )

    asyncio.create_task(_run_execution(session_id, store))

    return {"status": "accepted"}


@router.get("/status", response_model=ExecutionStatusResponse)
async def get_status(
    session_id: str, request: Request
) -> ExecutionStatusResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    pre = state.preprocessing_result or {}
    ana = state.analysis_result or {}

    if state.error and pre.get("status") != "completed":
        return ExecutionStatusResponse(status="failed", error=state.error)

    pre_status = pre.get("status", "idle")
    ana_status = ana.get("status", "idle")

    if pre_status == "running":
        return ExecutionStatusResponse(status="running", progress="preprocessing")
    if pre_status == "failed":
        err_msg = pre.get("error", "Preprocessing failed")
        return ExecutionStatusResponse(status="failed", error=err_msg)
    if ana_status == "running":
        return ExecutionStatusResponse(status="running", progress="analysis")
    if ana_status == "complete":
        return ExecutionStatusResponse(status="completed")
    if pre_status == "complete" and ana_status == "idle":
        return ExecutionStatusResponse(status="running", progress="analysis")
    return ExecutionStatusResponse(status="idle")


@router.get("/results", response_model=ExecutionResultResponse)
async def get_results(
    session_id: str, request: Request
) -> ExecutionResultResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    pre = state.preprocessing_result or {}
    ana = state.analysis_result or {}
    unit_results_raw: list[dict[str, Any]] = ana.get("unit_results", [])

    units = [
        UnitResultResponse(
            unit_id=u.get("unit_id", 0),
            status=u.get("status", "unknown"),
            stdout=u.get("stdout", ""),
            stderr=u.get("stderr", ""),
            charts=u.get("charts", []),
            insights=u.get("insights", []),
            error=u.get("error"),
        )
        for u in unit_results_raw
    ]

    return ExecutionResultResponse(preprocessing=pre, units=units)


@router.get("/charts/{chart_name}")
async def serve_chart(
    session_id: str, chart_name: str, request: Request
) -> FileResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    ana = state.analysis_result or {}
    output_dir = str(ana.get("output_dir", str(OUTPUT_DIR / session_id)))

    chart_path = Path(output_dir) / chart_name
    resolved = chart_path.resolve()

    allowed_base = Path(output_dir).resolve()
    if not str(resolved).startswith(str(allowed_base)):
        raise HTTPException(403, "Path traversal blocked")

    if not resolved.exists():
        raise HTTPException(404, f"Chart {chart_name} not found")

    return FileResponse(resolved, media_type="image/png")
