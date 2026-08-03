from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from src.agent.nodes.planner import planner_node
from src.agent.plan_validation import PlanValidationError, validate_plan
from src.agent.state import AgentState, Plan, PlannerInstruction, PlanUnit
from src.api.schemas import (
    GeneratePlanRequest,
    UnitCreateRequest,
    UnitUpdateRequest,
    WorkspacePlanResponse,
)
from src.api.session import IncompatibleSessionError, SessionStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}", tags=["workspace"])


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


def _validate_or_raise(plan: Plan, state: AgentState) -> None:
    try:
        validate_plan(plan, state)
    except PlanValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.as_detail()) from exc


def _parse_plan_or_raise(body: dict[str, Any]) -> Plan:
    """Turn public JSON into a Plan and keep shape errors frontend-readable."""
    try:
        return Plan.model_validate(body)
    except ValidationError as exc:
        issues = [
            {
                "code": "PLAN_SHAPE_INVALID",
                "unit_id": None,
                "field": ".".join(str(part) for part in error.get("loc", ())) or None,
                "message": str(error.get("msg", "Invalid Plan")),
            }
            for error in exc.errors()
        ]
        detail = {
            "code": "INVALID_PLAN",
            "message": "Plan shape is invalid",
            "issues": issues,
        }
        raise HTTPException(status_code=422, detail=detail) from exc


def _stale_patch(
    state: AgentState,
    changed_unit_id: int,
    units: list[Any],
) -> dict[str, object]:
    """Mark an edited unit and all downstream results stale immutably."""
    from src.agent.dag import transitive_dependents

    stale_ids = {changed_unit_id, *transitive_dependents(changed_unit_id, units)}
    analysis_result = state.analysis_result
    if not isinstance(analysis_result, dict):
        return {}
    unit_results = analysis_result.get("unit_results")
    if not isinstance(unit_results, list):
        return {}
    updated_results = [
        {
            **result,
            # Staleness is monotonic until a successful execution or rerun
            # explicitly clears it. Editing one branch must not revive an
            # unrelated result that was already stale.
            "stale": bool(result.get("stale"))
            or result.get("unit_id") in stale_ids,
        }
        for result in unit_results
        if isinstance(result, dict)
    ]
    return {"analysis_result": {**analysis_result, "unit_results": updated_results}}


def _all_results_stale_patch(state: AgentState) -> dict[str, object]:
    """Invalidate retained results after replacing the complete Plan."""
    analysis_result = state.analysis_result
    if not isinstance(analysis_result, dict):
        return {}
    unit_results = analysis_result.get("unit_results")
    if not isinstance(unit_results, list):
        return {}
    updated_results = [
        {**result, "stale": True}
        for result in unit_results
        if isinstance(result, dict)
    ]
    return {"analysis_result": {**analysis_result, "unit_results": updated_results}}


def _request_unit_payload(body: UnitCreateRequest, unit_id: int) -> dict[str, object]:
    payload: dict[str, object] = {
        "unit_id": unit_id,
        "purpose": body.purpose,
        "cautious": body.cautious,
        "depends_on": body.depends_on,
    }
    if body.operation is None:
        payload.update(
            {
                "operation": "legacy",
                "model": body.model,
                "related_fields": body.related_fields,
            }
        )
        return payload

    payload["operation"] = body.operation
    if body.model is not None:
        payload["model"] = body.model
    if body.execution_mode is not None:
        payload["execution_mode"] = body.execution_mode
    for field in (
        "input_snapshot",
        "input_columns",
        "output_columns",
        "output_snapshot",
        "inputs",
        "keys",
        "select",
        "how",
        "template_name",
        "template_params",
        "params",
    ):
        value = getattr(body, field)
        if value is not None:
            payload[field] = value
    return payload


def _updated_unit_payload(target: Any, body: UnitUpdateRequest) -> dict[str, object]:
    updates = body.model_dump(exclude_none=True)
    if "model" in updates:
        updates["model_hint"] = updates.pop("model")
    if "related_fields" in updates:
        if getattr(target, "operation", "legacy") == "legacy":
            updates["related_fields"] = updates.pop("related_fields")
        else:
            updates["input_columns"] = updates.pop("related_fields")

    target_operation = getattr(target, "operation", "legacy")
    requested_operation = updates.get("operation")
    if requested_operation is not None and requested_operation != target_operation:
        # Operation switches must not carry fields from the previous tagged
        # model into the new extra=forbid model. The frontend sends the full
        # replacement operation payload in the same request.
        payload: dict[str, object] = {
            "unit_id": target.unit_id,
            "operation": requested_operation,
            "purpose": target.purpose,
            "model_hint": target.model_hint,
            "cautious": target.cautious,
            "depends_on": target.depends_on,
        }
        payload.update(updates)
        return payload

    payload = dict(target.model_dump(mode="python"))
    payload.update(updates)
    return payload


def _ensure_plan(state: AgentState) -> Plan:
    """Return existing plan or create an empty default one."""
    if state.plan is not None:
        return state.plan
    return Plan(
        units=[],
        alignment_notes="",
    )


@router.get("/workspace", response_model=WorkspacePlanResponse)
async def get_workspace(
    session_id: str, request: Request
) -> WorkspacePlanResponse:
    store = _get_store(request)
    state = _get_state(store, session_id)
    return WorkspacePlanResponse(plan=state.plan)


@router.put("/workspace", response_model=WorkspacePlanResponse)
async def set_workspace(
    session_id: str, body: dict[str, Any], request: Request
) -> WorkspacePlanResponse:
    store = _get_store(request)
    state = _get_state(store, session_id)
    plan = _parse_plan_or_raise(body)
    _validate_or_raise(plan, state)
    stale_patch = _all_results_stale_patch(state) if state.plan != plan else {}
    store.update(session_id, {"plan": plan, **stale_patch})
    return WorkspacePlanResponse(plan=plan)


@router.delete("/workspace")
async def clear_workspace(
    session_id: str, request: Request
) -> dict[str, str]:
    store = _get_store(request)
    state = _get_state(store, session_id)
    stale_patch = _all_results_stale_patch(state)
    store.update(session_id, {"plan": None, **stale_patch})
    return {"message": "Workspace cleared"}


@router.post("/workspace/units", response_model=WorkspacePlanResponse)
async def add_unit(
    session_id: str, body: UnitCreateRequest, request: Request
) -> WorkspacePlanResponse:
    store = _get_store(request)
    state = _get_state(store, session_id)

    plan = _ensure_plan(state)
    new_id = max((unit.unit_id for unit in plan.units), default=0) + 1
    try:
        new_unit = Plan.model_validate(
            {
                "units": [_request_unit_payload(body, new_id)],
                "alignment_notes": plan.alignment_notes,
            }
        ).units[0]
        new_plan = plan.model_copy(update={"units": [*plan.units, new_unit]})
        _validate_or_raise(new_plan, state)
    except PlanValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.as_detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    stale_patch = _all_results_stale_patch(state)
    store.update(session_id, {"plan": new_plan, **stale_patch})
    return WorkspacePlanResponse(plan=new_plan)


@router.put("/workspace/units/{unit_id}", response_model=WorkspacePlanResponse)
async def update_unit(
    session_id: str, unit_id: int, body: UnitUpdateRequest, request: Request
) -> WorkspacePlanResponse:
    store = _get_store(request)
    state = _get_state(store, session_id)
    if state.plan is None:
        raise HTTPException(400, "No workspace plan to update")

    target = next((u for u in state.plan.units if u.unit_id == unit_id), None)
    if target is None:
        raise HTTPException(404, f"Unit {unit_id} not found")

    try:
        updated_unit = Plan.model_validate(
            {
                "units": [_updated_unit_payload(target, body)],
                "alignment_notes": state.plan.alignment_notes,
            }
        ).units[0]
        units_list = [
            updated_unit if unit.unit_id == unit_id else unit
            for unit in state.plan.units
        ]
        new_plan = state.plan.model_copy(update={"units": units_list})
        _validate_or_raise(new_plan, state)
    except PlanValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.as_detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    stale_patch = _stale_patch(state, unit_id, units_list)
    store.update(session_id, {"plan": new_plan, **stale_patch})
    return WorkspacePlanResponse(plan=new_plan)


@router.delete("/workspace/units/{unit_id}", response_model=WorkspacePlanResponse)
async def delete_unit(
    session_id: str, unit_id: int, request: Request, cascade: bool = False
) -> WorkspacePlanResponse:
    store = _get_store(request)
    state = _get_state(store, session_id)
    if state.plan is None:
        raise HTTPException(400, "No workspace plan to delete from")

    target = next((unit for unit in state.plan.units if unit.unit_id == unit_id), None)
    if target is None:
        raise HTTPException(404, f"Unit {unit_id} not found")

    from src.agent.dag import transitive_dependents

    dependent_ids = transitive_dependents(unit_id, state.plan.units)
    if dependent_ids and not cascade:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DOWNSTREAM_DEPENDENTS",
                "message": f"Unit {unit_id} has downstream dependents",
                "dependent_unit_ids": dependent_ids,
            },
        )

    remove_ids = {unit_id, *(dependent_ids if cascade else [])}
    remaining = [unit for unit in state.plan.units if unit.unit_id not in remove_ids]
    # Legacy fixtures keep their historical display behavior. V2 IDs are
    # immutable and are deliberately never renumbered after deletion.
    all_legacy = all(isinstance(unit, PlanUnit) for unit in state.plan.units)
    if all_legacy and not dependent_ids:
        legacy_remaining: list[Any] = []
        for index, unit in enumerate(remaining, start=1):
            legacy_remaining.append(unit.model_copy(update={"unit_id": index}))
        remaining = legacy_remaining
    new_plan = state.plan.model_copy(update={"units": remaining})
    _validate_or_raise(new_plan, state)
    stale_patch = _stale_patch(state, unit_id, state.plan.units)
    store.update(session_id, {"plan": new_plan, **stale_patch})
    return WorkspacePlanResponse(plan=new_plan)


@router.post("/plan/generate", response_model=WorkspacePlanResponse)
async def generate_plan(
    session_id: str, request: Request, body: GeneratePlanRequest | None = None
) -> WorkspacePlanResponse:
    store = _get_store(request)
    state = _get_state(store, session_id)

    # If frontend sent a pending instruction, use it
    if body and body.instruction:
        try:
            instruction = PlannerInstruction(**body.instruction)  # type: ignore[arg-type]
            store.update(session_id, {"planner_instruction": instruction})
            state = _get_state(store, session_id)
        except Exception as e:
            raise HTTPException(400, f"Invalid instruction: {e}") from e

    if state.planner_instruction is None and state.analysis_intent is None:
        raise HTTPException(
            400,
            "No instruction from Business Track yet. "
            "Send a message via POST /dialogue first to let the BT Agent "
            "understand your goal, then generate the plan.",
        )

    result = planner_node(state)
    if "error" in result:
        detail: object = result["error"]
        if "_plan_validation_issues" in result:
            detail = {
                "code": "INVALID_PLAN",
                "message": str(result["error"]),
                "issues": result["_plan_validation_issues"],
            }
        raise HTTPException(400, detail)
    generated_plan = result.get("plan")
    if not isinstance(generated_plan, Plan):
        raise HTTPException(400, "Planner did not return a valid Plan")
    _validate_or_raise(generated_plan, state)
    stale_patch = _all_results_stale_patch(state)
    store.update(session_id, {**result, **stale_patch})
    final = store.get(session_id)
    assert final is not None
    return WorkspacePlanResponse(plan=final.plan)
