# Plan: Audit Fix — Phase 3 (Backlog)

**Source Audit**: `.claude/audits/audit-summary.md` (49 findings, 2026-07-01)
**Scope**: 20 MEDIUM + 15 LOW remaining (post Phase 1+2)
**Status**: 📋 Backlog — deferred, revisit as development demands
**Complexity**: Varies (Small to Medium)

## Summary

Phase 1+2 resolved all 3 CRITICAL, all 9 HIGH, and 2 LOW findings. The remaining
35 items are defense-in-depth, maintainability, and polish — none block production
use or sharing. This document is a reference, not a work plan. Pick items as they
become painful rather than working through a checklist.

## Priority Tiers

### Tier A — Worth doing soon (high value, low cost)

| ID | Finding | Cost | Why bother |
|---|---|---|---|
| M10 | `_load_dotenv` silently swallows OSError | 1 line | Data loss risk — if .env is corrupt, you'd never know |
| M2 | Run bandit security scan | 1 command | Catches regressions in CI; already wired in CI.yml |
| M7 | Error messages leak internal filesystem paths | ~5 lines | Privacy for shared reports |
| M12 | Error messages truncated to 500 chars | 1 line | Losing stack traces during debugging |

### Tier B — Before major refactoring (medium value, medium cost)

| ID | Finding | Cost | Trigger |
|---|---|---|---|
| M15+M16 | Deduplicate preprocessing/analysis node structure (~70% overlap) | ~100 lines | When adding a third sandbox node or changing the ReAct loop |
| M19 | `execution_plan: object` → `ExecutionPlan` type | ~5 files | When type-checking becomes noisy |
| M20 | Test fixtures return `object` → concrete types | ~3 files | Same as above |
| M13 | `_should_retry_analysis` no defense for empty-result + no-error | ~10 lines | If you see ReAct loops that shouldn't happen |
| M14 | `cleaned_data_path: ""` silently falls through to raw data | ~5 lines | When silent fallback causes confusing results |

### Tier C — Nice to have (low value or speculative)

| ID | Finding | Notes |
|---|---|---|
| M1 | `__main__.py` 0% test coverage | CLI test is hard to mock; wait until CLI stabilizes |
| M3 | Temp file lifecycle management | Partially addressed by H5 atexit cleanup |
| M4 | Inspection script path resolution fragile | Only matters if running from non-project-root |
| M5 | Output path derived from user input | Low risk after Phase 1 path validation |
| M6 | LLM model/base URL printed to stdout | Minor info leak; useful for debugging |
| M8 | Unbounded JSON parsing from LLM output | Python json.loads is already memory-safe |
| M9 | PII sent to external LLM without warning | Add a console warning before first LLM call |
| M11 | CLI doesn't explicitly warn on partial report | Low UX pain |
| M17 | `_save_intermediates` 85 lines, 3 responsibilities | Refactor when it grows past 200 |
| M18 | Empty `__init__.py` placeholder dirs | Remove when project structure stabilizes |

### Tier D — LOW items (defer indefinitely)

All 15 remaining LOW items. Key ones worth remembering:

| ID | Finding | Trigger to fix |
|---|---|---|
| L5 | No feedback iteration limit | If someone writes a bot that loops forever |
| L6 | LLM failure in node loses attempt history | If debugging LLM flakes becomes common |
| L13 | `main()` 90 lines with duplicated run+save | When adding a third iteration mode |

## When to Revisit

- **Before publishing to PyPI**: Tier A
- **Before adding a new pipeline stage** (e.g., Stage 5 validation): Tier B (M15+M16)
- **Before onboarding a second developer**: Tier C (M1, M9)
- **Otherwise**: let it be

## Audit Status Summary

| Severity | Total | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 3 | 3 | 0 |
| HIGH | 9 | 9 | 0 |
| MEDIUM | 20 | 0 | 20 |
| LOW | 17 | 2 | 15 |
| **Total** | **49** | **14** | **35** |
