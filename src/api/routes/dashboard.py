from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, HTTPException, Request

from src.api.schemas import DashboardResponse, PinChartRequest, PinChartResponse
from src.api.session import SessionStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}/dashboard", tags=["dashboard"])


def _get_store(request: Request) -> SessionStore:
    return cast(SessionStore, request.app.state.sessions)


@router.get("", response_model=DashboardResponse)
async def get_dashboard(session_id: str, request: Request) -> DashboardResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    pins = [
        PinChartResponse(
            pin_id=str(p["pin_id"]),
            unit_id=int(str(p["unit_id"])),
            chart_path=str(p["chart_path"]),
            label=str(p["label"]),
            pinned_at=str(p["pinned_at"]),
        )
        for p in state.dashboard_pins
    ]
    return DashboardResponse(pins=pins)


@router.post("/pins", response_model=PinChartResponse)
async def pin_chart(
    session_id: str, body: PinChartRequest, request: Request
) -> PinChartResponse:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    pin: dict[str, object] = {
        "pin_id": uuid.uuid4().hex[:12],
        "unit_id": body.unit_id,
        "chart_path": body.chart_path,
        "label": body.label,
        "pinned_at": datetime.now(UTC).isoformat(),
    }
    updated_pins = list(state.dashboard_pins) + [pin]
    store.update(session_id, {"dashboard_pins": updated_pins})

    return PinChartResponse(
        pin_id=str(pin["pin_id"]),
        unit_id=body.unit_id,
        chart_path=body.chart_path,
        label=body.label,
        pinned_at=str(pin["pinned_at"]),
    )


@router.delete("/pins/{pin_id}")
async def unpin_chart(
    session_id: str, pin_id: str, request: Request
) -> dict[str, str]:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    filtered = [p for p in state.dashboard_pins if p["pin_id"] != pin_id]
    if len(filtered) == len(state.dashboard_pins):
        raise HTTPException(404, f"Pin {pin_id} not found")
    store.update(session_id, {"dashboard_pins": filtered})
    return {"message": f"Pin {pin_id} removed"}
