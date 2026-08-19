# M2: Vite Shell and Project History UI

## Objective

Replace the zero-build browser entry point with a maintained React + TypeScript
+ Vite application and establish the light IDE-style shell. A user can see a
server-backed Project history, create a Project, rename it, switch it, and see
stable loading/error/empty states. This milestone creates the layout regions;
it does not yet implement the Plan Canvas semantics, operation forms, Agent
runtime, or Output Dock content.

## Dependencies and Boundary

- Depends on: M1 typed Project and Agent-thread projections.
- Enables: M3, M4, M5, and M6 feature components to mount in a shared shell.
- Does not implement: a visual-design system, responsive mobile redesign,
  authentication, Project deletion, Result Canvas / Board, or Dashboard pins.
- The old static UI is not extended. Its useful API behavior is migrated into
  typed React feature clients and then retired at M6.

## Proposed Modules and Contracts

| Location | Responsibility |
|---|---|
| `frontend/package.json` | React, TypeScript, Vite, React Flow, and package scripts (`dev`, `typecheck`, `lint`, `build`, `test`) |
| `frontend/vite.config.ts` | FastAPI proxy in development and production output configuration |
| `frontend/tsconfig.json`, `frontend/index.html` | Strict browser build boundary |
| `frontend/src/main.tsx` | React bootstrap and global error boundary |
| `frontend/src/app/App.tsx` | Active Project route, resource loading, and shell composition |
| `frontend/src/api/client.ts` | One typed fetch wrapper, JSON/error decoding, and request cancellation |
| `frontend/src/domain/types.ts` | Public API types only; no Pydantic internals or raw state file types |
| `frontend/src/features/projects/ProjectSwitcher.tsx` | Project list, create, select, and rename interactions |
| `frontend/src/features/shell/Header.tsx` | Logo, active Project title, history control, New Project, and fake local user |
| `frontend/src/features/shell/ThreePaneLayout.tsx` | Header, Explorer slot, center workspace slot, Agent slot, and Output Dock slot |
| `frontend/src/styles/tokens.css`, `frontend/src/styles/app.css` | Functional light theme, focus states, sizing, and pane boundaries |
| `src/api/app.py` and build scripts | Serve the Vite production output while retaining API routes |
| `frontend/src/**/*.test.ts(x)` | Component and API-client tests without direct state-file access |

### Shell contract

The app has one active Project ID at a time. The server-backed list is the
authority; browser storage may remember only the last active ID as a
convenience. Encode the active ID in the URL, for example
`/projects/<project_id>`, and treat a missing or incompatible ID as a visible
recoverable state rather than silently creating a new Project.

The shell has these stable regions:

```text
Header
  logo | active Project / history | New Project | Local user
Body
  Explorer slot | center Workspace slot | Agent panel slot
  center bottom: collapsible Output Dock slot
```

Each slot owns its own loading and error boundary. Switching Projects cancels
in-flight requests, clears transient selection and drag state, and only then
loads the new Project's public projections. No feature may retain a stale
resource from the previous Project by keying state only on a component mount.

### Build and serving contract

- Development uses the Vite dev server with `/api` proxied to FastAPI. The
  README must document starting both local processes.
- Production uses the existing FastAPI `static/` mount as the generated Vite
  output (`frontend/vite.config.ts` sets `build.outDir` to `../static`). Move
  any retained image assets into `frontend/public` before the first clean
  build; do not maintain two browser applications after M6.
- API tests must remain runnable without a Node process. The FastAPI app should
  expose API routes even when a production build has not yet been generated;
  the serving fallback must be explicit and documented.
- TypeScript uses strict mode. Do not use `any` for server payloads; unknown
  JSON is decoded at the API boundary and validated into domain types.

## Execution Tasks

### 1. Scaffold the maintained frontend

- Add the Vite React TypeScript project under `frontend/` with a lockfile and
  pinned compatible versions.
- Add scripts for `dev`, `typecheck`, `lint`, `build`, and focused tests. Keep
  the dependency list small; React Flow is introduced by M3, not a generic
  graph framework of our own.
- Set strict compiler options, path aliases only where they improve local
  readability, and a test environment that can run pure mapping tests without
  a browser.

### 2. Implement the typed API boundary

- Add `apiFetch` with base URL handling, abort signals, JSON parsing, and a
  normalized error containing HTTP status and structured `detail`.
- Define `ProjectSummary`, `ProjectStateSummary`, `AgentThreadSummary`, and
  shared loading/resource types from M1 responses.
- Add clients for list/create/get/rename Project. Every mutation returns or
  triggers a refresh from the server; local optimistic titles are not the
  durable authority.
- Add a request generation token or abort controller so a late response from
  Project A cannot overwrite Project B state.

### 3. Build the Header and Project history flow

- Render a compact DataInsight logo/text mark, active Project title, history
  control, New Project action, and a fixed `Local user` affordance.
- History entries show title, recent activity, source count, unit count, and
  high-level result/report indicators from the safe summary. Do not show raw
  paths or internal IDs as editable objects.
- Make rename explicit (edit, confirm, cancel), validate on the server, and
  announce errors without losing the previous title.
- New Project creates a server record, navigates to its URL, and loads its
  default empty state. Project deletion is absent from menus and keyboard
  actions.
- Keep a visible empty state when no Projects exist and a distinct incompatible
  Project state when the server reports schema incompatibility.

### 4. Compose the three-column IDE shell

- Establish CSS grid/flex tracks with stable minimum widths: Explorer, center
  workspace, and Agent panel. The center may shrink only to the documented
  minimum; controls must not overlap or resize cards unpredictably.
- Add a header row and a bottom Output Dock slot whose collapse state is local
  to the active Project view until M6 decides whether it is persisted.
- Add keyboard focus styles, visible busy/error states, and a light palette
  with restrained borders. Keep styling functional and avoid a premature full
  design system.
- Mount placeholder panels for Explorer, Plan Canvas, Agent panel, and Output
  Dock so later milestones can replace a slot without changing navigation.

### 5. Retire the old entry path in a controlled step

- Record which API calls and user behaviors were covered by `static/app.js`
  before removing it from the supported runtime.
- Update README and developer instructions to use Vite scripts and the local
  FastAPI/Vite workflow. Do not delete user-owned assets or unrelated static
  files until the build and serving path is verified.
- Add a production smoke check that opens the generated index and confirms an
  API request still reaches FastAPI.

## Tests and Evidence

- API-client tests cover successful JSON, structured HTTP errors, aborts, and a
  late response ignored after an active Project switch.
- Component tests cover no Projects, list ordering, create navigation, rename
  success/failure, incompatible Project display, and fake-user rendering.
- A browser check opens two Projects, switches between them, reloads the
  active URL, and confirms the server title remains authoritative.
- The three-column shell has no horizontal overlap at the supported desktop
  width and keeps a usable center region at the narrow validation width.
- `npm run typecheck`, `npm run lint`, `npm run build`, `pytest -q
  tests/api/test_sessions.py`, `ruff check .`, `mypy src/`, and
  `git diff --check` pass for the milestone.

## Exit Criteria

- The maintained browser source is React + TypeScript + Vite under `frontend/`.
- A built app can be served by FastAPI without requiring the legacy zero-build
  page at runtime.
- Project history, creation, switching, and durable rename work across a
  browser reload and a server restart.
- Header and three-pane shell provide stable mounting points for all remaining
  Cycle 7 features and show clear loading/error/empty states.
- No authentication, Project deletion, Dashboard feature, or duplicate API
  client boundary was introduced.

## Risks and Mitigations

- **Build output unavailable in API tests:** keep serving configuration
  explicit and provide a test-safe API-only fallback; make the production
  build a separate verified step.
- **Stale Project responses:** key every resource by Project ID and abort or
  ignore requests from the previous generation.
- **Legacy UI accidentally remains supported:** document one supported entry
  path, capture the migration evidence, and remove old navigation after the
  new build serves successfully.
- **Layout becomes a card maze:** keep the shell as unframed regions; use
  framed cards only for repeated Project entries and real tool surfaces.
