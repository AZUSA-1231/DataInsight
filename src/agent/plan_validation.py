"""Deterministic validation for Plan v2.

Pydantic validates the shape of individual operation units. This module
validates the complete plan against the current Snapshot and Column registries
without touching the filesystem or mutating state.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, Field

from src.agent.state import (
    AgentState,
    DeriveColumnUnit,
    FilterUnit,
    JoinUnit,
    Plan,
    PlanUnit,
    PlanUnitValue,
    TerminalUnit,
)

if TYPE_CHECKING:
    from src.agent.state import (
        CheckpointRecord,
        ColumnGraph,
        SnapshotRecord,
    )


_SNAPSHOT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class PlanValidationIssue(BaseModel):
    """One stable, frontend-safe validation issue."""

    code: str
    unit_id: int | None = None
    field: str | None = None
    message: str


class PlanValidationError(ValueError):
    """Raised when a complete Plan cannot be saved or executed."""

    def __init__(self, issues: list[PlanValidationIssue]) -> None:
        self.issues = issues
        summary = "; ".join(issue.message for issue in issues)
        super().__init__(summary or "Plan validation failed")

    def as_detail(self) -> dict[str, object]:
        return {
            "code": "INVALID_PLAN",
            "message": str(self),
            "issues": [issue.model_dump() for issue in self.issues],
        }


class PlanValidationResult(BaseModel):
    """Non-throwing result form for callers that need to render issues."""

    valid: bool
    issues: list[PlanValidationIssue] = Field(default_factory=list)


@dataclass
class _SnapshotView:
    """The refs visible at one point in deterministic plan simulation."""

    name: str
    refs: dict[str, str]
    producer_unit_id: int | None = None


def collect_plan_issues(
    plan: Plan,
    state: AgentState | dict[str, SnapshotRecord] | None = None,
    snapshot_registry: dict[str, SnapshotRecord] | None = None,
    checkpoint_registry: dict[str, CheckpointRecord] | None = None,
    column_graph: ColumnGraph | None = None,
    allow_reexecution: bool = False,
) -> list[PlanValidationIssue]:
    """Return all deterministic issues found in ``plan``.

    ``state`` is the preferred argument. The explicit registry arguments are
    useful for isolated tests and small API integrations.
    """

    if state is not None and hasattr(state, "snapshot_registry"):
        state_obj = cast(AgentState, state)
        snapshot_registry = state_obj.snapshot_registry
        checkpoint_registry = state_obj.checkpoint_registry
        column_graph = state_obj.column_graph
    elif isinstance(state, dict) and snapshot_registry is None:
        # Also accept the natural positional form used by isolated callers:
        # validate_plan(plan, snapshots, checkpoints, column_graph).
        snapshot_registry = state

    snapshots = snapshot_registry or {}
    checkpoints = checkpoint_registry or {}
    graph_nodes = column_graph.nodes if column_graph is not None else {}

    issues: list[PlanValidationIssue] = []
    units = list(plan.units)
    unit_by_id: dict[int, PlanUnitValue] = {}

    for unit in units:
        unit_id = getattr(unit, "unit_id", None)
        if unit_id in unit_by_id:
            issues.append(
                PlanValidationIssue(
                    code="DUPLICATE_UNIT_ID",
                    unit_id=unit_id,
                    field="unit_id",
                    message=f"Unit ID {unit_id} is used more than once",
                )
            )
        elif isinstance(unit_id, int) and unit_id > 0:
            unit_by_id[unit_id] = unit
        else:
            issues.append(
                PlanValidationIssue(
                    code="INVALID_UNIT_ID",
                    unit_id=unit_id if isinstance(unit_id, int) else None,
                    field="unit_id",
                    message="unit_id must be a positive integer",
                )
            )

    if not units:
        return issues

    # Legacy units are tolerated only as a complete legacy plan without a v2
    # registry. They are never used as a source of truth by the v2 path.
    has_v2 = any(not isinstance(unit, PlanUnit) for unit in units)
    if not has_v2:
        if snapshots:
            issues.append(
                PlanValidationIssue(
                    code="LEGACY_PLAN_UNIT",
                    field="units",
                    message="Cycle 4 Plan units cannot be saved in a v2 data session",
                )
            )
        return issues

    for unit in units:
        if isinstance(unit, PlanUnit):
            issues.append(
                PlanValidationIssue(
                    code="LEGACY_PLAN_UNIT",
                    unit_id=unit.unit_id,
                    field="operation",
                    message="Every unit in a v2 Plan must declare an operation",
                )
            )

    dependencies: dict[int, set[int]] = {}
    children: dict[int, set[int]] = defaultdict(set)
    for unit_id, unit in unit_by_id.items():
        deps = set(getattr(unit, "depends_on", []))
        dependencies[unit_id] = deps
        for dependency in deps:
            if dependency not in unit_by_id:
                issues.append(
                    PlanValidationIssue(
                        code="UNKNOWN_DEPENDENCY",
                        unit_id=unit_id,
                        field="depends_on",
                        message=f"Unit {unit_id} depends on unknown unit {dependency}",
                    )
                )
            else:
                children[dependency].add(unit_id)

    topological_ids = _topological_order(unit_by_id, dependencies, issues)

    views = _initial_snapshot_views(snapshots, checkpoints, graph_nodes, issues)
    original_snapshot_names = set(views)
    planned_producers: dict[str, int] = {}

    for unit_id in topological_ids:
        unit = unit_by_id[unit_id]
        if isinstance(unit, PlanUnit):
            continue

        if isinstance(unit, DeriveColumnUnit):
            _validate_derive(
                unit,
                unit_by_id,
                dependencies,
                views,
                planned_producers,
                issues,
                graph_nodes,
                allow_reexecution,
            )
        elif isinstance(unit, FilterUnit):
            _validate_filter(
                unit,
                unit_by_id,
                dependencies,
                views,
                planned_producers,
                original_snapshot_names,
                issues,
                allow_reexecution,
            )
        elif isinstance(unit, JoinUnit):
            _validate_join(
                unit,
                unit_by_id,
                dependencies,
                views,
                planned_producers,
                original_snapshot_names,
                issues,
                allow_reexecution,
            )
        elif isinstance(unit, TerminalUnit):
            _validate_terminal(
                unit,
                unit_by_id,
                dependencies,
                views,
                planned_producers,
                issues,
            )

    _validate_same_snapshot_writer_chains(units, topological_ids, dependencies, issues)

    terminal_ids = {
        unit.unit_id for unit in units if isinstance(unit, TerminalUnit)
    }
    for terminal_id in sorted(terminal_ids):
        if children.get(terminal_id):
            issues.append(
                PlanValidationIssue(
                    code="TERMINAL_NOT_LEAF",
                    unit_id=terminal_id,
                    field="depends_on",
                    message=f"Terminal unit {terminal_id} must be a DAG leaf",
                )
            )

    return _deduplicate_issues(issues)


def validate_plan(
    plan: Plan,
    state: AgentState | dict[str, SnapshotRecord] | None = None,
    snapshot_registry: dict[str, SnapshotRecord] | None = None,
    checkpoint_registry: dict[str, CheckpointRecord] | None = None,
    column_graph: ColumnGraph | None = None,
    allow_reexecution: bool = False,
) -> Plan:
    """Validate and return ``plan`` or raise a structured error."""

    issues = collect_plan_issues(
        plan,
        state,
        snapshot_registry=snapshot_registry,
        checkpoint_registry=checkpoint_registry,
        column_graph=column_graph,
        allow_reexecution=allow_reexecution,
    )
    if issues:
        raise PlanValidationError(issues)
    return plan


def validate_plan_result(
    plan: Plan,
    state: AgentState | dict[str, SnapshotRecord] | None = None,
    snapshot_registry: dict[str, SnapshotRecord] | None = None,
    checkpoint_registry: dict[str, CheckpointRecord] | None = None,
    column_graph: ColumnGraph | None = None,
    allow_reexecution: bool = False,
) -> PlanValidationResult:
    """Return a renderable validation result without raising."""

    issues = collect_plan_issues(
        plan,
        state,
        snapshot_registry=snapshot_registry,
        checkpoint_registry=checkpoint_registry,
        column_graph=column_graph,
        allow_reexecution=allow_reexecution,
    )
    return PlanValidationResult(valid=not issues, issues=issues)


def _initial_snapshot_views(
    snapshots: dict[str, SnapshotRecord],
    checkpoints: dict[str, CheckpointRecord],
    graph_nodes: dict[str, Any],
    issues: list[PlanValidationIssue],
) -> dict[str, _SnapshotView]:
    views: dict[str, _SnapshotView] = {}
    for snapshot in snapshots.values():
        name = snapshot.name
        checkpoint = checkpoints.get(snapshot.current_checkpoint_id)
        if checkpoint is None:
            issues.append(
                PlanValidationIssue(
                    code="MISSING_SNAPSHOT_CHECKPOINT",
                    field="snapshot_registry",
                    message=(
                        f"Snapshot '{name}' points to missing checkpoint "
                        f"'{snapshot.current_checkpoint_id}'"
                    ),
                )
            )
            views[name] = _SnapshotView(name=name, refs={})
            continue

        refs: dict[str, str] = {}
        for ref, node_id in checkpoint.columns.items():
            if node_id not in graph_nodes:
                issues.append(
                    PlanValidationIssue(
                        code="MISSING_COLUMN_NODE",
                        field="checkpoint_registry.columns",
                        message=f"Checkpoint column '{ref}' points to missing node '{node_id}'",
                    )
                )
            refs[ref] = node_id
        views[name] = _SnapshotView(
            name=name,
            refs=refs,
            producer_unit_id=snapshot.created_by_unit_id,
        )
    return views


def _topological_order(
    unit_by_id: dict[int, PlanUnitValue],
    dependencies: dict[int, set[int]],
    issues: list[PlanValidationIssue],
) -> list[int]:
    indegree = {
        unit_id: len(deps & unit_by_id.keys())
        for unit_id, deps in dependencies.items()
    }
    ready = deque(sorted(unit_id for unit_id, degree in indegree.items() if degree == 0))
    order: list[int] = []
    children: dict[int, set[int]] = defaultdict(set)
    for unit_id, deps in dependencies.items():
        for dependency in deps & unit_by_id.keys():
            children[dependency].add(unit_id)

    while ready:
        current = ready.popleft()
        order.append(current)
        for child in sorted(children[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)

    if len(order) != len(unit_by_id):
        issues.append(
            PlanValidationIssue(
                code="DAG_CYCLE",
                field="depends_on",
                message="Plan dependencies contain a cycle",
            )
        )
        return sorted(unit_by_id)
    return order


def _validate_derive(
    unit: DeriveColumnUnit,
    unit_by_id: dict[int, PlanUnitValue],
    dependencies: dict[int, set[int]],
    views: dict[str, _SnapshotView],
    planned_producers: dict[str, int],
    issues: list[PlanValidationIssue],
    graph_nodes: dict[str, Any],
    allow_reexecution: bool,
) -> None:
    view = _require_snapshot(unit.input_snapshot, unit.unit_id, "input_snapshot", views, issues)
    if view is None:
        return
    _require_refs(unit.input_columns, view, unit.unit_id, "input_columns", issues)
    output_ref = unit.output_columns[0]
    prefix = f"{unit.input_snapshot}."
    if not output_ref.startswith(prefix) or output_ref == prefix:
        issues.append(
            PlanValidationIssue(
                code="DERIVE_OUTPUT_SNAPSHOT_MISMATCH",
                unit_id=unit.unit_id,
                field="output_columns",
                message=(
                    f"Derive output '{output_ref}' must be a qualified column in "
                    f"Snapshot '{unit.input_snapshot}'"
                ),
            )
        )
    existing_output = output_ref in view.refs
    existing_node = graph_nodes.get(view.refs.get(output_ref, ""))
    output_is_same_producer = bool(
        existing_node is not None
        and existing_node.created_by_unit_id == unit.unit_id
    )
    if existing_output and not (allow_reexecution and output_is_same_producer):
        issues.append(
            PlanValidationIssue(
                code="DERIVE_OUTPUT_EXISTS",
                unit_id=unit.unit_id,
                field="output_columns",
                message=f"Derive output column '{output_ref}' already exists",
            )
        )
    _require_planned_snapshot_dependency(
        unit,
        [unit.input_snapshot],
        dependencies,
        planned_producers,
        issues,
    )
    view.refs[output_ref] = f"planned:unit_{unit.unit_id}:{output_ref}"
    planned_producers[unit.input_snapshot] = unit.unit_id


def _validate_filter(
    unit: FilterUnit,
    unit_by_id: dict[int, PlanUnitValue],
    dependencies: dict[int, set[int]],
    views: dict[str, _SnapshotView],
    planned_producers: dict[str, int],
    original_snapshot_names: set[str],
    issues: list[PlanValidationIssue],
    allow_reexecution: bool,
) -> None:
    view = _require_snapshot(unit.input_snapshot, unit.unit_id, "input_snapshot", views, issues)
    if view is None:
        return
    _require_refs(unit.input_columns, view, unit.unit_id, "input_columns", issues)
    _validate_new_snapshot_name(
        unit.output_snapshot,
        unit.unit_id,
        original_snapshot_names,
        views,
        issues,
        allow_reexecution=allow_reexecution,
    )
    _require_planned_snapshot_dependency(
        unit,
        [unit.input_snapshot],
        dependencies,
        planned_producers,
        issues,
    )
    output_refs = {
        _replace_snapshot_prefix(ref, unit.input_snapshot, unit.output_snapshot): node_id
        for ref, node_id in view.refs.items()
    }
    views[unit.output_snapshot] = _SnapshotView(
        name=unit.output_snapshot,
        refs=output_refs,
        producer_unit_id=unit.unit_id,
    )
    planned_producers[unit.output_snapshot] = unit.unit_id


def _validate_join(
    unit: JoinUnit,
    unit_by_id: dict[int, PlanUnitValue],
    dependencies: dict[int, set[int]],
    views: dict[str, _SnapshotView],
    planned_producers: dict[str, int],
    original_snapshot_names: set[str],
    issues: list[PlanValidationIssue],
    allow_reexecution: bool,
) -> None:
    by_role = {item.role: item for item in unit.inputs}
    role_views: dict[str, _SnapshotView] = {}
    for role in ("left", "right"):
        item = by_role.get(role)
        if item is None:
            continue
        view = _require_snapshot(item.snapshot, unit.unit_id, f"inputs.{role}", views, issues)
        if view is not None:
            role_views[role] = view

    for key in unit.keys:
        _require_join_ref(key.left, "left", by_role, role_views, unit.unit_id, issues)
        _require_join_ref(key.right, "right", by_role, role_views, unit.unit_id, issues)

    aliases: set[str] = set()
    for selected in unit.select:
        if selected.as_ in aliases:
            issues.append(
                PlanValidationIssue(
                    code="DUPLICATE_JOIN_ALIAS",
                    unit_id=unit.unit_id,
                    field="select",
                    message=f"Join alias '{selected.as_}' is declared more than once",
                )
            )
        aliases.add(selected.as_)
        matching_role = _role_for_snapshot(selected.from_, by_role)
        if selected.as_ == "__di_row_id":
            issues.append(
                PlanValidationIssue(
                    code="JOIN_RESERVED_ALIAS",
                    unit_id=unit.unit_id,
                    field="select",
                    message="Join alias '__di_row_id' is reserved",
                )
            )
        if matching_role is None:
            issues.append(
                PlanValidationIssue(
                    code="JOIN_SELECT_SNAPSHOT_MISMATCH",
                    unit_id=unit.unit_id,
                    field="select",
                    message=f"Join select '{selected.from_}' is not from a declared input Snapshot",
                )
            )
        elif matching_role in role_views and selected.from_ not in role_views[matching_role].refs:
            issues.append(
                PlanValidationIssue(
                    code="MISSING_COLUMN",
                    unit_id=unit.unit_id,
                    field="select",
                    message=f"Qualified column '{selected.from_}' does not exist",
                )
            )
        elif unit.how in {"semi", "anti"} and matching_role != "left":
            issues.append(
                PlanValidationIssue(
                    code="JOIN_SELECT_SIDE_MISMATCH",
                    unit_id=unit.unit_id,
                    field="select",
                    message=(
                        f"{unit.how} joins may select columns only from the left Snapshot"
                    ),
                )
            )

    input_snapshot_names = [item.snapshot for item in unit.inputs]
    _require_planned_snapshot_dependency(
        unit,
        input_snapshot_names,
        dependencies,
        planned_producers,
        issues,
    )
    _validate_new_snapshot_name(
        unit.output_snapshot,
        unit.unit_id,
        original_snapshot_names,
        views,
        issues,
        allow_reexecution=allow_reexecution,
    )
    output_refs = {
        f"{unit.output_snapshot}.{selected.as_}": f"planned:unit_{unit.unit_id}:{selected.as_}"
        for selected in unit.select
    }
    views[unit.output_snapshot] = _SnapshotView(
        name=unit.output_snapshot,
        refs=output_refs,
        producer_unit_id=unit.unit_id,
    )
    planned_producers[unit.output_snapshot] = unit.unit_id


def _validate_terminal(
    unit: TerminalUnit,
    unit_by_id: dict[int, PlanUnitValue],
    dependencies: dict[int, set[int]],
    views: dict[str, _SnapshotView],
    planned_producers: dict[str, int],
    issues: list[PlanValidationIssue],
) -> None:
    view = _require_snapshot(unit.input_snapshot, unit.unit_id, "input_snapshot", views, issues)
    if view is None:
        return
    _require_refs(unit.input_columns, view, unit.unit_id, "input_columns", issues)
    _require_planned_snapshot_dependency(
        unit,
        [unit.input_snapshot],
        dependencies,
        planned_producers,
        issues,
    )


def _require_snapshot(
    name: str,
    unit_id: int,
    field: str,
    views: dict[str, _SnapshotView],
    issues: list[PlanValidationIssue],
) -> _SnapshotView | None:
    view = views.get(name)
    if view is None:
        issues.append(
            PlanValidationIssue(
                code="MISSING_SNAPSHOT",
                unit_id=unit_id,
                field=field,
                message=f"Snapshot '{name}' does not exist",
            )
        )
    return view


def _require_refs(
    refs: list[str],
    view: _SnapshotView,
    unit_id: int,
    field: str,
    issues: list[PlanValidationIssue],
) -> None:
    for ref in refs:
        if ref not in view.refs:
            issues.append(
                PlanValidationIssue(
                    code="MISSING_COLUMN",
                    unit_id=unit_id,
                    field=field,
                    message=f"Qualified column '{ref}' does not exist in Snapshot '{view.name}'",
                )
            )


def _validate_new_snapshot_name(
    name: str,
    unit_id: int,
    original_snapshot_names: set[str],
    views: dict[str, _SnapshotView],
    issues: list[PlanValidationIssue],
    *,
    allow_reexecution: bool = False,
) -> None:
    if not _SNAPSHOT_NAME_PATTERN.fullmatch(name):
        issues.append(
            PlanValidationIssue(
                code="INVALID_OUTPUT_SNAPSHOT",
                unit_id=unit_id,
                field="output_snapshot",
                message=f"Output Snapshot '{name}' is not a valid ASCII identifier",
            )
        )
    existing_view = views.get(name)
    same_producer = (
        existing_view is not None
        and existing_view.producer_unit_id == unit_id
    )
    if (name in original_snapshot_names or name in views) and not (
        allow_reexecution and same_producer
    ):
        issues.append(
            PlanValidationIssue(
                code="OUTPUT_SNAPSHOT_EXISTS",
                unit_id=unit_id,
                field="output_snapshot",
                message=f"Output Snapshot '{name}' is already in use",
            )
        )


def _require_join_ref(
    ref: str,
    role: str,
    by_role: Mapping[Any, Any],
    role_views: dict[str, _SnapshotView],
    unit_id: int,
    issues: list[PlanValidationIssue],
) -> None:
    matching_role = _role_for_snapshot(ref, by_role)
    if matching_role != role:
        issues.append(
            PlanValidationIssue(
                code="JOIN_KEY_SNAPSHOT_MISMATCH",
                unit_id=unit_id,
                field="keys",
                message=f"Join key '{ref}' is not from the declared {role} Snapshot",
            )
        )
        return
    view = role_views.get(role)
    if view is not None and ref not in view.refs:
        issues.append(
            PlanValidationIssue(
                code="MISSING_COLUMN",
                unit_id=unit_id,
                field="keys",
                message=f"Qualified join key '{ref}' does not exist",
            )
        )


def _role_for_snapshot(ref: str, by_role: Mapping[Any, Any]) -> str | None:
    for role, item in by_role.items():
        if ref.startswith(f"{item.snapshot}."):
            return cast(str, role)
    return None


def _require_planned_snapshot_dependency(
    unit: PlanUnitValue,
    input_snapshots: list[str],
    dependencies: dict[int, set[int]],
    planned_producers: dict[str, int],
    issues: list[PlanValidationIssue],
) -> None:
    direct_dependencies = dependencies.get(unit.unit_id, set())
    for snapshot in input_snapshots:
        producer = planned_producers.get(snapshot)
        if producer is None or producer in direct_dependencies:
            continue
        issues.append(
            PlanValidationIssue(
                code="MISSING_SNAPSHOT_DEPENDENCY",
                unit_id=unit.unit_id,
                field="depends_on",
                message=(
                    f"Unit {unit.unit_id} reads Snapshot '{snapshot}', which is produced "
                    f"by unit {producer}; declare that dependency explicitly"
                ),
            )
        )


def _validate_same_snapshot_writer_chains(
    units: list[PlanUnitValue],
    topological_ids: list[int],
    dependencies: dict[int, set[int]],
    issues: list[PlanValidationIssue],
) -> None:
    writers: dict[str, list[int]] = defaultdict(list)
    for unit in units:
        if isinstance(unit, DeriveColumnUnit):
            writers[unit.input_snapshot].append(unit.unit_id)

    position = {unit_id: index for index, unit_id in enumerate(topological_ids)}
    for snapshot, writer_ids in writers.items():
        ordered = sorted(writer_ids, key=lambda unit_id: position.get(unit_id, unit_id))
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous not in dependencies.get(current, set()):
                issues.append(
                    PlanValidationIssue(
                        code="DERIVE_WRITERS_NOT_CHAINED",
                        unit_id=current,
                        field="depends_on",
                        message=(
                            f"Derive writers for Snapshot '{snapshot}' must form one explicit "
                            f"dependency chain; unit {current} must depend on unit {previous}"
                        ),
                    )
                )


def _replace_snapshot_prefix(ref: str, source: str, target: str) -> str:
    prefix = f"{source}."
    return f"{target}.{ref[len(prefix):]}" if ref.startswith(prefix) else ref


def _deduplicate_issues(
    issues: list[PlanValidationIssue],
) -> list[PlanValidationIssue]:
    seen: set[tuple[str, int | None, str | None, str]] = set()
    result: list[PlanValidationIssue] = []
    for issue in issues:
        key = (issue.code, issue.unit_id, issue.field, issue.message)
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result
