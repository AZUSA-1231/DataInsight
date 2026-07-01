# Plan: Audit Fix — Phase 1 (CRITICAL + Cascading HIGH)

**Source Audit**: `.claude/audits/audit-summary.md` (49 findings, 2026-07-01)
**Scope**: 3 CRITICAL + 3 cascading HIGH fixes
**Status**: ✅ Complete (2026-07-02)
**Complexity**: Medium

## Summary

Fix the 3 CRITICAL findings (C1 sandbox isolation, C2 prompt injection, C3 infinite loop)
plus 3 HIGH items that cascade directly from them (H2 AST guard, H4 path validation,
H6 input limits, H7 missing try/except). All changes are surgical — no architectural
refactoring.

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Naming | `preprocessing.py:133` | `*_node(state: AgentState) -> dict[str, object]` |
| Errors | `decision_match.py:213-215` | Return `{"error": "...", "feedback": None}`, never raise |
| Logging | `data_track.py:87` | `logger.info("Module: message %s", var)` at entry/exit |
| Tests | `test_preprocessing.py:49-57` | AAA pattern, `@pytest.mark.unit`, mock `get_llm`, assert prompt content |
| Immutability | `preprocessing.py:227-237` | Return `{**computed, "error": None}`, never mutate state |
| Subprocess | `executor.py:37-44` | `subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=120)` |

## Files to Change

| File | Action | Why |
|---|---|---|
| `src/sandbox/static_guard.py` | **CREATE** | New module: AST + regex scan of LLM-generated code before execution (C1, H2) |
| `src/agent/nodes/decision_match.py` | UPDATE | C3: add `"feedback": None` to except block (line 215) |
| `src/agent/nodes/data_track.py` | UPDATE | H7: wrap LLM call in try/except (lines 108-111) |
| `src/agent/nodes/preprocessing.py` | UPDATE | C1: integrate static_guard scan before `run_script()` |
| `src/agent/nodes/analysis.py` | UPDATE | C1: integrate static_guard scan before `run_script()` |
| `src/__main__.py` | UPDATE | C2, H4, H6: input sanitization, extension validation, length limits |
| `tests/test_static_guard.py` | **CREATE** | Tests for the new sandbox guard module |
| `tests/test_decision_match.py` | UPDATE | C3: test that feedback=None is set on LLM failure |
| `tests/test_data_track.py` | UPDATE | H7: test that LLM failure returns error dict |
| `tests/test_preprocessing.py` | UPDATE | C1: test that unsafe code is rejected before subprocess |
| `tests/test_analysis.py` | UPDATE | C1: test that unsafe code is rejected before subprocess |

## Tasks

### Phase 1: CRITICAL + Direct Cascading Fixes

### Task 1: C3 — Fix decision_match infinite loop (1 line)

- **Action**: In `decision_match.py:215`, add `"feedback": None` to the except-block return dict.
  Without this, `_should_iterate` in graph.py returns `"decision_match"` (feedback truthy from
  prior iteration), and the graph loops endlessly until LangGraph's recursion_limit kills it.
- **Mirror**: Line 233 already does this correctly in the JSON parse failure path —
  `return {"error": "...", "feedback": None}`. Copy that pattern.
- **Validate**: `pytest -v -k "decision_match"`

### Task 2: H7 — Wrap data_track LLM call in try/except (5 lines)

- **Action**: In `data_track.py:107-114`, wrap the LLM call in try/except. On failure,
  return `{"error": f"Data Track LLM error: {e}", "data_profile": data_profile}`.
  The data_profile is still valid (deterministic inspection succeeded), so downstream
  nodes can produce a partial report.
- **Mirror**: The LLM exception handlers in `preprocessing.py:187-196` and
  `analysis.py:197-206` — same pattern: log error, return error + partial result.
- **Validate**: `pytest -v -k "data_track"`

### Task 3: C1+H2 — Sandbox hardening (new module + integration)

- **Action**: Create `src/sandbox/static_guard.py` with:
  - `BANNED_PATTERNS: list[str]` — regex patterns for dangerous imports/calls
    (`requests\.`, `urllib`, `socket\.`, `subprocess\.`, `os\.system\(`,
    `shutil\.rmtree`, `os\.remove\(`, `os\.unlink\(`, `os\.rmdir\(`,
    `pathlib.*unlink`, `pathlib.*rmdir`, `eval\(`, `exec\(`, `compile\(`,
    `__import__\(`, `open\(.*/[a-z]` (absolute path reads outside working dir))
  - `BANNED_IMPORTS: set[str]` — exact module names to block
    (`requests`, `urllib.request`, `http.client`, `ftplib`, `telnetlib`,
    `smtplib`, `subprocess`, `socket`, `pickle`, `marshal`, `ctypes`, `code`)
  - `check_static(code: str) -> tuple[bool, str]` — AST parse + regex scan.
    Returns `(True, "")` if safe, `(False, "reason")` if rejected.
  - AST visitor that walks `Import`/`ImportFrom` nodes and checks against
    `BANNED_IMPORTS`.
  - Regex scan against `BANNED_PATTERNS` as a second layer (catches `eval()`,
    `__import__()`, dynamic calls that AST import check misses).
- **Integration points**:
  - `preprocessing.py:200` — after `mkstemp`, before `run_script`: call
    `check_static(code)`. If unsafe, append to attempts and return error (triggers
    ReAct retry — the LLM gets a chance to fix it).
  - `analysis.py:210` — same integration point, same pattern.
- **Mirror**: `executor.py` SandboxResult NamedTuple pattern for return types.
  Error handling follows the node convention: `state.error` + `attempts.append()`.
- **Validate**: `pytest -v -k "static_guard"` + `pytest -v -k "smoke"` (ensures
  legitimate scripts still pass through)

### Task 4: C2+H4+H6 — Input sanitization + prompt injection defense

- **Action**: Three changes in `__main__.py`:
  1. **Input sanitization** (`_sanitize_user_input(text: str, max_len: int) -> str`):
     - Strip markdown code fences (```), prompt injection delimiters
       (`---`, `===`, `### SYSTEM`, `### USER`, `<|im_start|>`, `<|im_end|>`)
     - Strip ASCII control chars below 0x20 (except `\n`, `\t`)
     - Truncate to `max_len`
  2. **Apply to both input paths**:
     - `args.requirement` → sanitize before `AgentState()` (line 245)
     - `feedback` from `input()` → sanitize before `model_copy(update=...)` (line 280)
  3. **File path validation**:
     - Add `choices`/validation to argparse: only `.csv`, `.xlsx`, `.xls` extensions
     - Resolve path to absolute, verify it's within current working tree
       (reject `../../etc/passwd` style traversal)
- **Mirror**: `_check_prerequisites()` fail-fast pattern — validate early, fail with
  clear `[ERROR]` message on stderr.
- **Validate**: `pytest -v -k "main"` (if tests exist) or manual: try `python -m src
  "../../etc/passwd" "requirement"` → should reject.

## Validation

```bash
# Unit tests for new + changed modules
pytest -v -k "static_guard or decision_match or data_track" -x

# Ensure existing tests still pass
pytest -v -x

# Lint + type check
ruff check .
mypy src/

# Smoke test (real subprocess path)
pytest -v -k "smoke"
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| AST scanner false-positive on legitimate pandas/sklearn code | Low | Only block explicitly dangerous imports (network, subprocess, filesystem destruction). Allow all data science packages. |
| `BANNED_IMPORTS` too narrow — LLM finds new dangerous module | Medium | Regex layer catches patterns regardless of import method. Defense in depth. |
| Input sanitization breaks valid Chinese text | Low | Only strip control chars and known injection delimiters. Chinese characters are all > 0x4E00. |
| ReAct retry loop now fires on static guard rejection (increasing LLM cost) | Low | Guard rejection is explicit in the error message — LLM should remove the banned import on next attempt. Max 3 retries unchanged. |

## Phase 2 (Next — HIGH fixes, separate plan)

- H1: CI/CD pipeline (`.github/workflows/ci.yml`)
- H3: Replace manual `.env` parser with `python-dotenv`
- H5: Temp file cleanup strategy
- H8: Empty `parsed_output: {}` distinction in report_gen
- H9: Extract shared `_extract_code_block` to `src/agent/utils.py`

## Phase 3 (Later — MEDIUM, separate plan)

- M15+M16: Deduplicate preprocessing/analysis node structure
- M1: `__main__.py` test coverage
- M10: `_load_dotenv` OSError logging
- Selected remaining MEDIUM items

## Acceptance

- [x] C3: `decision_match.py:215` returns `"feedback": None`
- [x] H7: `data_track.py` LLM call wrapped in try/except
- [x] C1+H2: `src/sandbox/static_guard.py` created with AST + regex scan
- [x] C1: `preprocessing.py` calls `check_static()` before `run_script()`
- [x] C1: `analysis.py` calls `check_static()` before `run_script()`
- [x] C2: User input sanitized (requirement + feedback paths)
- [x] H4: File extension + path traversal validation in argparse
- [x] H6: Input length limits enforced
- [x] All existing 81 tests pass + new tests for guard/sanitizer (97/97)
- [x] `ruff check .` + `mypy src/` clean
