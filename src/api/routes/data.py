from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request, UploadFile

from src.agent.ingestion import SourceIngestionError, ingest_source
from src.agent.input_guard import allocate_upload_path
from src.agent.state import AgentState, ColumnGraph, ColumnProfile
from src.api.schemas import (
    ColumnInfoResponse,
    ColumnsResponse,
    DataUploadResponse,
    LineageColumnResponse,
    LineageResponse,
    SnapshotResponse,
    SnapshotsResponse,
    SourceProfileResponse,
    SourceResponse,
    SourcesResponse,
)
from src.api.session import IncompatibleSessionError, SessionStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}/data", tags=["data"])

UPLOAD_DIR = Path("data/uploads")
OUTPUT_DIR = Path("data/output")
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


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


def _visible_columns(state: AgentState) -> list[ColumnInfoResponse]:
    """Build visible qualified columns from the persisted registry."""
    columns: list[ColumnInfoResponse] = []
    for snapshot in state.snapshot_registry.values():
        checkpoint = state.checkpoint_registry.get(snapshot.current_checkpoint_id)
        if checkpoint is None:
            continue
        profile_by_name: dict[str, ColumnProfile] = {}
        source = next(
            (source for source in state.data_sources if source.snapshot_id == snapshot.snapshot_id),
            None,
        )
        if source is not None:
            profile_by_name = {column.name: column for column in source.profile.columns}

        for ref, node_id in checkpoint.columns.items():
            node = state.column_graph.nodes.get(node_id)
            if node is None:
                continue
            profile = profile_by_name.get(node.name)
            columns.append(
                ColumnInfoResponse(
                    name=node.name,
                    dtype=node.dtype,
                    null_count=profile.null_count if profile else 0,
                    null_pct=profile.null_pct if profile else 0.0,
                    ref=ref,
                    snapshot=node.snapshot,
                    source_column=node.source_column,
                )
            )
    return columns


def _source_for_snapshot(state: AgentState, snapshot_id: str) -> Any | None:
    return next(
        (source for source in state.data_sources if source.snapshot_id == snapshot_id),
        None,
    )


def _profile_response(source: Any, state: AgentState) -> SourceProfileResponse:
    """Build a public profile envelope without exposing registry node IDs."""
    profile = source.profile
    columns = []
    for column in profile.columns:
        columns.append(
            ColumnInfoResponse(
                name=column.name,
                dtype=column.dtype,
                null_count=column.null_count,
                null_pct=column.null_pct,
                ref=f"{state.snapshot_registry[source.snapshot_id].name}.{column.name}"
                if source.snapshot_id in state.snapshot_registry
                else None,
                snapshot=(
                    state.snapshot_registry[source.snapshot_id].name
                    if source.snapshot_id in state.snapshot_registry
                    else None
                ),
                source_column=column.name,
            )
        )
    from src.api.schemas import DataProfileResponse

    return SourceProfileResponse(
        source_id=source.source_id,
        snapshot_id=source.snapshot_id,
        snapshot_name=state.snapshot_registry[source.snapshot_id].name,
        display_name=source.display_name,
        profile=DataProfileResponse(
            file_path=profile.file_path,
            shape=profile.shape,
            columns=columns,
            encoding=profile.encoding,
            statistics=profile.statistics,
            head_sample=profile.head_sample,
        ),
    )


def _public_lineage(state: AgentState) -> list[LineageColumnResponse]:
    """Project current-head lineage while keeping internal node IDs private."""
    result: list[LineageColumnResponse] = []
    for snapshot in state.snapshot_registry.values():
        checkpoint = state.checkpoint_registry.get(snapshot.current_checkpoint_id)
        if checkpoint is None:
            continue
        for ref, node_id in checkpoint.columns.items():
            node = state.column_graph.nodes.get(node_id)
            if node is None:
                continue
            parents = [
                state.column_graph.nodes[parent_id].ref
                for parent_id in node.derived_from_node_ids
                if parent_id in state.column_graph.nodes
            ]
            result.append(
                LineageColumnResponse(
                    ref=ref,
                    snapshot=snapshot.name,
                    name=node.name,
                    dtype=node.dtype,
                    source_column=node.source_column,
                    origin_refs=list(node.origin_columns),
                    derived_from=parents,
                    created_by_unit_id=node.created_by_unit_id,
                )
            )
    return result


@router.post("/upload", response_model=DataUploadResponse)
async def upload_file(
    session_id: str, request: Request, file: UploadFile | None = None
) -> DataUploadResponse:
    if file is None:
        raise HTTPException(422, "No file provided")
    store = _get_store(request)
    state = _get_state(store, session_id)

    if not file.filename:
        raise HTTPException(422, "Filename is required")

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large. Max: {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

    upload_dir = UPLOAD_DIR / session_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    try:
        file_path = allocate_upload_path(upload_dir, file.filename)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large. Max: {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

    file_path.write_bytes(content)

    source_id = f"src_{uuid.uuid4().hex[:16]}"
    output_root = OUTPUT_DIR / session_id
    existing_names = [snapshot.name for snapshot in state.snapshot_registry.values()]
    try:
        source, snapshot, checkpoint, nodes = ingest_source(
            source_path=file_path,
            display_name=file.filename,
            source_id=source_id,
            output_root=output_root,
            existing_snapshot_names=existing_names,
        )
    except SourceIngestionError as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc

    data_sources = [*state.data_sources, source]
    snapshot_registry = {
        **state.snapshot_registry,
        snapshot.snapshot_id: snapshot,
    }
    checkpoint_registry = {
        **state.checkpoint_registry,
        checkpoint.checkpoint_id: checkpoint,
    }
    graph_nodes = {**state.column_graph.nodes, **nodes}
    qualified_columns = [
        ref
        for snapshot_record in snapshot_registry.values()
        if (head := checkpoint_registry.get(snapshot_record.current_checkpoint_id))
        for ref in head.columns
    ]

    # These fields keep the existing graph and CLI bootable during M1. They are
    # compatibility projections; the registries above are the durable source.
    store.update(
        session_id,
        {
            "data_sources": data_sources,
            "snapshot_registry": snapshot_registry,
            "checkpoint_registry": checkpoint_registry,
            "column_graph": ColumnGraph(nodes=graph_nodes),
            "file_path": str(file_path),
            "data_profile": source.profile,
            "unified_columns": qualified_columns,
        },
    )

    return DataUploadResponse(
        file_name=file.filename,
        row_count=checkpoint.row_count,
        col_count=len(source.profile.columns),
        unified_columns=qualified_columns,
        source_id=source.source_id,
        snapshot_id=source.snapshot_id,
        snapshot_name=snapshot.name,
        checkpoint_id=checkpoint.checkpoint_id,
        columns=_visible_columns(store.get(session_id) or state),
    )


@router.get("/profile")
async def get_profile(
    session_id: str,
    request: Request,
    source_id: str | None = None,
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    store = _get_store(request)
    state = _get_state(store, session_id)
    if state.data_sources:
        selected = list(state.data_sources)
        if source_id is not None:
            selected = [source for source in selected if source.source_id == source_id]
        if snapshot_id is not None:
            selected = [
                source for source in selected if source.snapshot_id == snapshot_id
            ]
        if (source_id is not None or snapshot_id is not None) and not selected:
            raise HTTPException(404, "Source profile not found")

        profiles = [_profile_response(source, state) for source in selected]
        if len(profiles) == 1 and (source_id is not None or snapshot_id is not None):
            envelope = profiles[0].model_dump()
            # Keep the profile fields at the top level for direct inspection while
            # also returning a stable envelope for clients that need metadata.
            flattened = dict(envelope["profile"])
            flattened.update(
                {
                    "source_id": envelope["source_id"],
                    "snapshot_id": envelope["snapshot_id"],
                    "snapshot_name": envelope["snapshot_name"],
                    "display_name": envelope["display_name"],
                    "profile": envelope["profile"],
                }
            )
            return flattened
        if len(profiles) == 1:
            envelope = profiles[0].model_dump()
            flattened = dict(envelope["profile"])
            flattened.update(
                {
                    "source_id": envelope["source_id"],
                    "snapshot_id": envelope["snapshot_id"],
                    "snapshot_name": envelope["snapshot_name"],
                    "display_name": envelope["display_name"],
                    "profile": envelope["profile"],
                    "profiles": [envelope],
                }
            )
            return flattened
        return {"profiles": [profile.model_dump() for profile in profiles]}

    if state.data_profile is None:
        raise HTTPException(404, "No data uploaded yet")
    return state.data_profile.model_dump()


@router.get("/columns", response_model=ColumnsResponse)
async def get_columns(session_id: str, request: Request) -> ColumnsResponse:
    store = _get_store(request)
    state = _get_state(store, session_id)
    columns = _visible_columns(state)
    if not columns and state.unified_columns:
        return ColumnsResponse(columns=[], unified_columns=state.unified_columns)
    return ColumnsResponse(
        columns=columns,
        unified_columns=[column.ref for column in columns if column.ref is not None],
    )


@router.get("/sources", response_model=SourcesResponse)
async def get_sources(session_id: str, request: Request) -> SourcesResponse:
    store = _get_store(request)
    state = _get_state(store, session_id)
    responses: list[SourceResponse] = []
    for source in state.data_sources:
        snapshot = state.snapshot_registry.get(source.snapshot_id)
        if snapshot is None:
            continue
        responses.append(
            SourceResponse(
                source_id=source.source_id,
                display_name=source.display_name,
                snapshot_id=source.snapshot_id,
                snapshot_name=snapshot.name,
                row_count=source.profile.shape[0],
                col_count=source.profile.shape[1],
                checkpoint_id=source.source_checkpoint_id,
            )
        )
    return SourcesResponse(sources=responses)


@router.get("/snapshots", response_model=SnapshotsResponse)
async def get_snapshots(session_id: str, request: Request) -> SnapshotsResponse:
    store = _get_store(request)
    state = _get_state(store, session_id)
    responses: list[SnapshotResponse] = []
    for snapshot in state.snapshot_registry.values():
        checkpoint = state.checkpoint_registry.get(snapshot.current_checkpoint_id)
        if checkpoint is None:
            continue
        responses.append(
            SnapshotResponse(
                snapshot_id=snapshot.snapshot_id,
                name=snapshot.name,
                display_name=snapshot.display_name,
                current_checkpoint_id=snapshot.current_checkpoint_id,
                row_count=checkpoint.row_count,
                column_refs=list(checkpoint.columns),
                source_id=(
                    source.source_id
                    if (source := _source_for_snapshot(state, snapshot.snapshot_id))
                    is not None
                    else None
                ),
                created_by_unit_id=snapshot.created_by_unit_id,
                parent_snapshot_ids=list(snapshot.parent_snapshot_ids),
            )
        )
    return SnapshotsResponse(snapshots=responses)


@router.get("/lineage", response_model=LineageResponse)
async def get_lineage(session_id: str, request: Request) -> LineageResponse:
    store = _get_store(request)
    state = _get_state(store, session_id)
    return LineageResponse(columns=_public_lineage(state))
