"""DAG execution engine for PlanUnit orchestration.

Pure functions for topological sort, column validation, Parquet checkpoint
management, and level-parallel execution. No LLM or sandbox dependencies —
testable without mocking.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd

from src.agent.state import AgentState, PlanUnit

logger = logging.getLogger(__name__)

_MAX_WORKERS = 3


class DagCycleError(Exception):
    """Raised when a cycle is detected in the PlanUnit dependency graph."""

    def __init__(self, unit_ids: set[int]) -> None:
        self.unit_ids = unit_ids
        super().__init__(
            f"Cycle detected involving units: {sorted(unit_ids)}"
        )


# ── topological sort ─────────────────────────────────────────────────────────


def topological_levels(units: list[PlanUnit]) -> list[list[PlanUnit]]:
    """Group units into execution levels using Kahn's algorithm.

    Units within the same level have no dependencies on each other
    and can run in parallel. Levels run sequentially.

    Returns:
        List of levels, each level is a list of PlanUnit.

    Raises:
        DagCycleError: if a cycle, self-loop, or missing dependency is detected.
    """
    if not units:
        return []

    unit_map: dict[int, PlanUnit] = {u.unit_id: u for u in units}
    in_degree: dict[int, int] = {u.unit_id: 0 for u in units}
    dependents: dict[int, list[int]] = {u.unit_id: [] for u in units}

    for u in units:
        for dep_id in u.depends_on:
            if dep_id not in unit_map:
                raise DagCycleError({u.unit_id, dep_id})
            if dep_id == u.unit_id:
                raise DagCycleError({u.unit_id})
            in_degree[u.unit_id] += 1
            dependents[dep_id].append(u.unit_id)

    queue: list[int] = [uid for uid, deg in in_degree.items() if deg == 0]
    levels: list[list[PlanUnit]] = []
    processed = 0

    while queue:
        level = [unit_map[uid] for uid in queue]
        levels.append(level)
        processed += len(queue)

        next_queue: list[int] = []
        for uid in queue:
            for dependent_id in dependents[uid]:
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    next_queue.append(dependent_id)
        queue = next_queue

    if processed != len(units):
        stuck = {uid for uid, deg in in_degree.items() if deg > 0}
        raise DagCycleError(stuck)

    return levels


# ── column validation ────────────────────────────────────────────────────────


def validate_columns(
    required: list[str], available: set[str],
) -> tuple[list[str], list[str]]:
    """Check which required columns are missing from available.

    Returns:
        (missing, found) — columns required but not available,
        and columns that are available. Case-sensitive exact match.
    """
    if not required:
        return ([], [])

    missing = [c for c in required if c not in available]
    found = [c for c in required if c in available]
    return (missing, found)


# ── Parquet checkpoint helpers ──────────────────────────────────────────────


def _session_dir(parent_output_dir: str) -> str:
    """Ensure and return the session checkpoint directory."""
    path = os.path.join(parent_output_dir, "checkpoints")
    os.makedirs(path, exist_ok=True)
    return path


def _snapshots_dir(parent_output_dir: str) -> str:
    """Ensure and return the snapshots directory."""
    path = os.path.join(parent_output_dir, "checkpoints", "snapshots")
    os.makedirs(path, exist_ok=True)
    return path


def _checkpoint_path(parent_output_dir: str, branch: str, level: int) -> str:
    """Build a checkpoint Parquet path for a branch and level.

    ``branch`` is "wide" for the main table, or the snapshot name.
    """
    if branch == "wide":
        return os.path.join(_session_dir(parent_output_dir), f"wide_l{level}.parquet")
    return os.path.join(
        _snapshots_dir(parent_output_dir), f"{branch}_l{level}.parquet"
    )


def save_checkpoint(df: pd.DataFrame, path: str) -> None:
    """Save a DataFrame as a Parquet checkpoint."""
    df.to_parquet(path, index=False)
    logger.info("Checkpoint saved: %s (%d rows, %d cols)", path, len(df), len(df.columns))


def load_checkpoint(path: str) -> pd.DataFrame:
    """Load a DataFrame from a Parquet checkpoint."""
    df = pd.read_parquet(path)
    logger.info("Checkpoint loaded: %s (%d rows, %d cols)", path, len(df), len(df.columns))
    return df


def _output_csv_path(unit_output_dir: str) -> str:
    return os.path.join(unit_output_dir, "output.csv")


def _upstream_ids(unit: PlanUnit, units: list[PlanUnit]) -> set[int]:
    """Return all unit IDs that ``unit`` transitively depends on."""
    result: set[int] = set()
    queue = list(unit.depends_on)
    while queue:
        dep_id = queue.pop(0)
        if dep_id in result:
            continue
        result.add(dep_id)
        dep_unit = next((u for u in units if u.unit_id == dep_id), None)
        if dep_unit:
            queue.extend(dep_unit.depends_on)
    return result


# ── DAG executor ─────────────────────────────────────────────────────────────


def execute_dag(
    state: AgentState,
    parent_output_dir: str,
    prev_unit_results: dict[int, dict[str, Any]],
    execute_unit_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Execute PlanUnits in DAG order with Parquet checkpoint chaining.

    Each successful non-Terminal unit produces a Parquet checkpoint that
    downstream units read as input. This replaces the old CSV-concatenation
    model and supports branching via FilterUnit snapshots.

    Checkpoint layout::

        {parent_output_dir}/checkpoints/
        ├── wide_l0.parquet        # Original data (loaded on demand)
        ├── wide_l1.parquet        # After level-1 main-table transforms
        ├── wide_l2.parquet        # After level-2 main-table transforms
        └── snapshots/
            ├── recent_l0.parquet  # FilterUnit output
            └── recent_l1.parquet  # Transform on snapshot "recent"

    Args:
        state: Current AgentState.
        parent_output_dir: Root output directory for all units.
        prev_unit_results: Restored per-unit state from previous partial runs.
        execute_unit_fn: Callable with signature
            (unit, input_data_path, output_dir, retry_state) -> dict.

    Returns:
        {unit_results, status, output_dir}
    """
    plan = state.plan
    if not plan:
        return {
            "unit_results": [],
            "status": "failed",
            "output_dir": parent_output_dir,
            "dag_error": "No plan available",
        }

    units = plan.units

    try:
        levels = topological_levels(units)
    except DagCycleError as e:
        logger.error("DAG: cycle detected — %s", e)
        return {
            "unit_results": [],
            "status": "failed",
            "output_dir": parent_output_dir,
            "dag_error": str(e),
        }

    logger.info(
        "DAG: %d unit(s) across %d level(s)", len(units), len(levels),
    )
    for i, level in enumerate(levels):
        logger.info(
            "DAG level %d: units %s", i, [u.unit_id for u in level],
        )

    unit_results: list[dict[str, Any]] = []
    errors: list[str] = []

    original_columns = set(state.unified_columns)
    data_path = state.file_path

    # ── checkpoint tracking ──
    # Main table level: 0 = original data, N = after N transforms
    main_level = 0
    # Snapshot levels: snapshot_name → current level (0 = filter output)
    snapshot_levels: dict[str, int] = {}

    for _level_idx, level in enumerate(levels):
        level_tasks: list[dict[str, Any]] = []

        for unit in level:
            unit_output_dir = os.path.join(
                parent_output_dir, f"unit_{unit.unit_id}"
            )
            os.makedirs(unit_output_dir, exist_ok=True)

            # ── resolve input path ──
            input_path: str
            available: set[str]

            if unit.input_from is not None:
                # Read from a named snapshot
                snap_name = unit.input_from
                snap_lvl = snapshot_levels.get(snap_name)
                if snap_lvl is not None:
                    cp_path = _checkpoint_path(parent_output_dir, snap_name, snap_lvl)
                    if os.path.exists(cp_path):
                        input_path = cp_path
                    else:
                        logger.warning(
                            "DAG: snapshot '%s' l%d checkpoint not found, "
                            "falling back to original data for unit [%d]",
                            snap_name, snap_lvl, unit.unit_id,
                        )
                        input_path = data_path
                else:
                    logger.warning(
                        "DAG: snapshot '%s' not yet created, "
                        "falling back to original data for unit [%d]",
                        snap_name, unit.unit_id,
                    )
                    input_path = data_path
                available = set(original_columns)
                for dep_id in _upstream_ids(unit, units):
                    dep_unit = next((u for u in units if u.unit_id == dep_id), None)
                    if dep_unit:
                        available |= set(dep_unit.output_columns)
            elif unit.depends_on:
                # Read from the latest main-table checkpoint
                if main_level > 0:
                    cp_path = _checkpoint_path(parent_output_dir, "wide", main_level)
                    input_path = cp_path if os.path.exists(cp_path) else data_path
                else:
                    input_path = data_path
                available = set(original_columns)
                for dep_id in _upstream_ids(unit, units):
                    dep_unit = next((u for u in units if u.unit_id == dep_id), None)
                    if dep_unit:
                        available |= set(dep_unit.output_columns)
            else:
                # Root unit: read original data file
                input_path = data_path
                available = set(original_columns)

            # ── column validation ──
            cols_to_check = (
                unit.input_columns if unit.input_columns
                else unit.related_fields
            )
            missing, _found = validate_columns(cols_to_check, available)

            if missing and unit.input_columns:
                msg = f"Missing required columns: {missing}"
                logger.error(
                    "DAG: unit [%d] column validation failed: %s",
                    unit.unit_id, msg,
                )
                unit_results.append({
                    "unit_id": unit.unit_id,
                    "status": "failed",
                    "parsed_output": None,
                    "charts": [],
                    "insights": [],
                    "statistics": {},
                    "error": msg,
                    "retry_count": 0,
                    "scripts": [],
                    "stdout": "",
                    "output_dir": unit_output_dir,
                })
                errors.append(f"Unit {unit.unit_id}: {msg}")
                continue

            if missing and not unit.input_columns:
                logger.warning(
                    "DAG: unit [%d] related_fields not in available columns: %s "
                    "(non-fatal — columns may exist in data but not in profile)",
                    unit.unit_id, missing,
                )

            level_tasks.append({
                "unit": unit,
                "input_path": input_path,
                "output_dir": unit_output_dir,
            })

        # ── execute level in parallel ──
        if level_tasks:
            max_workers = min(len(level_tasks), _MAX_WORKERS)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures: dict[Any, int] = {}
                for task in level_tasks:
                    unit = task["unit"]
                    prev = prev_unit_results.get(unit.unit_id)
                    future = executor.submit(
                        execute_unit_fn,
                        unit,
                        task["input_path"],
                        task["output_dir"],
                        prev,
                    )
                    futures[future] = unit.unit_id

                for future in as_completed(futures):
                    unit_id = futures[future]
                    try:
                        result = future.result()
                        unit_results.append(result)

                        if result["status"] == "success":
                            unit_obj = next(
                                u for u in units if u.unit_id == unit_id
                            )
                            _save_unit_checkpoint(
                                unit_obj, result, parent_output_dir,
                                main_level, snapshot_levels,
                            )
                            # Bump main_level for main-table transforms
                            if (
                                unit_obj.unit_type == "transform"
                                and unit_obj.input_from is None
                            ):
                                main_level += 1
                                logger.info(
                                    "DAG: main table advanced to level %d", main_level,
                                )
                            elif (
                                unit_obj.unit_type == "transform"
                                and unit_obj.input_from is not None
                            ):
                                snap = unit_obj.input_from
                                cur = snapshot_levels.get(snap, 0)
                                snapshot_levels[snap] = cur + 1
                                logger.info(
                                    "DAG: snapshot '%s' advanced to level %d",
                                    snap, cur + 1,
                                )
                        else:
                            errors.append(
                                f"Unit {unit_id}: {result.get('error', 'unknown')}"
                            )
                    except Exception as e:
                        logger.error(
                            "DAG: unit [%d] executor failed: %s", unit_id, e,
                        )
                        unit_results.append({
                            "unit_id": unit_id,
                            "status": "failed",
                            "parsed_output": None,
                            "charts": [],
                            "insights": [],
                            "statistics": {},
                            "error": f"Executor error: {e}",
                            "retry_count": 0,
                            "scripts": [],
                            "stdout": "",
                            "output_dir": os.path.join(
                                parent_output_dir, f"unit_{unit_id}",
                            ),
                        })
                        errors.append(f"Unit {unit_id}: executor error: {e}")

    unit_results.sort(key=lambda r: r["unit_id"])

    all_success = all(r["status"] == "success" for r in unit_results)
    status = "complete" if all_success else "partial"

    logger.info(
        "DAG: %d/%d units succeeded (status=%s)",
        sum(1 for r in unit_results if r["status"] == "success"),
        len(unit_results),
        status,
    )

    return {
        "unit_results": unit_results,
        "status": status,
        "output_dir": parent_output_dir,
    }


def _save_unit_checkpoint(
    unit: PlanUnit,
    result: dict[str, Any],
    parent_output_dir: str,
    main_level: int,
    snapshot_levels: dict[str, int],
) -> None:
    """Save a Parquet checkpoint for a successfully executed unit.

    Transform: appends new columns → saves next-level checkpoint.
    Filter: saves a named snapshot at level 0.
    Terminal: no checkpoint (only produces artifacts).
    """
    utype = unit.unit_type
    if utype == "terminal":
        return  # Terminal units produce artifacts only, no data checkpoint

    # ── resolve DataFrame ───────────────────────────────────────────────
    df: pd.DataFrame | None = result.get("_result_df")

    if df is None:
        unit_output_dir = result.get("output_dir", "")
        output_csv = _output_csv_path(unit_output_dir)
        if not os.path.exists(output_csv):
            logger.debug(
                "DAG: unit [%d] produced no output.csv — skipping checkpoint",
                unit.unit_id,
            )
            return
        try:
            df = pd.read_csv(output_csv)
        except Exception as e:
            logger.warning(
                "DAG: unit [%d] output.csv read failed — skipping checkpoint: %s",
                unit.unit_id, e,
            )
            return

    # ── contract validation ─────────────────────────────────────────────
    input_rows = result.get("_input_row_count")
    if utype == "transform" and input_rows is not None and len(df) != input_rows:
        logger.error(
            "DAG: unit [%d] CONTRACT VIOLATION — Transform row count "
            "changed: %d -> %d. Checkpoint saved but downstream data "
            "may be corrupt.",
            unit.unit_id, input_rows, len(df),
        )

    for col in unit.output_columns:
        if col not in df.columns:
            logger.warning(
                "DAG: unit [%d] declared output_column '%s' not found "
                "in result.",
                unit.unit_id, col,
            )

    # ── save checkpoint ─────────────────────────────────────────────────
    if utype == "transform":
        if unit.input_from is not None:
            snap_name = unit.input_from
            cur_lvl = snapshot_levels.get(snap_name, 0)
            new_lvl = cur_lvl + 1
            cp_path = _checkpoint_path(parent_output_dir, snap_name, new_lvl)
            save_checkpoint(df, cp_path)
        else:
            new_lvl = main_level + 1
            cp_path = _checkpoint_path(parent_output_dir, "wide", new_lvl)
            save_checkpoint(df, cp_path)

    elif utype == "filter":
        snap_name = result.get("snapshot_name") or f"snapshot_{unit.unit_id}"
        snapshot_levels[snap_name] = 0
        cp_path = _checkpoint_path(parent_output_dir, snap_name, 0)
        save_checkpoint(df, cp_path)


# ── rerun helpers ────────────────────────────────────────────────────────────


def transitive_dependents(unit_id: int, units: list[PlanUnit]) -> list[int]:
    """Return all unit IDs that transitively depend on ``unit_id``.

    Follows ``depends_on`` edges forward. Results are sorted topologically
    (by unit_id ascending, which respects topological order since units
    are indexed in execution order).
    """
    # Build reverse index: unit_id → list of units that depend on it
    dependents_map: dict[int, list[int]] = {u.unit_id: [] for u in units}
    for u in units:
        for dep_id in u.depends_on:
            if dep_id in dependents_map:
                dependents_map[dep_id].append(u.unit_id)

    # BFS from unit_id
    visited: set[int] = set()
    queue = [unit_id]
    while queue:
        current = queue.pop(0)
        for downstream_id in dependents_map.get(current, []):
            if downstream_id not in visited:
                visited.add(downstream_id)
                queue.append(downstream_id)

    return sorted(visited)


def resolve_rerun_input(
    unit: PlanUnit, parent_output_dir: str
) -> str | None:
    """Find the best input checkpoint for re-running a single unit.

    Scans the checkpoint directory for the unit's branch:
    - ``input_from is None`` → main wide table (``wide_l*.parquet``)
    - ``input_from = "name"`` → snapshot branch (``{name}_l*.parquet``)

    Returns the path to the highest-level checkpoint, or ``None`` if no
    checkpoint exists (caller should use the original data file).
    """
    import glob as _glob

    branch = unit.input_from or "wide"
    if branch == "wide":
        pattern = os.path.join(
            parent_output_dir, "checkpoints", "wide_l*.parquet"
        )
    else:
        pattern = os.path.join(
            parent_output_dir, "checkpoints", "snapshots", f"{branch}_l*.parquet"
        )

    matches = _glob.glob(pattern)
    if not matches:
        logger.debug(
            "resolve_rerun_input: no checkpoint for branch '%s', "
            "unit [%d] will use original data",
            branch, unit.unit_id,
        )
        return None

    # Pick the highest level (last sorted alphabetically = highest number)
    best = sorted(matches)[-1]
    logger.info(
        "resolve_rerun_input: unit [%d] branch='%s' → %s",
        unit.unit_id, branch, best,
    )
    return best
