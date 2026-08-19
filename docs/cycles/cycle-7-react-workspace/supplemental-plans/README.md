# Cycle 7 Supplemental Plans

Cycle 7 was closed after M6. This directory records the post-closure
implementation work that remains within the Cycle 7 workspace boundary. The
original M1-M6 plans remain historical records under `../archive/plans/`.

| ID | Plan | Status |
|---|---|---|
| M7 | [Workspace interaction simplification and layout stability](07-workspace-interaction-simplification-and-layout-stability.md) | Implemented |
| M8 | [Plan-time Explorer projection and node drag persistence](08-plan-time-explorer-projection-and-node-drag-persistence.md) | Implemented |

M7 keeps the existing Plan v2 and execution contracts. M8 also preserves
those contracts: it exposes a read-only, plan-time data projection for the
Explorer and narrows layout persistence to final node positions and collapse
state. It does not introduce draft Plan semantics, checkpoint materialization,
or new execution behavior.
