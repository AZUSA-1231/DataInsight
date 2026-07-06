from __future__ import annotations

import uuid

from src.agent.state import AgentState


class SessionStore:
    """In-memory session storage. Single-user desktop app — no locking needed."""

    def __init__(self) -> None:
        self._sessions: dict[str, AgentState] = {}

    def create(self, user_requirement: str = "") -> str:
        """Create a new session, return its UUID."""
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = AgentState(
            file_path="",
            user_requirement=user_requirement,
        )
        return session_id

    def get(self, session_id: str) -> AgentState | None:
        """Return the session state, or None if unknown."""
        return self._sessions.get(session_id)

    def update(self, session_id: str, patch: dict[str, object]) -> AgentState:
        """Apply a partial update to the session state (immutable pattern)."""
        state = self._sessions[session_id]
        updated = state.model_copy(update=patch)
        self._sessions[session_id] = updated
        return updated

    def delete(self, session_id: str) -> bool:
        """Remove a session. Returns False if session did not exist."""
        existed = session_id in self._sessions
        self._sessions.pop(session_id, None)
        return existed

    def exists(self, session_id: str) -> bool:
        """Check whether a session exists."""
        return session_id in self._sessions
