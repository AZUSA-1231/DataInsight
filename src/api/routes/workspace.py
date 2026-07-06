from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.agent.nodes.planner import planner_node
from src.agent.state import AgentState, Plan, PlanUnit
from src.api.schemas import UnitCreateRequest, UnitUpdateRequest, WorkspacePlanResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}", tags=["workspace"])


def _get_store(request: Request) -> Any:
    return request.app.state.sessions


def _reindex_units(units: list[PlanUnit]) -> list[PlanUnit]:
    """Re-index units starting from 1, preserving order."""
    reindexed: list[PlanUnit] = []
    for i, u in enumerate(units, start=1):
        reindexed.append(
            PlanUnit(
                unit_id=i,
                purpose=u.purpose,
                model=u.model,
                cautious=u.cautious,
                depends_on=u.depends_on,
                related_fields=u.related_fields,
            )
        )
    return reindexed


def _ensure_plan(state: AgentState) -> Plan:
    """Return existing plan or create a default one with cleaning unit."""
    if state.plan is not None:
        return state.plan
    return Plan(
        cleaning=PlanUnit(
            unit_id=0,
            purpose="处理缺失值和异常值",
            cautious="",
            related_fields=[],
        ),
        units=[],
        alignment_notes="",
    )


@router.get("/workspace", response_model=WorkspacePlanResponse)
async def get_workspace(
    session_id: str, request: Request
) -> WorkspacePlanResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")
    return WorkspacePlanResponse(plan=state.plan)


@router.put("/workspace", response_model=WorkspacePlanResponse)
async def set_workspace(
    session_id: str, plan: Plan, request: Request
) -> WorkspacePlanResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")
    store.update(session_id, {"plan": plan})
    return WorkspacePlanResponse(plan=plan)


@router.delete("/workspace")
async def clear_workspace(
    session_id: str, request: Request
) -> dict[str, str]:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")
    store.update(session_id, {"plan": None})
    return {"message": "Workspace cleared"}


@router.post("/workspace/units", response_model=WorkspacePlanResponse)
async def add_unit(
    session_id: str, body: UnitCreateRequest, request: Request
) -> WorkspacePlanResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    plan = _ensure_plan(state)
    new_unit = PlanUnit(
        unit_id=len(plan.units) + 1,
        purpose=body.purpose,
        model=body.model,
        cautious=body.cautious,
        related_fields=body.related_fields,
    )
    plan.units.append(new_unit)
    store.update(session_id, {"plan": plan})
    return WorkspacePlanResponse(plan=plan)


@router.put("/workspace/units/{unit_id}", response_model=WorkspacePlanResponse)
async def update_unit(
    session_id: str, unit_id: int, body: UnitUpdateRequest, request: Request
) -> WorkspacePlanResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")
    if state.plan is None:
        raise HTTPException(400, "No workspace plan to update")

    target = next((u for u in state.plan.units if u.unit_id == unit_id), None)
    if target is None:
        raise HTTPException(404, f"Unit {unit_id} not found")

    update_data: dict[str, object] = {}
    if body.purpose is not None:
        update_data["purpose"] = body.purpose
    if body.model is not None:
        update_data["model"] = body.model
    if body.cautious is not None:
        update_data["cautious"] = body.cautious
    if body.related_fields is not None:
        update_data["related_fields"] = body.related_fields

    updated_unit = target.model_copy(update=update_data)
    units_list = [updated_unit if u.unit_id == unit_id else u for u in state.plan.units]
    new_plan = state.plan.model_copy(update={"units": units_list})
    store.update(session_id, {"plan": new_plan})
    return WorkspacePlanResponse(plan=new_plan)


@router.delete("/workspace/units/{unit_id}", response_model=WorkspacePlanResponse)
async def delete_unit(
    session_id: str, unit_id: int, request: Request
) -> WorkspacePlanResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")
    if state.plan is None:
        raise HTTPException(400, "No workspace plan to delete from")

    remaining = [u for u in state.plan.units if u.unit_id != unit_id]
    reindexed = _reindex_units(remaining)
    new_plan = state.plan.model_copy(update={"units": reindexed})
    store.update(session_id, {"plan": new_plan})
    return WorkspacePlanResponse(plan=new_plan)


@router.post("/plan/generate", response_model=WorkspacePlanResponse)
async def generate_plan(
    session_id: str, request: Request
) -> WorkspacePlanResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    result = planner_node(state)
    if "error" in result:
        raise HTTPException(400, result["error"])
    store.update(session_id, result)
    final = store.get(session_id)
    assert final is not None
    return WorkspacePlanResponse(plan=final.plan)
