# Cycle 7 Development Issues

## Closed M7 Work

Execution, rerun, report, Project switching, frontend build contracts, and the
implemented M7 interaction/layout contracts are covered by the repository and
frontend validation suites.

## M7 Workspace Review

The initial M6 workspace exposed duplicate operation creation paths, a bottom
Inspector that enlarged the page, browser-level scrolling, and layout writes
triggered by every node movement frame. M7 resolved these issues by making the
Explorer operation palette click-only, requiring columns to target explicit
Unit slots, rendering the Inspector beside the selected node with its own
scroll area, constraining the shell to `100dvh`, and queueing only the latest
validated layout after a drag or viewport gesture.

## Validation Environment Gap

The workspace did not contain Playwright, Puppeteer, or a browser executable.
The planned desktop and narrow-viewport screenshot/trace evidence therefore
could not be captured. The fallback evidence is the 41-test frontend suite,
the full 281-test backend suite, the Vite production build, and a FastAPI HTTP
smoke against `/`, a direct Project URL, execution status/results, report, and
Dashboard compatibility reads.

## Implemented M8 Supplement

M8 adds the coherent Plan-aware workspace data projection and revision-safe
node/collapse persistence. Planned Snapshot and column schema can now be
selected or dragged into downstream Unit slots before execution; unknown
execution facts remain nullable, and stale output falls back to planned schema.
Explorer-only refreshes follow accepted Plan mutations, while viewport changes
remain local. The focused M8 tests are included in the 281-test backend and
41-test frontend validation evidence above.
