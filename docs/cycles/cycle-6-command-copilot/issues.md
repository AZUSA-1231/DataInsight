# Cycle 6 Issues

## ISSUE-001: Platform plan exceeded the product boundary

- **Status:** Resolved by restart decision.
- **Observation:** The first execution plan introduced ten dependent plans,
  generic actions, fingerprints, a second persistence store, proposals,
  lifecycle events, and cross-file transactions before a Copilot turn existed.
- **Decision:** Return to the Cycle 5 software baseline and restart with the
  three-milestone bounded Copilot plan. Do not preserve the abandoned platform
  implementation as an architectural constraint.

## ISSUE-002: Tool calling needs bounded multi-segment turns

- **Status:** Accepted for M1.
- **Observation:** A useful chat turn may require model -> tool -> model result
  synthesis, but an unlimited coding-agent loop is unnecessary.
- **Decision:** Allow multiple in-request tool segments under a small configured
  maximum. Stop on final text, tool failure, timeout, or round limit. There is
  no background continuation or recursive self-repair.

## ISSUE-003: Plan edit needs a future Workspace confirmation boundary

- **Status:** Accepted for M2.
- **Observation:** Plan editing is central to the Copilot but the Workspace
  Accept/Reject interaction is not part of the current agent slice.
- **Decision:** Implement `PlanEditGateway` and a mock/default adapter that
  returns a complete validated Plan result without writing `AgentState.plan`.
  Later Workspace work can bind the same result to an editable diff and
  acceptance action.

## ISSUE-004: Conversation persistence should remain on AgentState

- **Status:** Accepted for restart.
- **Observation:** A second `copilot.json` store creates unnecessary lifecycle
  and cross-file consistency work for a local single-user app.
- **Decision:** Reuse `AgentState.dialogue_history` and existing SessionStore
  persistence. No Copilot-specific durable schema is introduced.

## ISSUE-005: Lineage projection could expose hidden row references

- **Status:** Resolved in M2.
- **Observation:** Direct hidden columns were excluded from the workspace
  projection, but a visible derived column could still carry
  `__di_row_id` through `origin_refs` or parent lineage metadata.
- **Decision:** Filter hidden references in both the context projection and
  typed inspection results. Copilot tools continue to consume only the
  projected workspace, never live executor data.

## ISSUE-006: Blank sanitized messages reached the model

- **Status:** Resolved in closure audit.
- **Observation:** The API rejected an empty string but accepted whitespace or
  delimiter-only input that sanitization reduced to an empty message.
- **Decision:** Validate non-blank API input and enforce the same invariant
  after sanitization in the turn handler. Invalid input returns HTTP 422 and is
  neither sent to the model nor persisted.

## ISSUE-007: Turn completion could overwrite newer history

- **Status:** Resolved in closure audit.
- **Observation:** A turn built its final history from the state captured before
  the model call. A newer history update made during that call could be lost.
- **Decision:** Keep the turn context as a start-of-turn snapshot, but reload
  the latest `AgentState` before appending the completed user/assistant pair.

## ISSUE-008: Internal exception details were user-visible

- **Status:** Resolved in closure audit.
- **Observation:** Provider and tool exceptions were copied into response
  messages and structured errors, potentially exposing configuration or local
  paths.
- **Decision:** Log full exceptions server-side and return stable public error
  messages/codes. Unexpected provider response objects are not stringified.

## ISSUE-009: JSON safety fallback could stringify runtime objects

- **Status:** Resolved in closure audit.
- **Observation:** Unknown values in projected metadata fell back to `str`, and
  non-finite floats produced non-standard JSON tokens.
- **Decision:** Replace unknown values with a fixed omission marker, normalize
  non-finite floats to `null`, and require standard JSON when building the model
  message. Tool-result serialization uses the same non-leaking fallback.

## ISSUE-010: Run/rerun policy advertised deferred mutation tools

- **Status:** Resolved in closure audit.
- **Observation:** The soft-skill policy named `run_plan` and `rerun_unit`, but
  Cycle 6 did not bind either tool and the cycle summary deferred them.
- **Decision:** Keep `/run` and `/rerun` as guidance plus result-inspection
  skills for Cycle 6. Execution mutations remain on the existing Workspace UI
  until a later PRD defines a confirmation boundary.

## ISSUE-011: Casual chat overwrote the formal business requirement

- **Status:** Resolved in closure audit.
- **Observation:** Completing any Copilot turn wrote the sanitized chat message
  into `AgentState.user_requirement`. A `/help` or inspection question could
  therefore replace the durable business intent even though the Copilot is an
  overlay on Workspace state.
- **Decision:** Copilot persistence appends only the final user/assistant pair
  to `dialogue_history`. Formal intent changes remain behind their existing
  product/domain paths.

## Deferred

The following remain future interaction or product work: Plan Accept/Reject UI,
Copilot execution/rerun mutations, Canvas actions, checkpoint version
selection, richer skills, and any measured need for context summarization.
