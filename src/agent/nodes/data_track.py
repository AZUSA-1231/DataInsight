from __future__ import annotations

import json
import logging
import os

from src.agent.state import AgentState, ColumnProfile, DataProfile
from src.sandbox.executor import SandboxResult, run_script

logger = logging.getLogger(__name__)

_INSPECTION_SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "..", "sandbox", "inspection_script.py"
)


def _parse_data_profile(inspection_json: str) -> DataProfile:
    """Parse inspection script output into a structured DataProfile."""
    raw = json.loads(inspection_json)

    columns = [
        ColumnProfile(
            name=col["name"],
            dtype=col["dtype"],
            null_count=col["null_count"],
            null_pct=col["null_pct"],
            unique_count=col["unique_count"],
            unique_pct=col["unique_pct"],
        )
        for col in raw["columns"]
    ]

    return DataProfile(
        file_path=raw["file_path"],
        shape=(raw["shape"]["rows"], raw["shape"]["cols"]),
        columns=columns,
        statistics=raw.get("statistics", {}),
        head_sample=raw.get("head", []),
        encoding=raw.get("encoding"),
    )


def data_track_node(state: AgentState) -> dict[str, object]:
    """Stage 1 — Data Track: deterministic inspection → structured profile
    and unified column list extraction.

    Reads: state.file_path
    Writes: state.data_profile, state.unified_columns
    """
    file_path = state.file_path
    logger.info("Data Track: inspecting %s", file_path)

    result: SandboxResult = run_script(_INSPECTION_SCRIPT, [file_path])

    if result.exit_code != 0:
        logger.error("Inspection script failed: %s", result.stderr)
        return {"error": f"Inspection script error: {result.stderr}"}

    try:
        data_profile = _parse_data_profile(result.stdout)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error("Failed to parse inspection output: %s", e)
        return {"error": f"Failed to parse inspection output: {e}"}

    unified_columns = [col.name for col in data_profile.columns]
    logger.info(
        "Data Track: profile parsed — %d columns, shape=%s; unified_columns=%s",
        len(data_profile.columns),
        data_profile.shape,
        unified_columns,
    )

    return {"data_profile": data_profile, "unified_columns": unified_columns}
