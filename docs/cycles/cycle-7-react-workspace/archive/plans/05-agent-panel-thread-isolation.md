# M5: Agent Panel and Thread Isolation

## Status

Implemented. The React Agent panel now lists, creates, selects, and reloads
Project-local Threads, sends explicit-thread bounded Copilot turns, and drops
stale Project/Thread responses during switches.

## Objective

Deliver the right-hand IDE Agent panel: a user can create, select, reopen, and
read multiple Agent conversations inside the active Project and send bounded
Copilot turns to the selected Thread. Project workspace facts are shared as
intended, but messages never cross Thread or Project boundaries. Accept/Reject
for Plan proposals remains explicitly out of scope.

## Dependencies and Boundary

- Depends on: M1 thread APIs and Copilot resolver, and M2 shell/navigation.
- May run alongside M3 and M4 once the shared API client and Project resource
  lifecycle are stable.
- Does not implement: autonomous/background Agent loops, streaming redesign,
  proposal persistence or diff/Accept/Reject, cross-Project memory, or a new
  LLM provider/runtime.
- Cycle 6's bounded model/tool exchange, soft slash skills, read-only Plan
  proposal boundary, and safety limits remain authoritative.

## Proposed Modules and Contracts

| Location | Responsibility |
|---|---|
| `frontend/src/features/agent/AgentPanel.tsx` | Right pane composition and active-thread lifecycle |
| `frontend/src/features/agent/AgentThreadList.tsx` | Project-local thread list, create action, metadata, and selection |
| `frontend/src/features/agent/MessageHistory.tsx` | Ordered messages, loading/error/tool-used markers, and scroll behavior |
| `frontend/src/features/agent/Composer.tsx` | Message input, submit/cancel, disabled states, and soft command text |
| `frontend/src/features/agent/agentStore.ts` | Project/thread-keyed UI state only; no duplicate Plan or message authority |
| `frontend/src/api/agentApi.ts` | Thread list/detail/create and explicit-thread Copilot requests |
| `src/api/routes/copilot.py` | `thread_id` request validation and selected-thread dispatch |
| `src/agent/copilot.py` | Thread resolver and atomic append around the existing handler |
| `src/agent/copilot_context.py` | Selected-thread recent history plus shared Project workspace projection |
| `tests/api/test_agent_chats.py`, `tests/api/test_copilot.py` | Isolation, migration, restart, and bounded-turn regressions |
| `frontend/src/features/agent/*.test.tsx` | Thread switching and composer behavior |

### UI and request contract

The panel always has a Project-local thread list, a selected Thread ID, full
history for that Thread, and a composer. The request body is:

```json
{"thread_id": "thread-opaque-id", "message": "..."}
```

The frontend never sends a Thread object, another Project ID, raw state, or a
client-assembled conversation context. The API verifies ownership and builds
the context server-side. Thread messages returned to the UI contain only
`user` and `assistant` roles plus timestamps; tool exchange details are shown
only as a neutral turn marker when the response exposes them.

### Isolation contract

```text
selected Project P
  workspace facts: shared by P.thread-1 and P.thread-2
  messages:        only the selected Thread

Project Q
  workspace facts: Q only
  messages:        Q threads only
```

Switching a Thread clears the visible history until its detail request resolves
and aborts a pending send for the old selection. Switching a Project clears
the entire Agent resource and selected Thread. A late response is ignored by
both Project ID and Thread ID.

## Execution Tasks

### 1. Add the thread resource client and hook

- Add typed methods for list, create, detail, and Copilot turn. Normalize
  ownership, incompatible-Project, validation, and model-failure errors.
- Key cached data by `(project_id, thread_id)` and avoid a global message array.
- Fetch the thread list when the active Project changes; select the first
  server-provided Thread deterministically, or create the documented default.
- Refetch the selected detail after a successful turn so the server remains
  the message authority. Do not append a guessed assistant string locally.

### 2. Build the Agent panel UI

- Render a compact thread list with title, updated time, message count, and a
  clear selected state. Include `New Agent chat`; do not conflate it with New
  Project.
- Render an empty state for a new Thread and a restart-safe loading state for
  historical messages.
- Keep message content readable, preserve ordered turns, and distinguish a
  model error from a user message. Tool-used/status markers are informational,
  not approval controls.
- Composer supports Enter/send and an accessible multiline path. Disable
  submit for blank/overlong input, while preserving the server's sanitizer and
  max length as the final guard.
- Show a retry action for a failed turn that resends only after an explicit
  user action; do not silently duplicate a persisted turn.

### 3. Wire selected-thread Copilot requests

- Send the active `thread_id` on every request. Prevent submit if the Project
  or Thread changed during preparation.
- Display skill names and bounded tool-round metadata when returned, without
  implying that a proposed Plan was applied.
- Keep Plan proposal results read-only in this cycle. The panel may link the
  user to the Plan Canvas, but it must not call `/workspace` from a Copilot
  response.
- Preserve slash command behavior (`/inspect`, `/plan`, `/run`, `/rerun`, and
  `/help`) as soft-injected prompts; unknown prefixes remain ordinary text with
  the existing explanation.

### 4. Validate server context isolation

- Refactor `build_copilot_context` to accept the selected Thread or a resolved
  recent-history projection. Keep the full history available only to the UI;
  send the existing bounded recent window to the model.
- Ensure fresh Sources, Snapshots, Plan, execution, lineage, and report facts
  are built from the addressed Project on every turn.
- Append the user/final-assistant pair to the resolved Thread in one state
  update. Do not persist tool messages or a second global mirror.
- Keep compatibility `/dialogue` behavior as decided in M1, but do not call it
  from React.

### 5. Handle lifecycle and failure states

- Abort in-flight detail/send requests when the selected Project or Thread
  changes, and clear the busy flag on abort, validation failure, timeout, and
  server error.
- If a Thread is deleted or becomes unavailable in a later API response, pick
  a valid Project-local Thread and make the change visible; Cycle 7 need not
  expose Thread deletion UI.
- Keep the panel usable when no LLM credentials are configured by showing the
  normalized Copilot error and preserving existing history.

## Tests and Evidence

- API tests create two Threads in one Project and assert messages from Thread A
  are absent from Thread B's detail and fake-LLM context.
- API tests create a second Project and assert a foreign `thread_id` cannot be
  used under it, including after a fresh process/store load.
- Migration tests verify legacy history appears once in the default Thread,
  remains after restart, and is not appended to a global history mirror.
- Fake-LLM tests verify only the selected recent window is supplied, workspace
  facts come from the addressed Project, and Cycle 6 round/tool limits remain
  unchanged.
- Component/browser evidence creates two Agent chats, switches between them,
  reloads, sends messages, switches Projects, and confirms no visible or
  contextual cross-talk.
- Verify a Copilot plan proposal leaves `AgentState.plan` unchanged and that
  the UI offers no Accept/Reject control.
- Run focused frontend tests, `npm run typecheck`, `npm run lint`, `pytest -q
  tests/api/test_copilot.py tests/api/test_agent_chats.py`, `ruff check .`,
  `mypy src/`, and `git diff --check`.

## Exit Criteria

- The right panel can list, create, select, and reload multiple durable Agent
  conversations per Project.
- Selected-thread messages are isolated in storage, UI, and Copilot context;
  Project workspace facts remain shared only within that Project.
- A normal or soft-skill Copilot turn completes through the existing bounded
  runtime and persists exactly one user/final-assistant pair to the selected
  Thread.
- Plan proposal output remains visibly read-only, with no Accept/Reject,
  hidden mutation, or cross-Project memory behavior.

## Risks and Mitigations

- **UI displays the wrong history after a fast switch:** key every request and
  component state by both Project and Thread IDs and abort stale requests.
- **Context leakage through a convenience fallback:** require an explicit
  thread ID in React and test foreign IDs at the route boundary.
- **Duplicate messages after retries:** refetch server history after success,
  append only in the server transaction, and make retry an explicit action.
- **Proposal semantics accidentally expand:** keep the Copilot response typed
  as informational and prohibit the Agent feature from importing Plan mutation
  clients for proposal application.

## Validation Evidence

- `frontend/src/api/agentApi.test.ts` covers Thread DTO decoding, structured
  errors, and the explicit `{thread_id, message}` Copilot request body.
- `frontend/src/features/agent/agentStore.test.ts` covers Project reset,
  Thread switching, stale detail isolation, and explicit send retry state.
- `frontend/src/features/agent/AgentPanel.test.tsx` covers a late detail
  response after a fast Thread switch and Project reload.
- `frontend/src/features/agent/Composer.test.tsx` covers Enter submission and
  Shift+Enter multiline input.
- Frontend typecheck, lint, tests, and production build pass. Repository
  validation also passed with `pytest -q` (277 tests), `ruff check .`,
  `mypy src/`, and `git diff --check`.
