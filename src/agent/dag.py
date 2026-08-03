"""DAG scheduling and explicit Snapshot/Checkpoint execution."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.agent.checkpoints import (
    CheckpointError,
    checkpoint_id,
    checkpoint_path,
    load_checkpoint,
    new_run_id,
    write_checkpoint_atomically,
)
from src.agent.join_executor import execute_join
from src.agent.lineage import (
    derived_column_node,
    inherited_column_node,
    joined_column_node,
    resolve_local_columns,
)
from src.agent.operations import (
    validate_derive_frame,
    validate_filter_frame,
    validate_join_frame,
)
from src.agent.plan_validation import PlanValidationError, validate_plan
from src.agent.state import (
    AgentState,
    CheckpointRecord,
    ColumnGraph,
    DeriveColumnUnit,
    FilterUnit,
    JoinInput,
    JoinUnit,
    PlanUnit,
    PlanUnitLike,
    SnapshotRecord,
    TerminalUnit,
)

logger = logging.getLogger(__name__)

_MAX_WORKERS = 3


@dataclass(frozen=True)
class _PreparedUnit:
    """Resolved checkpoint context for one executable Plan unit."""

    execution_unit: PlanUnitLike
    input_records: list[CheckpointRecord]
    input_paths: list[str]
    local_columns_by_role: dict[str, dict[str, str]]


class DagCycleError(Exception):
    """Raised when a cycle or missing dependency is found."""

    def __init__(self, unit_ids: set[int]) -> None:
        self.unit_ids = unit_ids
        super().__init__(f"Cycle detected involving units: {sorted(unit_ids)}")


def topological_levels(units: list[PlanUnitLike]) -> list[list[PlanUnitLike]]:
    """Group units into deterministic dependency levels."""
    if not units:
        return []

    unit_map = {unit.unit_id: unit for unit in units}
    in_degree = {unit.unit_id: 0 for unit in units}
    dependents: dict[int, list[int]] = {unit.unit_id: [] for unit in units}
    for unit in units:
        for dependency in unit.depends_on:
            if dependency not in unit_map or dependency == unit.unit_id:
                raise DagCycleError({unit.unit_id, dependency})
            in_degree[unit.unit_id] += 1
            dependents[dependency].append(unit.unit_id)

    ready = sorted(unit_id for unit_id, degree in in_degree.items() if degree == 0)
    levels: list[list[PlanUnitLike]] = []
    processed = 0
    while ready:
        levels.append([unit_map[unit_id] for unit_id in ready])
        processed += len(ready)
        next_ready: list[int] = []
        for unit_id in ready:
            for child_id in sorted(dependents[unit_id]):
                in_degree[child_id] -= 1
                if in_degree[child_id] == 0:
                    next_ready.append(child_id)
        ready = sorted(next_ready)

    if processed != len(units):
        raise DagCycleError({unit_id for unit_id, degree in in_degree.items() if degree})
    return levels


def validate_columns(
    required: list[str], available: set[str]
) -> tuple[list[str], list[str]]:
    """Return missing and present values using exact matching."""
    missing = [column for column in required if column not in available]
    found = [column for column in required if column in available]
    return missing, found


def save_checkpoint(df: pd.DataFrame, path: str) -> None:
    """Compatibility helper for direct checkpoint tests."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def load_checkpoint_file(path: str) -> pd.DataFrame:
    """Load a physical Parquet file without registry resolution."""
    return pd.read_parquet(path)


def _snapshot_by_name(
    snapshots: dict[str, SnapshotRecord], name: str
) -> SnapshotRecord | None:
    return next((snapshot for snapshot in snapshots.values() if snapshot.name == name), None)


def _source_reset_snapshots(state: AgentState) -> dict[str, SnapshotRecord]:
    """Start a fresh full run from immutable source checkpoint heads."""
    snapshots = dict(state.snapshot_registry)
    for source in state.data_sources:
        snapshot = snapshots.get(source.snapshot_id)
        if snapshot is None or source.source_checkpoint_id not in state.checkpoint_registry:
            continue
        snapshots[source.snapshot_id] = snapshot.model_copy(
            update={"current_checkpoint_id": source.source_checkpoint_id}
        )
    return snapshots


def _unit_input_snapshots(unit: PlanUnitLike) -> list[str]:
    if isinstance(unit, DeriveColumnUnit | FilterUnit | TerminalUnit):
        return [unit.input_snapshot]
    if isinstance(unit, JoinUnit):
        by_role = {item.role: item for item in unit.inputs}
        return [by_role["left"].snapshot, by_role["right"].snapshot]
    raise CheckpointError(
        f"Unit {unit.unit_id} is not a Cycle 5 operation-specific unit"
    )


def _unit_output_snapshot(unit: PlanUnitLike) -> str | None:
    if isinstance(unit, DeriveColumnUnit):
        return unit.input_snapshot
    if isinstance(unit, FilterUnit):
        return unit.output_snapshot
    if isinstance(unit, JoinUnit):
        return unit.output_snapshot
    return None


def _ensure_v2_plan(units: Iterable[PlanUnitLike]) -> None:
    if any(isinstance(unit, PlanUnit) for unit in units):
        raise CheckpointError(
            "Execution requires operation-specific Plan v2 units; legacy units "
            "are no longer supported"
        )


def _resolve_records(
    snapshots: dict[str, SnapshotRecord],
    checkpoints: dict[str, CheckpointRecord],
    names: Iterable[str],
    preferred_ids: list[str] | None = None,
) -> list[CheckpointRecord]:
    names_list = list(names)
    if preferred_ids is not None:
        if len(preferred_ids) != len(names_list):
            raise CheckpointError("Stored input checkpoint count does not match unit inputs")
        records: list[CheckpointRecord] = []
        for checkpoint_key in preferred_ids:
            record = checkpoints.get(checkpoint_key)
            if record is None:
                raise CheckpointError(
                    f"Input checkpoint '{checkpoint_key}' is not registered"
                )
            records.append(record)
        return records

    records = []
    for name in names_list:
        snapshot = _snapshot_by_name(snapshots, name)
        if snapshot is None:
            raise CheckpointError(f"Snapshot '{name}' is not registered")
        record = checkpoints.get(snapshot.current_checkpoint_id)
        if record is None:
            raise CheckpointError(
                f"Snapshot '{name}' points to missing checkpoint "
                f"'{snapshot.current_checkpoint_id}'"
            )
        records.append(record)
    return records


def _localize_unit(
    unit: PlanUnitLike,
    local_columns: dict[str, str],
) -> PlanUnitLike:
    """Create the execution view with physical column names."""
    if isinstance(unit, JoinUnit):
        return unit
    updates: dict[str, object] = {
        "input_columns": [local_columns[ref] for ref in unit.input_columns]
    }
    if isinstance(unit, DeriveColumnUnit):
        prefix = f"{unit.input_snapshot}."
        output_ref = unit.output_columns[0]
        if not output_ref.startswith(prefix):
            raise CheckpointError(
                f"Derive output '{output_ref}' is outside Snapshot '{unit.input_snapshot}'"
            )
        updates["output_columns"] = [output_ref[len(prefix):]]
    if isinstance(unit, FilterUnit):
        params = dict(unit.template_params or {})
        params["snapshot_name"] = unit.output_snapshot
        updates["template_params"] = params
    return unit.model_copy(update=updates)


def _unit_result_base(
    unit_id: int,
    *,
    run_id: str,
    input_checkpoint_ids: list[str] | None = None,
    output_dir: str | None = None,
    status: str = "failed",
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "unit_id": unit_id,
        "run_id": run_id,
        "status": status,
        "error": error,
        "charts": [],
        "insights": [],
        "statistics": {},
        "parsed_output": None,
        "retry_count": 0,
        "scripts": [],
        "stdout": "",
        "stderr": "",
        "output_dir": output_dir or "",
        "input_checkpoint_ids": input_checkpoint_ids or [],
        "warnings": [],
        "stale": False,
    }


def _blocked_result(unit_id: int, run_id: str, dependencies: list[int]) -> dict[str, Any]:
    return _unit_result_base(
        unit_id,
        run_id=run_id,
        status="blocked",
        error=f"Blocked by failed upstream units: {dependencies}",
    )


def _physical_output_path(parent_output_dir: str, checkpoint_key: str) -> str:
    relative = Path("analysis") / "checkpoints" / f"{checkpoint_key}.parquet"
    if Path(parent_output_dir).name != "analysis":
        relative = Path("checkpoints") / f"{checkpoint_key}.parquet"
    return relative.as_posix()


def _node_key(run_id: str, unit_id: int, suffix: str) -> str:
    safe_suffix = "".join(char if char.isalnum() else "_" for char in suffix)
    return f"coln_{run_id}_u{unit_id}_{safe_suffix or 'column'}"


def _join_role_for_ref(unit: JoinUnit, ref: str) -> str:
    roles = [
        item.role
        for item in unit.inputs
        if ref.startswith(f"{item.snapshot}.")
    ]
    if len(roles) != 1:
        raise CheckpointError(
            f"Join column '{ref}' does not resolve to exactly one input role"
        )
    return roles[0]


def _commit_data_result(
    *,
    unit: PlanUnitLike,
    result: dict[str, Any],
    input_records: list[CheckpointRecord],
    input_frames: list[pd.DataFrame],
    snapshots: dict[str, SnapshotRecord],
    checkpoints: dict[str, CheckpointRecord],
    graph: ColumnGraph,
    parent_output_dir: str,
    run_id: str,
) -> tuple[CheckpointRecord, SnapshotRecord, ColumnGraph]:
    """Validate a candidate frame, atomically write it, then build registry records."""
    frame = result.get("_result_df")
    if not isinstance(frame, pd.DataFrame):
        raise CheckpointError(
            f"Unit {unit.unit_id} did not return a candidate DataFrame"
        )

    if not input_records or len(input_records) != len(input_frames):
        raise CheckpointError("Input checkpoint and frame counts do not match")

    current_graph = graph.nodes
    new_nodes = dict(current_graph)
    column_map: dict[str, str]
    output_snapshot: str
    input_snapshot_record: SnapshotRecord | None = None
    parent_snapshot_ids: list[str]

    if isinstance(unit, DeriveColumnUnit):
        input_record = input_records[0]
        input_frame = input_frames[0]
        prefix = f"{unit.input_snapshot}."
        output_ref = unit.output_columns[0]
        if not output_ref.startswith(prefix):
            raise CheckpointError(
                f"Derive output '{output_ref}' is outside Snapshot '{unit.input_snapshot}'"
            )
        output_name = output_ref[len(prefix):]
        validate_derive_frame(input_frame, frame, output_name)
        output_snapshot = unit.input_snapshot
        input_snapshot_record = _snapshot_by_name(snapshots, output_snapshot)
        if input_snapshot_record is None:
            raise CheckpointError(f"Snapshot '{output_snapshot}' is not registered")
        parent_snapshot_ids = [input_snapshot_record.snapshot_id]
    elif isinstance(unit, FilterUnit):
        input_record = input_records[0]
        input_frame = input_frames[0]
        validate_filter_frame(input_frame, frame)
        output_snapshot = unit.output_snapshot
        input_snapshot_record = _snapshot_by_name(snapshots, unit.input_snapshot)
        if input_snapshot_record is None:
            raise CheckpointError(f"Snapshot '{unit.input_snapshot}' is not registered")
        parent_snapshot_ids = [input_snapshot_record.snapshot_id]
    elif isinstance(unit, JoinUnit):
        if len(input_records) != 2 or len(input_frames) != 2:
            raise CheckpointError("Join execution requires left and right inputs")
        aliases = [selected.as_ for selected in unit.select]
        validate_join_frame(frame, aliases)
        output_snapshot = unit.output_snapshot
        parent_snapshot_ids = []
        by_role: dict[str, JoinInput] = {item.role: item for item in unit.inputs}
        for role in ("left", "right"):
            parent_snapshot = _snapshot_by_name(snapshots, by_role[role].snapshot)
            if parent_snapshot is None:
                raise CheckpointError(
                    f"Snapshot '{by_role[role].snapshot}' is not registered"
                )
            parent_snapshot_ids.append(parent_snapshot.snapshot_id)
    else:
        raise CheckpointError(
            f"Unit {unit.unit_id} operation '{getattr(unit, 'operation', '')}' "
            "does not produce a data checkpoint"
        )

    checkpoint_key = checkpoint_id(run_id, unit.unit_id)
    relative_path = _physical_output_path(parent_output_dir, checkpoint_key)
    write_checkpoint_atomically(
        frame,
        relative_path=relative_path,
        parent_output_dir=parent_output_dir,
    )

    if isinstance(unit, DeriveColumnUnit):
        input_record = input_records[0]
        column_map = dict(input_record.columns)
        output_ref = unit.output_columns[0]
        output_name = output_ref[len(f"{unit.input_snapshot}."):]
        parents: dict[str, Any] = {}
        for ref in unit.input_columns:
            parent_id = input_record.columns.get(ref)
            if parent_id is None or parent_id not in current_graph:
                raise CheckpointError(f"Missing lineage parent for '{ref}'")
            parents[ref] = current_graph[parent_id]
        output_node_id = _node_key(run_id, unit.unit_id, output_name)
        new_nodes[output_node_id] = derived_column_node(
            node_id=output_node_id,
            ref=output_ref,
            name=output_name,
            snapshot=unit.input_snapshot,
            dtype=str(frame[output_name].dtype),
            row_count=len(frame),
            parents=parents,
            created_by_unit_id=unit.unit_id,
        )
        column_map[output_ref] = output_node_id
    elif isinstance(unit, FilterUnit):
        input_record = input_records[0]
        column_map = {}
        for ref, parent_id in input_record.columns.items():
            parent_node = current_graph.get(parent_id)
            if parent_node is None:
                raise CheckpointError(f"Missing lineage parent for '{ref}'")
            local_name = parent_node.name
            output_ref = f"{output_snapshot}.{local_name}"
            node_id = _node_key(run_id, unit.unit_id, local_name)
            new_nodes[node_id] = inherited_column_node(
                node_id=node_id,
                ref=output_ref,
                name=local_name,
                snapshot=output_snapshot,
                dtype=str(frame[local_name].dtype),
                row_count=len(frame),
                parent=parent_node,
                created_by_unit_id=unit.unit_id,
            )
            column_map[output_ref] = node_id
    else:
        if not isinstance(unit, JoinUnit):
            raise CheckpointError("Unsupported data-producing unit")
        column_map = {}
        role_records = {"left": input_records[0], "right": input_records[1]}
        for selected in unit.select:
            role = _join_role_for_ref(unit, selected.from_)
            parent_id = role_records[role].columns.get(selected.from_)
            if parent_id is None or parent_id not in current_graph:
                raise CheckpointError(
                    f"Missing lineage parent for Join column '{selected.from_}'"
                )
            parent_node = current_graph[parent_id]
            output_ref = f"{unit.output_snapshot}.{selected.as_}"
            node_id = _node_key(run_id, unit.unit_id, selected.as_)
            new_nodes[node_id] = joined_column_node(
                node_id=node_id,
                ref=output_ref,
                name=selected.as_,
                snapshot=unit.output_snapshot,
                dtype=str(frame[selected.as_].dtype),
                row_count=len(frame),
                parent=parent_node,
                created_by_unit_id=unit.unit_id,
            )
            column_map[output_ref] = node_id

    if isinstance(unit, DeriveColumnUnit):
        if input_snapshot_record is None:
            raise CheckpointError("Derive input Snapshot is not registered")
        checkpoint_snapshot_id = input_snapshot_record.snapshot_id
    else:
        checkpoint_snapshot_id = f"snap_{output_snapshot}"

    checkpoint = CheckpointRecord(
        checkpoint_id=checkpoint_key,
        snapshot_id=checkpoint_snapshot_id,
        parent_checkpoint_ids=[record.checkpoint_id for record in input_records],
        producer_unit_id=unit.unit_id,
        run_id=run_id,
        path=relative_path,
        row_count=len(frame),
        columns=column_map,
    )
    if isinstance(unit, DeriveColumnUnit):
        if input_snapshot_record is None:
            raise CheckpointError("Derive input Snapshot is not registered")
        snapshot = input_snapshot_record.model_copy(
            update={"current_checkpoint_id": checkpoint.checkpoint_id}
        )
    elif isinstance(unit, FilterUnit):
        previous = _snapshot_by_name(snapshots, output_snapshot)
        if input_snapshot_record is None:
            raise CheckpointError("Filter input Snapshot is not registered")
        snapshot = SnapshotRecord(
            snapshot_id=checkpoint.snapshot_id,
            name=output_snapshot,
            display_name=(previous.display_name if previous else output_snapshot),
            current_checkpoint_id=checkpoint.checkpoint_id,
            created_by_unit_id=unit.unit_id,
            parent_snapshot_ids=[input_snapshot_record.snapshot_id],
        )
    elif isinstance(unit, JoinUnit):
        previous = _snapshot_by_name(snapshots, output_snapshot)
        snapshot = SnapshotRecord(
            snapshot_id=checkpoint.snapshot_id,
            name=output_snapshot,
            display_name=(previous.display_name if previous else output_snapshot),
            current_checkpoint_id=checkpoint.checkpoint_id,
            created_by_unit_id=unit.unit_id,
            parent_snapshot_ids=parent_snapshot_ids,
        )
    else:
        raise CheckpointError("Unsupported data-producing unit")
    return checkpoint, snapshot, ColumnGraph(nodes=new_nodes)


def _annotate_success(
    result: dict[str, Any],
    *,
    run_id: str,
    input_records: list[CheckpointRecord],
) -> dict[str, Any]:
    result["run_id"] = run_id
    result["input_checkpoint_ids"] = [record.checkpoint_id for record in input_records]
    result["row_count_before"] = input_records[0].row_count if input_records else None
    result["input_row_counts"] = [record.row_count for record in input_records]
    result["warnings"] = list(result.get("warnings", []))
    result["stale"] = False
    return result


def _finalize_data_result(
    result: dict[str, Any],
    *,
    checkpoint: CheckpointRecord,
    input_records: list[CheckpointRecord],
) -> dict[str, Any]:
    result["output_checkpoint_id"] = checkpoint.checkpoint_id
    result["row_count_after"] = checkpoint.row_count
    result["row_count_delta"] = (
        checkpoint.row_count - input_records[0].row_count if input_records else None
    )
    return result


def _prepare_unit(
    unit: PlanUnitLike,
    *,
    snapshots: dict[str, SnapshotRecord],
    checkpoints: dict[str, CheckpointRecord],
    graph: ColumnGraph,
    parent_output_dir: str,
    preferred_checkpoint_ids: list[str] | None = None,
) -> _PreparedUnit:
    input_names = _unit_input_snapshots(unit)
    input_records = _resolve_records(
        snapshots, checkpoints, input_names, preferred_checkpoint_ids
    )
    if isinstance(unit, JoinUnit):
        if len(input_records) != 2:
            raise CheckpointError("Join execution requires exactly two input Snapshots")
        local_columns_by_role: dict[str, dict[str, str]] = {}
        by_role: dict[str, JoinInput] = {item.role: item for item in unit.inputs}
        for index, role in enumerate(("left", "right")):
            refs = [
                *(key.left if role == "left" else key.right for key in unit.keys),
                *(selected.from_ for selected in unit.select
                  if selected.from_.startswith(f"{by_role[role].snapshot}.")),
            ]
            local_columns_by_role[role] = resolve_local_columns(
                input_records[index], graph, dict.fromkeys(refs)
            )
    else:
        execution_unit: PlanUnitLike = unit
        if len(input_records) != 1:
            raise CheckpointError("Single-input operation received multiple Snapshots")
        refs = list(unit.input_columns)
        local_columns = resolve_local_columns(input_records[0], graph, refs)
        execution_unit = _localize_unit(unit, local_columns)
        local_columns_by_role = {"single": local_columns}

    input_paths: list[str] = []
    for input_record in input_records:
        input_path = str(checkpoint_path(input_record, parent_output_dir))
        if not Path(input_path).is_file():
            raise CheckpointError(
                f"Checkpoint {input_record.checkpoint_id} is missing at {input_record.path}"
            )
        input_paths.append(input_path)

    return _PreparedUnit(
        execution_unit=unit if isinstance(unit, JoinUnit) else execution_unit,
        input_records=input_records,
        input_paths=input_paths,
        local_columns_by_role=local_columns_by_role,
    )


def _execute_join_unit(
    unit: JoinUnit,
    input_paths: list[str],
    output_dir: str,
    local_columns_by_role: dict[str, dict[str, str]],
    run_id: str,
) -> dict[str, Any]:
    """Load two registered frames and execute Join deterministically."""
    if len(input_paths) != 2:
        raise CheckpointError("Join execution requires two checkpoint paths")
    left_frame = pd.read_parquet(input_paths[0])
    right_frame = pd.read_parquet(input_paths[1])
    join_result = execute_join(
        unit,
        left_frame,
        right_frame,
        left_columns=local_columns_by_role["left"],
        right_columns=local_columns_by_role["right"],
        row_id_prefix=f"{unit.output_snapshot}:{run_id}",
    )
    return {
        "unit_id": unit.unit_id,
        "status": "success",
        "parsed_output": None,
        "charts": [],
        "insights": [],
        "statistics": join_result.statistics,
        "warnings": join_result.warnings,
        "error": None,
        "retry_count": 0,
        "scripts": [],
        "stdout": "",
        "stderr": "",
        "output_dir": output_dir,
        "_result_df": join_result.frame,
    }


def _durable_result(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _durable_result(item)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    if isinstance(value, list):
        return [_durable_result(item) for item in value]
    return value


def _execute_levels(
    state: AgentState,
    parent_output_dir: str,
    prev_unit_results: dict[int, dict[str, Any]],
    execute_unit_fn: Callable[..., dict[str, Any]],
    *,
    run_id: str,
    snapshots: dict[str, SnapshotRecord],
    checkpoints: dict[str, CheckpointRecord],
    graph: ColumnGraph,
    units: list[PlanUnitLike],
    preferred_inputs: dict[int, list[str]] | None = None,
) -> dict[str, Any]:
    levels = topological_levels(units)
    run_output_dir = Path(parent_output_dir) / "runs" / run_id
    run_output_dir.mkdir(parents=True, exist_ok=True)
    unit_results: list[dict[str, Any]] = []
    failed_ids: set[int] = set()
    updated_snapshots: set[str] = set()
    unit_map = {unit.unit_id: unit for unit in units}

    for level in levels:
        tasks: list[tuple[PlanUnitLike, _PreparedUnit, str]] = []
        for unit in level:
            failed_dependencies = [
                dependency for dependency in unit.depends_on if dependency in failed_ids
            ]
            if failed_dependencies:
                blocked = _blocked_result(unit.unit_id, run_id, failed_dependencies)
                unit_results.append(blocked)
                failed_ids.add(unit.unit_id)
                continue
            unit_dir_path = run_output_dir / f"unit_{unit.unit_id}"
            try:
                preferred = (preferred_inputs or {}).get(unit.unit_id)
                if any(
                    snapshot in updated_snapshots
                    for snapshot in _unit_input_snapshots(unit)
                ):
                    preferred = None
                prepared = _prepare_unit(
                    unit,
                    snapshots=snapshots,
                    checkpoints=checkpoints,
                    graph=graph,
                    parent_output_dir=parent_output_dir,
                    preferred_checkpoint_ids=preferred,
                )
                tasks.append((unit, prepared, str(unit_dir_path)))
            except (CheckpointError, KeyError, ValueError) as exc:
                failed = _unit_result_base(
                    unit.unit_id,
                    run_id=run_id,
                    status="failed",
                    error=str(exc),
                )
                unit_results.append(failed)
                failed_ids.add(unit.unit_id)

        if not tasks:
            continue
        max_workers = min(len(tasks), _MAX_WORKERS)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures: dict[Any, tuple[PlanUnitLike, _PreparedUnit]] = {}
            for unit, prepared, unit_dir in tasks:
                if isinstance(unit, JoinUnit):
                    future = executor.submit(
                        _execute_join_unit,
                        unit,
                        prepared.input_paths,
                        unit_dir,
                        prepared.local_columns_by_role,
                        run_id,
                    )
                else:
                    future = executor.submit(
                        execute_unit_fn,
                        prepared.execution_unit,
                        prepared.input_paths[0],
                        unit_dir,
                        prev_unit_results.get(unit.unit_id),
                    )
                futures[future] = (unit, prepared)

            completed: list[tuple[PlanUnitLike, _PreparedUnit, dict[str, Any]]] = []
            for future in as_completed(futures):
                unit, prepared = futures[future]
                try:
                    raw_result = future.result()
                    result = dict(raw_result) if isinstance(raw_result, dict) else {}
                except Exception as exc:
                    result = _unit_result_base(
                        unit.unit_id,
                        run_id=run_id,
                        status="failed",
                        error=f"Executor error: {exc}",
                    )
                completed.append((unit, prepared, result))

            for unit, prepared, result in sorted(
                completed, key=lambda item: item[0].unit_id
            ):
                if result.get("status") != "success":
                    result.setdefault("unit_id", unit.unit_id)
                    result["run_id"] = run_id
                    result.setdefault(
                        "input_checkpoint_ids",
                        [record.checkpoint_id for record in prepared.input_records],
                    )
                    result.setdefault("warnings", [])
                    result.setdefault("stale", False)
                    unit_results.append(result)
                    failed_ids.add(unit.unit_id)
                    continue

                result = _annotate_success(
                    result, run_id=run_id, input_records=prepared.input_records
                )
                if isinstance(unit, DeriveColumnUnit | FilterUnit | JoinUnit):
                    try:
                        input_frames = [
                            load_checkpoint(record, parent_output_dir)
                            for record in prepared.input_records
                        ]
                        checkpoint, snapshot, new_graph = _commit_data_result(
                            unit=unit,
                            result=result,
                            input_records=prepared.input_records,
                            input_frames=input_frames,
                            snapshots=snapshots,
                            checkpoints=checkpoints,
                            graph=graph,
                            parent_output_dir=parent_output_dir,
                            run_id=run_id,
                        )
                    except (CheckpointError, KeyError, ValueError) as exc:
                        result.update(
                            _unit_result_base(
                                unit.unit_id,
                                run_id=run_id,
                                input_checkpoint_ids=[
                                    record.checkpoint_id
                                    for record in prepared.input_records
                                ],
                                output_dir=str(result.get("output_dir", "")),
                                error=str(exc),
                            )
                        )
                        failed_ids.add(unit.unit_id)
                    else:
                        checkpoints[checkpoint.checkpoint_id] = checkpoint
                        snapshots[snapshot.snapshot_id] = snapshot
                        graph = new_graph
                        output_snapshot = _unit_output_snapshot(unit)
                        if output_snapshot is not None:
                            updated_snapshots.add(output_snapshot)
                        result = _finalize_data_result(
                            result,
                            checkpoint=checkpoint,
                            input_records=prepared.input_records,
                        )
                elif isinstance(unit, TerminalUnit):
                    result["row_count_after"] = prepared.input_records[0].row_count
                    result["row_count_delta"] = 0
                else:
                    result.update(
                        _unit_result_base(
                            unit.unit_id,
                            run_id=run_id,
                            input_checkpoint_ids=[
                                record.checkpoint_id
                                for record in prepared.input_records
                            ],
                            output_dir=str(result.get("output_dir", "")),
                            error="Unsupported operation for DAG execution",
                        )
                    )
                    failed_ids.add(unit.unit_id)
                unit_results.append(result)

    unit_results.sort(key=lambda item: int(item.get("unit_id", 0)))
    all_success = bool(unit_results) and all(
        item.get("status") == "success" for item in unit_results
    )
    return {
        "unit_results": unit_results,
        "status": "complete" if all_success else "partial",
        "output_dir": parent_output_dir,
        "run_id": run_id,
        "snapshot_registry": snapshots,
        "checkpoint_registry": checkpoints,
        "column_graph": graph,
        "failed_unit_ids": sorted(failed_ids),
        "unit_map": unit_map,
    }


def execute_dag(
    state: AgentState,
    parent_output_dir: str,
    prev_unit_results: dict[int, dict[str, Any]],
    execute_unit_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Execute a v2 Plan using Snapshot heads and registered checkpoints only."""
    plan = state.plan
    if plan is None:
        return {
            "unit_results": [],
            "status": "failed",
            "output_dir": parent_output_dir,
            "dag_error": "No plan available",
        }
    try:
        _ensure_v2_plan(plan.units)
    except CheckpointError as exc:
        return {
            "unit_results": [],
            "status": "failed",
            "output_dir": parent_output_dir,
            "dag_error": str(exc),
        }
    try:
        validate_plan(
            plan,
            state,
            allow_reexecution=any(
                record.producer_unit_id is not None
                for record in state.checkpoint_registry.values()
            ),
        )
    except PlanValidationError as exc:
        return {
            "unit_results": [],
            "status": "failed",
            "output_dir": parent_output_dir,
            "dag_error": str(exc),
            "validation_issues": [issue.model_dump() for issue in exc.issues],
        }

    run_id = new_run_id()
    result = _execute_levels(
        state,
        parent_output_dir,
        prev_unit_results,
        execute_unit_fn,
        run_id=run_id,
        snapshots=_source_reset_snapshots(state),
        checkpoints=dict(state.checkpoint_registry),
        graph=state.column_graph,
        units=list(plan.units),
    )
    result.pop("unit_map", None)
    result.pop("failed_unit_ids", None)
    return result


def transitive_dependents(unit_id: int, units: list[PlanUnitLike]) -> list[int]:
    """Return downstream units in deterministic topological order."""
    children: dict[int, list[int]] = {unit.unit_id: [] for unit in units}
    for unit in units:
        for dependency in unit.depends_on:
            if dependency in children:
                children[dependency].append(unit.unit_id)
    seen: set[int] = set()
    queue = [unit_id]
    while queue:
        current = queue.pop(0)
        for child in sorted(children.get(current, [])):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    position = {
        unit.unit_id: index for index, unit in enumerate(sum(topological_levels(units), []))
    }
    return sorted(seen, key=lambda value: position.get(value, value))


def rerun_dag(
    state: AgentState,
    parent_output_dir: str,
    unit_id: int,
    *,
    cascade: bool,
    execute_unit_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Rerun a unit from recorded inputs and retain all previous checkpoints."""
    if state.plan is None:
        raise CheckpointError("No plan available")
    _ensure_v2_plan(state.plan.units)
    validate_plan(state.plan, state, allow_reexecution=True)
    units = list(state.plan.units)
    units_by_id = {unit.unit_id: unit for unit in units}
    target = units_by_id.get(unit_id)
    if target is None:
        raise CheckpointError(f"Unit {unit_id} not found in plan")

    dependent_ids = transitive_dependents(unit_id, units)
    selected_ids = {unit_id, *dependent_ids} if cascade else {unit_id}
    selected_units = [
        unit.model_copy(
            update={
                "depends_on": [
                    dependency
                    for dependency in unit.depends_on
                    if dependency in selected_ids
                ]
            }
        )
        for unit in units
        if unit.unit_id in selected_ids
    ]
    ordered_ids = [unit.unit_id for unit in sum(topological_levels(selected_units), [])]

    current_results = {
        int(item["unit_id"]): item
        for item in (state.analysis_result or {}).get("unit_results", [])
        if isinstance(item, dict) and "unit_id" in item
    }
    preferred_inputs: dict[int, list[str]] = {}
    for selected_id in ordered_ids:
        stored = current_results.get(selected_id, {})
        ids = stored.get("input_checkpoint_ids")
        if isinstance(ids, list) and all(isinstance(item, str) for item in ids):
            preferred_inputs[selected_id] = list(ids)

    run_id = new_run_id()
    snapshots = dict(state.snapshot_registry)
    checkpoints = dict(state.checkpoint_registry)
    graph = state.column_graph
    selected_result = _execute_levels(
        state,
        parent_output_dir,
        current_results,
        execute_unit_fn,
        run_id=run_id,
        snapshots=snapshots,
        checkpoints=checkpoints,
        graph=graph,
        units=selected_units,
        preferred_inputs=preferred_inputs,
    )
    rerun_results = {
        int(item["unit_id"]): item
        for item in selected_result["unit_results"]
        if isinstance(item, dict) and "unit_id" in item
    }

    history = list((state.analysis_result or {}).get("history", []))
    previous_run_id = (state.analysis_result or {}).get("run_id")
    if previous_run_id:
        history.append(
            {
                "run_id": previous_run_id,
                "unit_results": _durable_result(
                    list((state.analysis_result or {}).get("unit_results", []))
                ),
            }
        )

    merged_results: list[dict[str, Any]] = []
    for unit in units:
        result = rerun_results.get(unit.unit_id, current_results.get(unit.unit_id))
        if result is not None:
            merged_results.append(dict(result))

    stale_ids = []
    if not cascade:
        stale_ids = dependent_ids
        for result in merged_results:
            if result.get("unit_id") in stale_ids:
                result["stale"] = True

    analysis_result = {
        "status": selected_result["status"] if cascade else "complete",
        "output_dir": parent_output_dir,
        "run_id": run_id,
        "unit_results": merged_results,
        "history": history,
    }
    return {
        "analysis_result": analysis_result,
        "snapshot_registry": selected_result["snapshot_registry"],
        "checkpoint_registry": selected_result["checkpoint_registry"],
        "column_graph": selected_result["column_graph"],
        "stale_unit_ids": stale_ids,
        "rerun_result": rerun_results.get(unit_id, {}),
    }
