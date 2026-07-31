from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from src.agent.dag import resolve_rerun_input, transitive_dependents
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
        )
        for u in unit_results_raw
    ]

    return ExecutionResultResponse(units=units)


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

    # Find target unit
    target = next((u for u in state.plan.units if u.unit_id == unit_id), None)
    if target is None:
        raise HTTPException(404, f"Unit {unit_id} not found in plan")

    # Resolve input checkpoint
    checkpoint = resolve_rerun_input(target, parent_output_dir)
    input_path = checkpoint if checkpoint else state.file_path

    # Execute the unit
    try:
        result = _execute_unit(target, input_path, parent_output_dir)
    except Exception as exc:
        logger.error("Rerun unit [%d] failed: %s", unit_id, exc)
        raise HTTPException(500, f"Unit {unit_id} execution error: {exc}") from exc

    if not isinstance(result, dict):
        raise HTTPException(500, f"Unexpected result type from unit {unit_id}")

    # Mark unit as not stale in result
    result["stale"] = False

    # Update analysis_result in state
    prev_results = list(ana.get("unit_results", []))
    updated_results = _merge_rerun_result(prev_results, result)

    # Compute stale dependents
    stale_ids: list[int] = []
    if cascade:
        # Rerun transitive dependents in topological order
        dep_ids = transitive_dependents(unit_id, state.plan.units)
        units_by_id = {u.unit_id: u for u in state.plan.units}
        for dep_id in dep_ids:
            dep_unit = units_by_id.get(dep_id)
            if dep_unit is None:
                continue
            dep_checkpoint = resolve_rerun_input(dep_unit, parent_output_dir)
            dep_input = dep_checkpoint if dep_checkpoint else state.file_path
            try:
                dep_result = _execute_unit(dep_unit, dep_input, parent_output_dir)
            except Exception as exc:
                logger.error(
                    "Cascade rerun unit [%d] failed: %s", dep_id, exc,
                )
                dep_result = {
                    "unit_id": dep_id,
                    "status": "failed",
                    "error": str(exc),
                    "charts": [],
                    "insights": [],
                    "stale": False,
                }
            if isinstance(dep_result, dict):
                dep_result["stale"] = False
                updated_results = _merge_rerun_result(updated_results, dep_result)
    else:
        stale_ids = transitive_dependents(unit_id, state.plan.units)
        updated_results = _mark_stale(updated_results, stale_ids)

    store.update(
        session_id,
        {"analysis_result": {**ana, "unit_results": updated_results}},
    )

    return RerunUnitResponse(
        unit_id=unit_id,
        status=result.get("status", "unknown"),
        stale_units=stale_ids,
        charts=_chart_references(session_id, result.get("charts", [])),
        insights=result.get("insights", []),
        error=result.get("error"),
    )


def _merge_rerun_result(
    prev: list[dict[str, object]], new_result: dict[str, object]
) -> list[dict[str, object]]:
    """Replace or append a unit result in the results list."""
    uid = new_result.get("unit_id")
    for i, ur in enumerate(prev):
        if ur.get("unit_id") == uid:
            out = list(prev)
            out[i] = new_result
            return out
    return list(prev) + [new_result]


def _mark_stale(
    results: list[dict[str, object]], stale_ids: list[int]
) -> list[dict[str, object]]:
    """Set stale=True on results for the given unit IDs."""
    stale_set = set(stale_ids)
    return [
        {**ur, "stale": ur["unit_id"] in stale_set}
        for ur in results
    ]


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
