from __future__ import annotations

import math
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from src.agent.state import AgentState, WorkspaceLayout
from src.api.schemas import WorkspaceLayoutResponse
from src.api.session import IncompatibleSessionError, SessionStore

router = APIRouter(
    prefix="/api/sessions/{session_id}/workspace/layout",
    tags=["workspace-layout"],
)

_MAX_LAYOUT_COORDINATE = 1_000_000.0


def _get_store(request: Request) -> SessionStore:
    return cast(SessionStore, request.app.state.sessions)


def _get_state(store: SessionStore, session_id: str) -> AgentState:
    try:
        state = store.get(session_id)
    except IncompatibleSessionError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "INCOMPATIBLE_SESSION_SCHEMA", "message": str(exc)},
        ) from exc
    if state is None:
        raise HTTPException(404, "Session not found")
    return state


def _layout_shape_issues(error: ValidationError) -> list[dict[str, object]]:
    return [
        {
            "field": ".".join(str(part) for part in issue.get("loc", ())) or None,
            "message": str(issue.get("msg", "Invalid workspace layout")),
        }
        for issue in error.errors()
    ]


def _parse_layout_or_raise(body: dict[str, Any]) -> WorkspaceLayout:
    try:
        layout = WorkspaceLayout.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_WORKSPACE_LAYOUT",
                "message": "Workspace layout shape is invalid",
                "issues": _layout_shape_issues(exc),
            },
        ) from exc

    coordinate_values = [
        ("viewport.x", layout.viewport.x),
        ("viewport.y", layout.viewport.y),
        ("viewport.zoom", layout.viewport.zoom),
    ]
    coordinate_values.extend(
        (f"nodes[{index}].{field}", value)
        for index, node in enumerate(layout.nodes)
        for field, value in (("x", node.x), ("y", node.y))
    )
    out_of_range = [
        field
        for field, value in coordinate_values
        if not math.isfinite(value)
        or abs(value) > _MAX_LAYOUT_COORDINATE
    ]
    if out_of_range:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "LAYOUT_COORDINATE_OUT_OF_RANGE",
                "message": "Workspace layout coordinates must be finite and bounded",
                "fields": out_of_range,
            },
        )
    return layout


def _validate_layout_units(layout: WorkspaceLayout, state: AgentState) -> None:
    seen: set[int] = set()
    duplicate_ids: list[int] = []
    for node in layout.nodes:
        if node.unit_id in seen and node.unit_id not in duplicate_ids:
            duplicate_ids.append(node.unit_id)
        seen.add(node.unit_id)
    if duplicate_ids:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "DUPLICATE_LAYOUT_UNIT",
                "message": "Workspace layout contains duplicate Unit IDs",
                "unit_ids": duplicate_ids,
            },
        )

    plan_unit_ids = {unit.unit_id for unit in state.plan.units} if state.plan else set()
    unknown_ids = sorted(seen - plan_unit_ids)
    if unknown_ids:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "UNKNOWN_LAYOUT_UNIT",
                "message": "Workspace layout references a Unit outside the current Plan",
                "unit_ids": unknown_ids,
            },
        )


@router.get("", response_model=WorkspaceLayoutResponse)
async def get_workspace_layout(
    session_id: str, request: Request
) -> WorkspaceLayoutResponse:
    state = _get_state(_get_store(request), session_id)
    return WorkspaceLayoutResponse(**state.workspace_layout.model_dump())


@router.put("", response_model=WorkspaceLayoutResponse)
async def set_workspace_layout(
    session_id: str, body: dict[str, Any], request: Request
) -> WorkspaceLayoutResponse:
    store = _get_store(request)
    state = _get_state(store, session_id)
    layout = _parse_layout_or_raise(body)
    _validate_layout_units(layout, state)
    updated = store.update(session_id, {"workspace_layout": layout})
    return WorkspaceLayoutResponse(**updated.workspace_layout.model_dump())
