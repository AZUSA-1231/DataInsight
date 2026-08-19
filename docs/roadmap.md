# Roadmap

## Current State

Cycle 7 is closed and audited as a focused React workspace rebuild: durable
Project history, Project naming, isolated Agent conversations inside each
Project, a Plan-canonical Plan Canvas, typed Explorer editing, and a light
IDE-style browser shell with an integrated Output Dock. Its M7 follow-up also
reduced the workspace to one operation-creation path, moved Unit inspection
beside the selected node, contained panel scrolling inside the viewport, and
made layout persistence resilient to fast drag gestures. The restricted M8
supplement now exposes unexecuted Plan schema in the Explorer through one
coherent catalog projection and makes node-position persistence revision-safe;
it does not broaden the Cycle 7 product scope. The existing Cycle 5
multi-table workflow and Cycle 6 bounded Copilot remain the runtime
foundation.

## Closed Cycle

Cycle 7: React Project Workspace

M1 Project/Thread foundation, M2 Project-history shell, M3 Plan Canvas
mapping/layout, M4 Explorer plus typed operation editing, M5 Agent panel
isolation, and M6 Output Dock integration are implemented.

- [Cycle summary](cycles/cycle-7-react-workspace/summary.md)
- [Supplemental plans](cycles/cycle-7-react-workspace/supplemental-plans/README.md)
- [Cycle archive](cycles/cycle-7-react-workspace/archive/README.md)

The cycle replaces the zero-build frontend with React, TypeScript, and Vite.
It does not add Copilot Plan Accept/Reject, new operations, dashboard product
work, authentication, or a second analysis runtime.

**Cycle 5: Column-First Lineage and Multi-Table Foundation**

- [Cycle summary](cycles/cycle-5-column-lineage/summary.md)
- [Development issues](cycles/cycle-5-column-lineage/development-issues.md)
- [PRD, assessment, and milestone plans](cycles/cycle-5-column-lineage/archive/README.md)

The cycle delivered the approved end-to-end scope. Detailed PRDs and milestone
plans are historical artifacts under the cycle's `archive/` directory.

The acceptance path is:

```text
upload orders + customers
-> derive revenue
-> filter into east_orders
-> join customers
-> run terminal analysis
-> restart and reload the Session
-> rerun a unit while retaining prior checkpoints and lineage
```

**Cycle 6: Bounded Copilot Chat**

- [Cycle summary](cycles/cycle-6-command-copilot/summary.md)
- [Development issues](cycles/cycle-6-command-copilot/issues.md)

The Copilot is an overlay, not a second workspace runtime. The browser uses
`POST /api/sessions/{session_id}/copilot`; the old `/dialogue` endpoint remains
only for compatibility. Workspace confirmation for Plan proposals is deferred.

## Deferred Candidates

These are candidates for a future PRD and are not committed scope:

1. Workspace Accept/Reject interaction for Copilot Plan proposals.
2. A visual lineage graph and checkpoint browser.
3. Bounded worker isolation for generated functions and resource limits.
4. Explicit, reviewable data-quality cleaning decisions.
5. Aggregate, Window, Pivot, Union, Measure, and first-class Model operations.
6. Dashboard product design and backend contract completion.
7. Checkpoint cleanup, cross-Session sources, database connections, and hosted
   multi-user support.
8. An evaluation harness for success rate, retries, report faithfulness, and
   latency on a stable corpus.

## Selection Rule

Choose one outcome, validate its user problem, and write one PRD representing a
fully usable cycle. Do not combine unrelated architectural upgrades simply
because they touch adjacent modules.
