# Cycle 7: React Workspace

Cycle 7 rebuilds the browser workspace as a light-theme React, TypeScript, and
Vite application. Its usable outcome is a project-oriented IDE workspace:
users can reopen and rename projects, switch among isolated Agent conversations
inside a project, assemble the existing Plan v2 visually, execute it, and
inspect the resulting evidence.

## Cycle Records

- [Cycle summary](summary.md)
- [Development issues](development-issues.md)
- [Detailed PRD, architecture, and milestone plans](archive/README.md)
- [Supplemental plans](supplemental-plans/README.md)

The implementation index is split into six bounded milestones. M1 establishes
Project and Agent-thread persistence; M2 builds the React shell; M3 protects
the Plan Canvas and Workspace layout mapping; M4 connects Explorer and
operation editing; M5 adds the isolated Agent panel; and M6 integrates the
Output Dock and records closure evidence.

Cycle 7 is closed, with the M7 interaction and layout-stability follow-up and
the deliberately narrow M8 post-closure supplement implemented. M8 makes
server-confirmed, unexecuted Plan outputs available in the Explorer and removes
a node-drag layout persistence race. Cycle 6 is the completed Copilot
foundation. Cycle 7 does not add autonomous Agent behavior or Plan proposal
acceptance; it concentrates on the frontend and the small API/state contracts
that make that frontend coherent.
