# M1: Project State, History, and Agent Threads

## Objective

Make the existing durable Session usable as a user-facing `Project`, and add
durable, strictly scoped Agent conversations. The milestone supplies the
server projections and migration behavior required by every React feature. It
does not build the React shell or change the bounded model/tool exchange.

## Dependencies and Boundary

- Depends on: the audited Cycle 6 state model, `SessionStore`, and the current
  session-scoped Copilot endpoint.
- Enables: Project history UI, Project switching, Workspace layout persistence,
  and thread-aware Copilot requests.
- Does not implement: Plan Canvas rendering, operation forms, Dashboard work,
  Accept/Reject, authentication, or a second message database.
- Keep schema version 2 compatible. New fields are optional and receive typed
  defaults; do not silently rewrite an incompatible state file.

## Proposed Modules and Contracts

| Location | Responsibility |
|---|---|
| `src/agent/state.py` | `AgentChatMessage`, `AgentChatThread`, and the optional Project metadata and `WorkspaceLayout` models; preserve immutable state updates |
| `src/api/session.py` | Project creation/list summaries, title update, thread creation/read/update helpers, one-time legacy-history migration, and atomic persistence |
| `src/api/schemas.py` | Safe Project summary, Project rename/create, Agent thread, message, and layout request/response models |
| `src/api/routes/projects.py` or `src/api/app.py` | `GET/POST /api/sessions` and `PATCH /api/sessions/{project_id}` without exposing raw state |
| `src/api/routes/agent_chats.py` | Project-owned thread list/create/read routes and ownership checks |
| `src/api/routes/copilot.py` | Accept an explicit `thread_id` and resolve it through the addressed Project |
| `src/api/routes/dialogue.py` | Compatibility adapter or deprecation behavior; never become a second Cycle 7 conversation source |
| `src/agent/copilot_context.py` and `src/agent/copilot.py` | Build context from the selected Thread while retaining the shared Project workspace projection and Cycle 6 bounds |
| `tests/api/test_sessions.py`, `tests/api/test_agent_chats.py` | Persistence, projection, migration, ownership, and restart coverage |
| `tests/api/test_copilot.py`, `tests/test_copilot.py` | Selected-thread context and no cross-thread leakage |

### Durable model

Use repository naming conventions if the final spelling differs, but preserve
these ownership boundaries:

```python
class AgentChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str

class AgentChatThread(BaseModel):
    thread_id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[AgentChatMessage] = Field(default_factory=list)

class WorkspaceLayout(BaseModel):
    version: Literal[1] = 1
    viewport: WorkspaceViewport = Field(default_factory=WorkspaceViewport)
    nodes: list[WorkspaceNodeLayout] = Field(default_factory=list)
```

`AgentState` gains `project_title`, `created_at`, `agent_threads`, and
`workspace_layout`, all with safe defaults. `AgentState.plan`, registries,
results, and report remain the existing sources of truth. `dialogue_history`
is not copied into every Thread and is not read by the new Copilot path after
migration.

### Public API

Add these typed routes. The user-facing parameter is called `project_id`, but
it remains the existing 32-character `session_id` on disk and in compatibility
paths.

```text
GET    /api/sessions
POST   /api/sessions                         {title?, user_requirement?}
GET    /api/sessions/{project_id}            existing safe state summary
PATCH  /api/sessions/{project_id}            {title}
GET    /api/sessions/{project_id}/agent-chats
POST   /api/sessions/{project_id}/agent-chats {title?}
GET    /api/sessions/{project_id}/agent-chats/{thread_id}
POST   /api/sessions/{project_id}/copilot    {thread_id, message}
```

Project list entries contain only safe summary fields:
`project_id`, `title`, `created_at`, `persisted_at`, `source_count`,
`unit_count`, `has_results`, `has_report`, `agent_chat_count`, and an optional
compatibility/status marker. Do not return upload paths, checkpoint paths,
internal Column Graph IDs, raw profile samples, or full messages from the list.

Thread list entries contain metadata and a message count/preview as needed by
the UI. The detail route returns the complete selected-thread messages. Every
thread route verifies that the `thread_id` belongs to the Project in the URL;
a valid thread ID from another Project is still a 404 or stable ownership
error, never a read of foreign data.

### Legacy history migration

Resolve legacy state lazily, under one SessionStore update:

1. If `agent_threads` is non-empty, use it and ignore `dialogue_history`.
2. If no threads exist and legacy history is non-empty, create one named
   `Imported chat` thread, normalize only user/assistant messages, clear the
   legacy history, and persist the resulting state atomically.
3. If neither exists, create one empty default thread and persist it when a
   thread API or Copilot request first needs it.

The migration must be idempotent under a repeated request. Existing messages
without timestamps receive a deterministic migration timestamp or the
Project's persisted timestamp; no message is duplicated. Compatibility
`/dialogue` and `/dialogue/stream` callers resolve the Project's default Thread
and adapt their legacy response shape, but never write `dialogue_history` after
migration. They must not reintroduce a competing global history.

## Execution Tasks

### 1. Add typed state and serialization defaults

- Define message, thread, viewport, node-layout, and Workspace layout models
  with bounded strings, finite numeric values, and `default_factory` for
  mutable collections.
- Add Project title and creation time to `AgentState` without changing the
  schema-version gate.
- Confirm `SessionStore.save()` strips executor-only result keys while keeping
  the new fields JSON serializable and atomically replacing `state.json`.
- Add a small helper that returns a safe Project summary from an `AgentState`.

### 2. Implement Project listing and rename

- Extend `SessionStore.create()` to accept an optional title and set a stable
  creation timestamp. New Projects always start with one empty default Thread
  in the same persisted state transaction; only pre-Cycle 7 Projects use the
  lazy migration rule above.
- Scan only valid session directories for `GET /api/sessions`. A malformed or
  incompatible state is skipped or surfaced with the existing status marker,
  never deleted or silently migrated.
- Trim and validate titles (non-blank, bounded length), persist the rename in
  one update, and return the updated safe summary.
- Preserve existing `POST /api/sessions` response compatibility for callers
  that only expect `session_id`.

### 3. Add Agent chat resource operations

- Add list, create, and detail helpers that always load the addressed Project
  first and then resolve a member Thread.
- Generate opaque stable thread IDs and deterministic initial titles such as
  `New chat`; optionally replace the title with a short first-message excerpt
  later, without adding a title-generation service.
- Keep message roles limited to `user` and `assistant`; do not persist tool
  messages or model internals as conversation history.
- Update `updated_at` whenever a message pair is appended and use one atomic
  state update for the pair.

### 4. Thread-scope Copilot without changing runtime limits

- Add `thread_id` to `CopilotTurnRequest` (retain a temporary default-thread
  fallback only for compatibility callers).
- Refactor the turn handler behind a resolver that supplies the selected
  Thread's recent bounded history and the active Project's fresh workspace
  projection. Keep the existing soft slash command behavior, tool safety,
  maximum rounds, model calls, and total tool calls unchanged.
- Append the sanitized user message and final assistant message to the same
  Thread only. A failed model call follows the existing result/error contract
  and must not append a message to a different Thread.
- Make active Project/thread ownership errors explicit and testable.

### 5. Adapt compatibility dialogue behavior

- Make `/dialogue` and `/dialogue/stream` resolve the default Project Thread,
  run their existing compatibility response behavior, and persist messages in
  that Thread. Preserve the Cycle 6 response shapes for existing callers.
- Ensure the React client never calls `/dialogue` and that no code path reads
  both `dialogue_history` and `agent_threads` for one turn.
- Add a regression test proving a compatibility request after migration does
  not recreate or append to the global `dialogue_history` field.

### 6. Publish an API contract fixture

- Add a small JSON fixture or typed test helper representing two Projects,
  two Threads in one Project, and one migrated legacy history.
- Use it as the fixture boundary for M2 and M5 instead of letting frontend
  tests inspect `state.json` directly.

## Tests and Evidence

- `GET /api/sessions` returns newest-first safe summaries and excludes paths,
  hidden IDs, and message bodies.
- Project title creation, rename, restart, and blank/overlong validation work.
- A new Project has the documented default-thread behavior and a new Thread
  persists after a fresh `SessionStore` instance loads the state.
- A thread from Project A cannot be read or used for a Copilot request under
  Project B. Two Threads in one Project receive identical workspace facts but
  disjoint message context.
- Legacy `dialogue_history` migrates exactly once, is cleared or delegated as
  documented, and does not duplicate messages on repeated requests.
- Copilot tests assert the selected Thread's recent messages are sent to the
  fake LLM and that the final pair is appended atomically.
- Run focused tests, then `pytest -q tests/api/test_sessions.py
  tests/api/test_agent_chats.py tests/api/test_copilot.py`, `ruff check .`,
  `mypy src/`, and `git diff --check`.

## Exit Criteria

- A client can list, create, rename, and reopen Projects using server state.
- A client can list, create, and read multiple durable Agent Threads within a
  Project, with strict Project and Thread isolation after restart.
- Copilot accepts an explicit Thread and uses only that Thread's history while
  retaining the shared Project workspace context and Cycle 6 bounds.
- No new database, cross-Project memory store, proposal persistence, or
  authentication code exists.
- M2 and M5 can consume typed API projections without reading `state.json`.

## Risks and Mitigations

- **Dual history after migration:** perform migration and legacy-field clearing
  in one atomic update; add a test that sends a second turn after restart.
- **Cross-Project leakage:** resolve the thread only from the Project object
  addressed by the URL and test both list and Copilot paths with foreign IDs.
- **Malformed old state:** keep the schema gate and safe summary status; never
  repair or delete incompatible files as a side effect of listing.
- **Concurrent turns:** serialize message appends per Project/Thread or reject
  an overlapping request deterministically so one pair cannot overwrite the
  other.
