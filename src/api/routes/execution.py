from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from src.agent.checkpoints import CheckpointError
from src.agent.dag import rerun_dag
from src.agent.nodes.analysis import _execute_unit, analysis_node
from src.api.schemas import (
    ExecutionResultResponse,
    ExecutionStatusResponse,
    RerunUnitResponse,
    UnitResultResponse,
)
from src.api.session import SessionStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}/execution", tags=["execution"])

OUTPUT_DIR = Path("data/output")


def _get_store(request: Request) -> SessionStore:
    return cast(SessionStore, request.app.state.sessions)


def _chart_reference(session_id: str, chart: object) -> str | None:
    """Convert a stored chart path to a session-relative API reference."""
    if not isinstance(chart, str) or not chart:
        return None
    allowed_base = (OUTPUT_DIR / session_id).resolve()
    candidate = Path(chart)
    resolved = candidate.resolve()
    try:
        return resolved.relative_to(allowed_base).as_posix()
    except ValueError:
        logger.warning("Ignoring chart outside session output: %s", chart)
        return None


def _chart_references(session_id: str, charts: object) -> list[str]:
    if not isinstance(charts, list):
        return []
    return [ref for chart in charts if (ref := _chart_reference(session_id, chart))]


async def _run_execution(session_id: str, store: SessionStore) -> None:
    """Background task: execute analysis directly on original data."""
    state = store.get(session_id)
    if state is None:
        return

    state = store.update(session_id, {"error": None})

    try:
        result = analysis_node(state)
    except Exception as exc:
        logger.error("Execution failed for session %s: %s", session_id, exc)
        result = {"analysis_result": {"status": "failed"}, "error": str(exc)}

    store.update(session_id, result)


@router.post("/run")
async def run_execution(session_id: str, request: Request) -> dict[str, str]:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")
    if state.plan is None:
        raise HTTPException(400, "No plan to execute — generate a plan first")

    ana_result = state.analysis_result
    if ana_result and ana_result.get("status") == "running":
        raise HTTPException(409, "Execution already in progress")

    output_dir = OUTPUT_DIR / session_id / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    store.update(
        session_id,
        {
            "analysis_result": {
                "status": "running",
                "output_dir": str(output_dir),
                "unit_results": [],
            },
            "error": None,
        },
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

    ana = state.analysis_result or {}
    ana_status = ana.get("status", "idle")

    if state.error and ana_status != "complete":
        return ExecutionStatusResponse(status="failed", error=state.error)
    if ana_status == "running":
        return ExecutionStatusResponse(status="running", progress="analysis")
    if ana_status == "complete" or ana_status == "partial":
        return ExecutionStatusResponse(status="completed")
    return ExecutionStatusResponse(status="idle")


@router.get("/results", response_model=ExecutionResultResponse)
async def get_results(
    session_id: str, request: Request
) -> ExecutionResultResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    ana = state.analysis_result or {}
    unit_results_raw: list[dict[str, Any]] = ana.get("unit_results", [])

    units = [
        UnitResultResponse(
            unit_id=u.get("unit_id", 0),
            status=u.get("status", "unknown"),
            stdout=u.get("stdout", ""),
            stderr=u.get("stderr", ""),
            charts=_chart_references(session_id, u.get("charts", [])),
            insights=u.get("insights", []),
            error=u.get("error"),
            stale=u.get("stale", False),
            run_id=u.get("run_id"),
            input_checkpoint_ids=u.get("input_checkpoint_ids", []),
            output_checkpoint_id=u.get("output_checkpoint_id"),
            row_count_before=u.get("row_count_before"),
            row_count_after=u.get("row_count_after"),
            row_count_delta=u.get("row_count_delta"),
            input_row_counts=u.get("input_row_counts", []),
            statistics=u.get("statistics", {}),
            warnings=u.get("warnings", []),
        )
        for u in unit_results_raw
    ]

    stale_unit_ids = [
        int(unit.unit_id) for unit in units if unit.stale
    ]
    return ExecutionResultResponse(
        units=units,
        status=str(ana.get("status", "idle")),
        run_id=ana.get("run_id") if isinstance(ana.get("run_id"), str) else None,
        stale_unit_ids=stale_unit_ids,
    )


@router.post("/units/{unit_id}/rerun", response_model=RerunUnitResponse)
async def rerun_unit(
    session_id: str,
    unit_id: int,
    request: Request,
    cascade: bool = False,
) -> RerunUnitResponse:
    """Re-execute a single analysis unit using its input checkpoint.

    - ``cascade=false``: rerun only this unit; mark downstream units stale.
    - ``cascade=true``: rerun this unit AND all transitive dependents in order.
    """
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")
    if state.plan is None:
        raise HTTPException(400, "No plan to execute — generate a plan first")

    ana = state.analysis_result or {}
    parent_output_dir = ana.get("output_dir") or str(
        OUTPUT_DIR / session_id / "analysis"
    )

    try:
        patch = rerun_dag(
            state,
            parent_output_dir,
            unit_id,
            cascade=cascade,
            execute_unit_fn=_execute_unit,
        )
    except CheckpointError as exc:
        logger.error("Rerun unit [%d] failed: %s", unit_id, exc)
        status_code = 404 if "not found" in str(exc) else 409
        raise HTTPException(status_code, str(exc)) from exc
    except ValueError as exc:
        logger.error("Rerun unit [%d] rejected: %s", unit_id, exc)
        raise HTTPException(409, str(exc)) from exc

    store.update(
        session_id,
        {
            "analysis_result": patch["analysis_result"],
            "snapshot_registry": patch["snapshot_registry"],
            "checkpoint_registry": patch["checkpoint_registry"],
            "column_graph": patch["column_graph"],
        },
    )

    result = patch.get("rerun_result", {})
    stale_ids = patch.get("stale_unit_ids", [])
    if not isinstance(result, dict):
        result = {}
    if not isinstance(stale_ids, list):
        stale_ids = []

    return RerunUnitResponse(
        unit_id=unit_id,
        status=str(result.get("status", "unknown")),
        stale_units=[int(item) for item in stale_ids],
        input_checkpoint_ids=[
            str(item) for item in result.get("input_checkpoint_ids", [])
            if isinstance(item, str)
        ],
        output_checkpoint_id=(
            str(result["output_checkpoint_id"])
            if isinstance(result.get("output_checkpoint_id"), str)
            else None
        ),
        charts=_chart_references(session_id, result.get("charts", [])),
        insights=result.get("insights", []),
        error=result.get("error"),
        run_id=result.get("run_id"),
        row_count_before=result.get("row_count_before"),
        row_count_after=result.get("row_count_after"),
        row_count_delta=result.get("row_count_delta"),
        warnings=result.get("warnings", []),
    )


@router.get("/charts/{chart_name:path}")
async def serve_chart(
    session_id: str, chart_name: str, request: Request
) -> FileResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    output_dir = str(OUTPUT_DIR / session_id)

    chart_path = Path(output_dir) / chart_name
    resolved = chart_path.resolve()

    allowed_base = Path(output_dir).resolve()
    try:
        resolved.relative_to(allowed_base)
    except ValueError:
        raise HTTPException(403, "Path traversal blocked") from None

    if not resolved.exists():
        raise HTTPException(404, f"Chart {chart_name} not found")

    return FileResponse(resolved, media_type="image/png")
