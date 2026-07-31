from __future__ import annotations

import json
import re
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from src.agent.state import AgentState

_SESSION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class SessionStore:
    """Session storage with an in-memory cache and JSON persistence."""

    def __init__(self, base_dir: str | Path = "data/sessions") -> None:
        self._sessions: dict[str, AgentState] = {}
        self._base_dir = Path(base_dir)

    def create(self, user_requirement: str = "") -> str:
        """Create a new session, return its UUID."""
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = AgentState(
            file_path="",
            user_requirement=user_requirement,
        )
        self.save(session_id)
        return session_id

    def get(self, session_id: str) -> AgentState | None:
        """Return cached state or restore it from disk."""
        state = self._sessions.get(session_id)
        if state is not None:
            return state
        try:
            return self.load(session_id)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            return None

    def update(self, session_id: str, patch: dict[str, object]) -> AgentState:
        """Apply a partial update to the session state (immutable pattern)."""
        state = self._sessions[session_id]
        updated = state.model_copy(update=patch)
        self._sessions[session_id] = updated
        self.save(session_id)
        return self._sessions[session_id]

    def save(self, session_id: str) -> Path:
        """Atomically persist one session and return its state file path."""
        state = self._sessions[session_id]
        persisted_at = datetime.now(UTC).isoformat()
        state = state.model_copy(update={"persisted_at": persisted_at})
        self._sessions[session_id] = state

        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        state_path = session_dir / "state.json"
        temp_path = session_dir / "state.json.tmp"

        payload = _strip_runtime_values(state.model_dump(mode="python"))
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        temp_path.replace(state_path)
        return state_path

    def load(self, session_id: str) -> AgentState:
        """Load a persisted session into the in-memory cache."""
        state_path = self._session_dir(session_id) / "state.json"
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        state = AgentState.model_validate(payload)
        self._sessions[session_id] = state
        return state

    def delete(self, session_id: str) -> bool:
        """Remove a session. Returns False if session did not exist."""
        state_path = self._session_dir_or_none(session_id)
        existed = session_id in self._sessions or (
            state_path is not None and (state_path / "state.json").exists()
        )
        self._sessions.pop(session_id, None)
        if state_path is not None:
            persisted = state_path / "state.json"
            temp = state_path / "state.json.tmp"
            persisted.unlink(missing_ok=True)
            temp.unlink(missing_ok=True)
            with suppress(OSError):
                state_path.rmdir()
        return existed

    def exists(self, session_id: str) -> bool:
        """Check whether a session exists."""
        return self.get(session_id) is not None

    def _session_dir(self, session_id: str) -> Path:
        if not _SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError("Invalid session ID")
        return self._base_dir / session_id

    def _session_dir_or_none(self, session_id: str) -> Path | None:
        try:
            return self._session_dir(session_id)
        except ValueError:
            return None


def _strip_runtime_values(value: Any) -> Any:
    """Remove executor-only values before serializing durable session state."""
    if isinstance(value, dict):
        return {
            str(key): _strip_runtime_values(item)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    if isinstance(value, list | tuple):
        return [_strip_runtime_values(item) for item in value]
    return value


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "item") and callable(value.item):
        return value.item()
    raise TypeError(f"Unsupported session value: {type(value).__name__}")
