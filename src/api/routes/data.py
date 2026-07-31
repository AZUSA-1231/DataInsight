from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request, UploadFile

from src.agent.input_guard import validate_upload_path
from src.agent.nodes.data_track import data_track_node
from src.api.schemas import DataUploadResponse
from src.api.session import SessionStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}/data", tags=["data"])

UPLOAD_DIR = Path("data/uploads")
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


def _get_store(request: Request) -> SessionStore:
    return cast(SessionStore, request.app.state.sessions)


@router.post("/upload", response_model=DataUploadResponse)
async def upload_file(
    session_id: str, request: Request, file: UploadFile | None = None
) -> DataUploadResponse:
    if file is None:
        raise HTTPException(422, "No file provided")
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")

    if not file.filename:
        raise HTTPException(422, "Filename is required")

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large. Max: {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

    upload_dir = UPLOAD_DIR / session_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    try:
        file_path = validate_upload_path(upload_dir, file.filename)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large. Max: {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

    file_path.write_bytes(content)

    store.update(
        session_id,
        {"file_path": str(file_path), "user_requirement": state.user_requirement},
    )
    updated = store.get(session_id)
    assert updated is not None

    result = data_track_node(updated)
    store.update(session_id, result)

    final = store.get(session_id)
    assert final is not None
    profile = final.data_profile
    row_count = profile.shape[0] if profile and profile.shape else 0
    col_count = profile.shape[1] if profile and profile.shape else 0

    return DataUploadResponse(
        file_name=file.filename,
        row_count=row_count,
        col_count=col_count,
        unified_columns=final.unified_columns,
    )


@router.get("/profile")
async def get_profile(session_id: str, request: Request) -> dict[str, Any]:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")
    if state.data_profile is None:
        raise HTTPException(404, "No data uploaded yet")
    return state.data_profile.model_dump()


@router.get("/columns")
async def get_columns(session_id: str, request: Request) -> dict[str, object]:
    store = _get_store(request)
    state = store.get(session_id)
    if state is None:
        raise HTTPException(404, "Session not found")
    return {"unified_columns": state.unified_columns}
