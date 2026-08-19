from __future__ import annotations

import json
import re
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Literal, TypedDict, cast

from src.agent.state import AgentChatMessage, AgentChatThread, AgentState

_SESSION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
DEFAULT_PROJECT_TITLE = "Untitled project"
DEFAULT_THREAD_TITLE = "New chat"
IMPORTED_THREAD_TITLE = "Imported chat"
MAX_PROJECT_TITLE_CHARS = 120
MAX_THREAD_TITLE_CHARS = 120


class ProjectSummary(TypedDict):
    project_id: str
    title: str
    created_at: str | None
    persisted_at: str | None
    source_count: int
    unit_count: int
    has_results: bool
    has_report: bool
    agent_chat_count: int
    status: str | None


class IncompatibleSessionError(RuntimeError):
    """Raised when a persisted Session is from an unsupported schema version."""

    def __init__(self, session_id: str, version: object) -> None:
        self.session_id = session_id
        self.version = version
        super().__init__(
            f"Session {session_id} uses incompatible schema version {version!r}; "
            "Cycle 5 requires schema version 2"
        )


class AgentThreadNotFoundError(LookupError):
    """Raised when a Thread is not owned by the addressed Project."""

    def __init__(self, session_id: str, thread_id: str) -> None:
        self.session_id = session_id
        self.thread_id = thread_id
        super().__init__(f"Agent Thread {thread_id} was not found in Project {session_id}")


def utc_now() -> str:
    """Return one stable, JSON-safe timestamp representation."""

    return datetime.now(UTC).isoformat()


def normalize_project_title(value: str | None) -> str:
    """Trim and validate a user-facing Project title."""

    if value is None:
        return DEFAULT_PROJECT_TITLE
    title = value.strip()
    if not title:
        raise ValueError("Project title must not be blank")
    if len(title) > MAX_PROJECT_TITLE_CHARS:
        raise ValueError(
            f"Project title must be at most {MAX_PROJECT_TITLE_CHARS} characters"
        )
    return title


def normalize_thread_title(value: str | None) -> str:
    """Trim and validate an optional Agent Thread title."""

    if value is None:
        return DEFAULT_THREAD_TITLE
    title = value.strip()
    if not title:
        raise ValueError("Agent Thread title must not be blank")
    if len(title) > MAX_THREAD_TITLE_CHARS:
        raise ValueError(
            f"Agent Thread title must be at most {MAX_THREAD_TITLE_CHARS} characters"
        )
    return title


def _new_thread(title: str, timestamp: str | None = None) -> AgentChatThread:
    created_at = timestamp or utc_now()
    return AgentChatThread(
        thread_id=uuid.uuid4().hex,
        title=normalize_thread_title(title),
        created_at=created_at,
        updated_at=created_at,
    )


def build_project_summary(
    project_id: str,
    state: AgentState,
    *,
    status: str | None = None,
) -> ProjectSummary:
    """Build the safe Project projection used by history and header clients."""

    thread_count = len(state.agent_threads)
    # Legacy state is not migrated while listing, but its eventual default
    # Thread is still useful for a truthful history count.
    if thread_count == 0 and state.dialogue_history:
        thread_count = 1
    return {
        "project_id": project_id,
        "title": state.project_title or DEFAULT_PROJECT_TITLE,
        "created_at": state.created_at,
        "persisted_at": state.persisted_at,
        "source_count": len(state.data_sources),
        "unit_count": len(state.plan.units) if state.plan is not None else 0,
        "has_results": state.analysis_result is not None,
        "has_report": state.final_report is not None,
        "agent_chat_count": thread_count,
        "status": status or ("error" if state.error else None),
    }


class SessionStore:
    """Session storage with an in-memory cache and JSON persistence."""

    def __init__(self, base_dir: str | Path = "data/sessions") -> None:
        self._sessions: dict[str, AgentState] = {}
        self._base_dir = Path(base_dir)
        self._lock = RLock()

    def create(
        self,
        user_requirement: str = "",
        *,
        title: str | None = None,
    ) -> str:
        """Create a new Project with one empty default Agent Thread."""

        with self._lock:
            session_id = uuid.uuid4().hex
            timestamp = utc_now()
            self._sessions[session_id] = AgentState(
                file_path="",
                user_requirement=user_requirement,
                project_title=normalize_project_title(title),
                created_at=timestamp,
                agent_threads=[_new_thread(DEFAULT_THREAD_TITLE, timestamp)],
            )
            self.save(session_id)
            return session_id

    def get(self, session_id: str) -> AgentState | None:
        """Return cached state or restore it from disk."""

        with self._lock:
            state = self._sessions.get(session_id)
            if state is not None:
                return state
            try:
                return self.load(session_id)
            except IncompatibleSessionError:
                raise
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                return None

    def update(self, session_id: str, patch: dict[str, object]) -> AgentState:
        """Apply a partial update to the session state (immutable pattern)."""

        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                state = self.get(session_id)
            if state is None:
                raise KeyError(f"Session not found: {session_id}")
            updated = state.model_copy(update=patch)
            self._sessions[session_id] = updated
            self.save(session_id)
            return self._sessions[session_id]

    def save(self, session_id: str) -> Path:
        """Atomically persist one session and return its state file path."""

        with self._lock:
            state = self._sessions[session_id]
            persisted_at = utc_now()
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

        with self._lock:
            state_path = self._session_dir(session_id) / "state.json"
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Session state must be a JSON object")
            if payload.get("schema_version") != 2:
                raise IncompatibleSessionError(session_id, payload.get("schema_version"))
            state = AgentState.model_validate(payload)
            self._sessions[session_id] = state
            return state

    def list_summaries(self) -> list[ProjectSummary]:
        """List safe Project summaries, newest first, without mutating files."""

        with self._lock:
            if not self._base_dir.exists():
                return []

            summaries: list[ProjectSummary] = []
            for session_dir in self._base_dir.iterdir():
                if not session_dir.is_dir() or not _SESSION_ID_PATTERN.fullmatch(
                    session_dir.name
                ):
                    continue
                state_path = session_dir / "state.json"
                if not state_path.is_file():
                    continue
                try:
                    payload = json.loads(state_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    # A malformed file is not a reason to delete or rewrite a
                    # user's Project. It is omitted from the safe list.
                    continue
                if not isinstance(payload, dict):
                    continue

                if payload.get("schema_version") != 2:
                    summaries.append(
                        {
                            "project_id": session_dir.name,
                            "title": "Unavailable project",
                            "created_at": None,
                            "persisted_at": None,
                            "source_count": 0,
                            "unit_count": 0,
                            "has_results": False,
                            "has_report": False,
                            "agent_chat_count": 0,
                            "status": "incompatible_schema",
                        }
                    )
                    continue

                try:
                    state = AgentState.model_validate(payload)
                except (TypeError, ValueError):
                    continue
                self._sessions[session_dir.name] = state
                summaries.append(build_project_summary(session_dir.name, state))

            return sorted(
                summaries,
                key=lambda item: (
                    str(item.get("persisted_at") or item.get("created_at") or ""),
                    str(item.get("project_id") or ""),
                ),
                reverse=True,
            )

    def rename(self, session_id: str, title: str) -> AgentState:
        """Persist an explicit Project title change."""

        return self.update(session_id, {"project_title": normalize_project_title(title)})

    def ensure_default_thread(self, session_id: str) -> AgentChatThread:
        """Migrate legacy history once and return the Project's default Thread."""

        with self._lock:
            state = self._require_state(session_id)
            state = self._ensure_threads_locked(session_id, state)
            return state.agent_threads[0].model_copy(deep=True)

    def list_agent_threads(self, session_id: str) -> list[AgentChatThread]:
        """Return metadata-bearing Thread records owned by one Project."""

        with self._lock:
            state = self._require_state(session_id)
            state = self._ensure_threads_locked(session_id, state)
            return [thread.model_copy(deep=True) for thread in state.agent_threads]

    def create_agent_thread(
        self,
        session_id: str,
        *,
        title: str | None = None,
    ) -> AgentChatThread:
        """Create and persist one empty Thread inside a Project."""

        with self._lock:
            state = self._require_state(session_id)
            state = self._ensure_threads_locked(session_id, state)
            thread = _new_thread(normalize_thread_title(title))
            threads = [*state.agent_threads, thread]
            self.update(session_id, {"agent_threads": threads})
            return thread.model_copy(deep=True)

    def get_agent_thread(
        self,
        session_id: str,
        thread_id: str,
    ) -> AgentChatThread | None:
        """Resolve a Thread only within the addressed Project."""

        with self._lock:
            state = self._require_state(session_id)
            state = self._ensure_threads_locked(session_id, state)
            for thread in state.agent_threads:
                if thread.thread_id == thread_id:
                    return thread.model_copy(deep=True)
            return None

    def append_agent_turn(
        self,
        session_id: str,
        thread_id: str,
        user_message: str,
        assistant_message: str,
    ) -> AgentState:
        """Append one user/assistant pair in a single durable state update."""

        with self._lock:
            state = self._require_state(session_id)
            state = self._ensure_threads_locked(session_id, state)
            timestamp = utc_now()
            user = AgentChatMessage(
                role="user",
                content=user_message,
                created_at=timestamp,
            )
            assistant = AgentChatMessage(
                role="assistant",
                content=assistant_message,
                created_at=timestamp,
            )
            for index, thread in enumerate(state.agent_threads):
                if thread.thread_id != thread_id:
                    continue
                updated_thread = thread.model_copy(
                    update={
                        "messages": [*thread.messages, user, assistant],
                        "updated_at": timestamp,
                    }
                )
                threads = list(state.agent_threads)
                threads[index] = updated_thread
                return self.update(session_id, {"agent_threads": threads})
            raise AgentThreadNotFoundError(session_id, thread_id)

    def delete(self, session_id: str) -> bool:
        """Remove a session. Returns False if the session did not exist."""

        with self._lock:
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

    def _require_state(self, session_id: str) -> AgentState:
        state = self.get(session_id)
        if state is None:
            raise KeyError(f"Session not found: {session_id}")
        return state

    def _ensure_threads_locked(self, session_id: str, state: AgentState) -> AgentState:
        if state.agent_threads:
            return state

        timestamp = state.persisted_at or state.created_at or utc_now()
        messages: list[AgentChatMessage] = []
        for legacy in state.dialogue_history:
            if not isinstance(legacy, dict):
                continue
            role = legacy.get("role")
            content = legacy.get("content")
            if role not in {"user", "assistant"} or not content:
                continue
            normalized_content = str(content).strip()[:20_000]
            if not normalized_content:
                continue
            messages.append(
                AgentChatMessage(
                    role=cast(Literal["user", "assistant"], role),
                    content=normalized_content,
                    created_at=timestamp,
                )
            )

        title = IMPORTED_THREAD_TITLE if messages else DEFAULT_THREAD_TITLE
        thread = AgentChatThread(
            thread_id=uuid.uuid4().hex,
            title=title,
            created_at=timestamp,
            updated_at=timestamp,
            messages=messages,
        )
        migrated = state.model_copy(
            update={
                "agent_threads": [thread],
                "dialogue_history": [],
            }
        )
        self._sessions[session_id] = migrated
        self.save(session_id)
        return self._sessions[session_id]

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
