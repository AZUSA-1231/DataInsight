from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request, UploadFile

from src.agent.ingestion import SourceIngestionError, ingest_source
from src.agent.input_guard import allocate_upload_path
from src.agent.plan_validation import (
    PlanColumnView,
    PlanSnapshotView,
    project_plan_snapshot_views,
)
from src.agent.state import (
    AgentState,
    ColumnGraph,
    ColumnProfile,
    FilterUnit,
    JoinUnit,
    Plan,
    PlanUnit,
)
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
    WorkspaceColumnViewResponse,
    WorkspaceDataProjectionResponse,
    WorkspaceSnapshotViewResponse,
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


def _source_responses(state: AgentState) -> list[SourceResponse]:
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
    return responses


def _snapshot_name_by_id(state: AgentState) -> dict[str, str]:
    return {
        snapshot.snapshot_id: snapshot.name
        for snapshot in state.snapshot_registry.values()
    }


def _successful_unit_ids(state: AgentState) -> set[int]:
    analysis_result = state.analysis_result
    if not isinstance(analysis_result, dict):
        return set()
    raw_results = analysis_result.get("unit_results", [])
    if not isinstance(raw_results, list):
        return set()
    return {
        int(result["unit_id"])
        for result in raw_results
        if isinstance(result, dict)
        and isinstance(result.get("unit_id"), int)
        and result.get("status") == "success"
        and not bool(result.get("stale", False))
    }


def _materialized_snapshot_rows(
    state: AgentState,
) -> list[WorkspaceSnapshotViewResponse]:
    names_by_id = _snapshot_name_by_id(state)
    rows: list[WorkspaceSnapshotViewResponse] = []
    for snapshot in state.snapshot_registry.values():
        checkpoint = state.checkpoint_registry.get(snapshot.current_checkpoint_id)
        if checkpoint is None:
            continue
        source = _source_for_snapshot(state, snapshot.snapshot_id)
        rows.append(
            WorkspaceSnapshotViewResponse(
                view_id=snapshot.snapshot_id,
                snapshot_id=snapshot.snapshot_id,
                name=snapshot.name,
                display_name=snapshot.display_name,
                row_count=checkpoint.row_count,
                column_refs=list(checkpoint.columns),
                source_id=source.source_id if source is not None else None,
                created_by_unit_id=snapshot.created_by_unit_id,
                parent_snapshot_names=[
                    names_by_id[parent_id]
                    for parent_id in snapshot.parent_snapshot_ids
                    if parent_id in names_by_id
                ],
                availability="materialized",
                profile_available=source is not None,
            )
        )
    rows_by_name = {row.name: row for row in rows}
    source_names = [
        source_snapshot.name
        for source in state.data_sources
        if (source_snapshot := state.snapshot_registry.get(source.snapshot_id)) is not None
    ]
    source_name_set = set(source_names)
    ordered = [rows_by_name[name] for name in source_names if name in rows_by_name]
    ordered.extend(
        rows_by_name[name]
        for name in sorted(rows_by_name)
        if name not in source_name_set
    )
    return ordered


def _materialized_column_rows(
    state: AgentState,
) -> list[WorkspaceColumnViewResponse]:
    rows: list[WorkspaceColumnViewResponse] = []
    for snapshot in state.snapshot_registry.values():
        checkpoint = state.checkpoint_registry.get(snapshot.current_checkpoint_id)
        if checkpoint is None:
            continue
        source = _source_for_snapshot(state, snapshot.snapshot_id)
        profile_by_name = (
            {column.name: column for column in source.profile.columns}
            if source is not None
            else {}
        )
        for ref, node_id in checkpoint.columns.items():
            node = state.column_graph.nodes.get(node_id)
            if node is None:
                continue
            profile = profile_by_name.get(node.name)
            rows.append(
                WorkspaceColumnViewResponse(
                    ref=ref,
                    name=node.name,
                    snapshot=snapshot.name,
                    dtype=node.dtype,
                    null_count=profile.null_count if profile is not None else 0,
                    null_pct=profile.null_pct if profile is not None else 0.0,
                    source_column=node.source_column,
                    created_by_unit_id=node.created_by_unit_id,
                    availability="materialized",
                )
            )
    return rows


def _compatibility_warning(state: AgentState, column_count: int) -> str | None:
    if column_count == 0 and state.unified_columns:
        return (
            "This Project exposes a legacy column projection. Upload a new Source "
            "to enable typed column facts."
        )
    return None


def _plan_snapshot_producers(plan: Plan) -> dict[str, int]:
    producers: dict[str, int] = {}
    for unit in plan.units:
        if isinstance(unit, FilterUnit | JoinUnit):
            producers[unit.output_snapshot] = unit.unit_id
    return producers


def _plan_is_v2(plan: Plan) -> bool:
    return any(not isinstance(unit, PlanUnit) for unit in plan.units)


def _plan_snapshot_materialized(
    view: PlanSnapshotView,
    snapshot: Any | None,
    checkpoint: Any | None,
    output_producers: dict[str, int],
    successful_units: set[int],
) -> bool:
    if snapshot is None or checkpoint is None:
        return False
    producer = output_producers.get(view.name)
    if producer is None:
        return True
    return (
        snapshot.created_by_unit_id == producer
        and producer in successful_units
    )


def _plan_column_materialized(
    column: PlanColumnView,
    snapshot_materialized: bool,
    checkpoint: Any | None,
    state: AgentState,
    successful_units: set[int],
) -> bool:
    if not snapshot_materialized:
        return False
    if column.planned_by_unit_id is None:
        return column.materialized_node_id is not None
    if column.planned_by_unit_id not in successful_units or checkpoint is None:
        return False
    node_id = checkpoint.columns.get(column.ref)
    node = state.column_graph.nodes.get(node_id) if node_id is not None else None
    return node is not None and node.created_by_unit_id == column.planned_by_unit_id


def _workspace_projection(
    state: AgentState,
) -> WorkspaceDataProjectionResponse:
    sources = _source_responses(state)
    plan = state.plan
    if plan is None or not _plan_is_v2(plan):
        return WorkspaceDataProjectionResponse(
            sources=sources,
            snapshots=_materialized_snapshot_rows(state),
            columns=_materialized_column_rows(state),
            lineage=_public_lineage(state),
            compatibility_warning=_compatibility_warning(
                state, len(_materialized_column_rows(state))
            ),
        )

    plan_views = project_plan_snapshot_views(plan, state)
    output_producers = _plan_snapshot_producers(plan)
    successful_units = _successful_unit_ids(state)
    snapshots_by_name = {
        snapshot.name: snapshot for snapshot in state.snapshot_registry.values()
    }
    source_snapshot_names = [
        snapshot.name
        for source in state.data_sources
        if (snapshot := state.snapshot_registry.get(source.snapshot_id)) is not None
    ]
    source_names = set(source_snapshot_names)
    materialized_rows: dict[str, WorkspaceSnapshotViewResponse] = {}
    planned_rows: dict[str, WorkspaceSnapshotViewResponse] = {}
    column_rows: dict[str, WorkspaceColumnViewResponse] = {}

    for name, view in plan_views.items():
        snapshot = snapshots_by_name.get(name)
        checkpoint = (
            state.checkpoint_registry.get(snapshot.current_checkpoint_id)
            if snapshot is not None
            else None
        )
        snapshot_materialized = _plan_snapshot_materialized(
            view,
            snapshot,
            checkpoint,
            output_producers,
            successful_units,
        )
        source = (
            _source_for_snapshot(state, snapshot.snapshot_id)
            if snapshot is not None and snapshot_materialized
            else None
        )
        parent_names = (
            [
                _snapshot_name_by_id(state)[parent_id]
                for parent_id in snapshot.parent_snapshot_ids
                if parent_id in _snapshot_name_by_id(state)
            ]
            if snapshot is not None and snapshot_materialized
            else list(view.parent_snapshot_names)
        )
        producer_id = (
            snapshot.created_by_unit_id
            if snapshot_materialized and snapshot is not None
            else view.producer_unit_id
        )
        row = WorkspaceSnapshotViewResponse(
            view_id=(
                snapshot.snapshot_id
                if snapshot_materialized and snapshot is not None
                else f"plan:unit_{view.producer_unit_id}"
            ),
            snapshot_id=(
                snapshot.snapshot_id
                if snapshot_materialized and snapshot is not None
                else None
            ),
            name=name,
            display_name=(snapshot.display_name if snapshot is not None else name),
            row_count=(
                checkpoint.row_count
                if snapshot_materialized and checkpoint is not None
                else None
            ),
            column_refs=[column.ref for column in view.columns],
            source_id=source.source_id if source is not None else None,
            created_by_unit_id=producer_id,
            parent_snapshot_names=parent_names,
            availability="materialized" if snapshot_materialized else "planned",
            profile_available=bool(snapshot_materialized and source is not None),
        )
        (materialized_rows if snapshot_materialized else planned_rows)[name] = row

        profile_by_name = (
            {column.name: column for column in source.profile.columns}
            if source is not None
            else {}
        )
        for column in view.columns:
            is_materialized = _plan_column_materialized(
                column,
                snapshot_materialized,
                checkpoint,
                state,
                successful_units,
            )
            node = None
            if is_materialized and checkpoint is not None:
                node_id = checkpoint.columns.get(column.ref)
                node = state.column_graph.nodes.get(node_id) if node_id is not None else None
            profile = profile_by_name.get(column.name) if is_materialized else None
            column_rows[column.ref] = WorkspaceColumnViewResponse(
                ref=column.ref,
                name=column.name,
                snapshot=column.snapshot,
                dtype=node.dtype if node is not None else column.dtype,
                null_count=profile.null_count if profile is not None else None,
                null_pct=profile.null_pct if profile is not None else None,
                source_column=(
                    node.source_column
                    if node is not None
                    else column.source_column
                ),
                created_by_unit_id=(
                    node.created_by_unit_id
                    if node is not None
                    else column.planned_by_unit_id
                ),
                availability="materialized" if is_materialized else "planned",
            )

    ordered_snapshots: list[WorkspaceSnapshotViewResponse] = []
    for name in source_snapshot_names:
        snapshot_row = materialized_rows.get(name) or planned_rows.get(name)
        if snapshot_row is not None:
            ordered_snapshots.append(snapshot_row)
    for name in sorted(materialized_rows):
        if name not in source_names:
            ordered_snapshots.append(materialized_rows[name])
    for name in plan_views:
        if name in planned_rows and name not in source_names:
            ordered_snapshots.append(planned_rows[name])

    ordered_columns = [
        column_rows[column.ref]
        for snapshot in ordered_snapshots
        for column in plan_views.get(snapshot.name, PlanSnapshotView(snapshot.name, ())).columns
        if column.ref in column_rows
    ]
    return WorkspaceDataProjectionResponse(
        sources=sources,
        snapshots=ordered_snapshots,
        columns=ordered_columns,
        lineage=_public_lineage(state),
        compatibility_warning=_compatibility_warning(state, len(ordered_columns)),
    )


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


@router.get(
    "/workspace-projection",
    response_model=WorkspaceDataProjectionResponse,
)
async def get_workspace_projection(
    session_id: str, request: Request
) -> WorkspaceDataProjectionResponse:
    """Return one coherent materialized-plus-Plan Explorer catalog."""

    store = _get_store(request)
    state = _get_state(store, session_id)
    return _workspace_projection(state)
