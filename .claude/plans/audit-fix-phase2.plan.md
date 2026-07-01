# Plan: Audit Fix — Phase 2 (HIGH + Cascading LOW)

**Source Audit**: `.claude/audits/audit-summary.md` (49 findings, 2026-07-01)
**Scope**: 5 HIGH fixes (H1, H3, H5, H8, H9) + 2 cascading LOW items (L12, L17)
**Status**: ✅ Complete (2026-07-02)
**Complexity**: Medium

## Summary

Fix the remaining 5 HIGH findings after Phase 1 completed the 3 CRITICAL + 3 HIGH items.
H1 adds CI/CD pipeline; H3 replaces the bug-prone manual `.env` parser with `python-dotenv`;
H5 adds atexit-based temp file/dir cleanup; H8 fixes `bool({})` false-negative in report_gen;
H9 extracts the duplicated `_extract_code_block` to a shared `src/agent/utils.py` module.
Two cascading LOW fixes are included: L12 (autouse test fixture) and L17 (deduplicate tests).

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Naming | `src/agent/nodes/` | `_private_helper()`, `*_node(state) -> dict[str, object]` |
| Errors | `decision_match.py:215` | Return `{"error": "...", "field": None}` dict, never raise |
| Logging | `data_track.py:87` | `logger.info("Module: message %s", var)` |
| Tests | `tests/test_preprocessing.py` | AAA, `@pytest.mark.unit`, `@pytest.mark.integration` |
| Imports | `src/agent/__init__.py` | Empty init, absolute imports throughout |

## Files to Change

| File | Action | Why |
|---|---|---|
| `.github/workflows/ci.yml` | **CREATE** | H1: CI/CD pipeline (lint, type-check, test matrix) |
| `src/agent/utils.py` | **CREATE** | H9: Single home for `_extract_code_block` |
| `src/agent/nodes/preprocessing.py` | UPDATE | H9: remove local `_extract_code_block`, import from utils |
| `src/agent/nodes/analysis.py` | UPDATE | H9: remove local `_extract_code_block`, import from utils |
| `src/agent/llm.py` | UPDATE | H3: replace `_load_dotenv` with `python-dotenv` |
| `src/agent/nodes/report_gen.py` | UPDATE | H8: fix `has_results` to distinguish `{}` from missing |
| `src/agent/nodes/preprocessing.py` | UPDATE | H5: register temp dirs/files for atexit cleanup |
| `src/agent/nodes/analysis.py` | UPDATE | H5: register temp dirs/files for atexit cleanup |
| `src/sandbox/executor.py` | UPDATE | H5: register temp scripts for atexit cleanup |
| `pyproject.toml` | UPDATE | H3: add `python-dotenv` dependency |
| `tests/test_utils.py` | **CREATE** | H9+L17: single home for `_extract_code_block` tests |
| `tests/conftest.py` | UPDATE | L12: make `set_llm_env` autouse |
| `tests/test_preprocessing.py` | UPDATE | L17: remove duplicated `_extract_code_block` tests |
| `tests/test_analysis.py` | UPDATE | L17: remove duplicated `_extract_code_block` tests |

## Tasks

### Task 1: H9+L17 — Extract shared `_extract_code_block` to `src/agent/utils.py`

- **Action**: Create `src/agent/utils.py` with the single function `_extract_code_block(text: str) -> str`.
  In both `preprocessing.py` and `analysis.py`, delete the local definition and import from `src.agent.utils`.
  In tests, create `tests/test_utils.py` with the 3 existing test cases, remove duplicates from
  `test_preprocessing.py` and `test_analysis.py`, update their imports.
- **Mirror**: Same function signature, same regex, same behavior. No refactoring — pure extraction.
- **Validate**: `pytest -v -k "extract_code_block"` (should go from 6 to 3 tests, all passing)

### Task 2: H3+L12 — Replace manual `.env` parser with `python-dotenv`

- **Action**:
  1. Add `python-dotenv>=1.0.0` to `pyproject.toml` dependencies.
  2. In `llm.py`, replace `_load_dotenv()` body with `from dotenv import load_dotenv; load_dotenv(override=False)`.
  3. Keep the function name for backward compat, but it becomes a thin wrapper.
  4. In `conftest.py`, add `@pytest.fixture(autouse=True)` to `set_llm_env` (L12) so every test
     automatically gets mock env vars — no need to add it to every test module.
- **Mirror**: ECC Python security rule explicitly recommends `python-dotenv` for secret management.
- **Validate**: `pytest -v -x` (all tests pass without explicit `set_llm_env` in test modules)

### Task 3: H5 — Temp file cleanup via atexit

- **Action**: Add a module-level `_TEMP_PATHS: list[str] = []` list and `_cleanup_temp_paths()` function
  registered via `atexit.register()`. The cleanup function iterates `_TEMP_PATHS`, removes files
  with `os.unlink()` and directories with `shutil.rmtree()`, silently passing on OSError.
  Register temp dirs (from `tempfile.mkdtemp()`) and temp scripts (from `tempfile.mkstemp()`) in:
  - `preprocessing.py`: output_dir + script_path
  - `analysis.py`: output_dir + script_path
  - `executor.py`: script_path (after `mkstemp`, before `run_script`)
- **Mirror**: `_save_intermediates` already uses `try/except OSError: pass` for cleanup-like ops.
- **Validate**: `pytest -v -k "smoke"` (temp dirs should be cleaned after test run)

### Task 4: H8 — Fix `has_results` to distinguish empty `{}` from missing result

- **Action**: In `report_gen.py:211`, change:
  ```python
  has_results = bool(analysis_result.get("parsed_output") and not error)
  ```
  to:
  ```python
  has_results = "parsed_output" in analysis_result and not error
  ```
  `bool({})` is `False`, so a successful analysis that legitimately returns empty results
  (e.g., no charts, no statistics, no insights) was incorrectly routed to the partial
  report path. Using `"parsed_output" in analysis_result` correctly checks for presence.
- **Mirror**: Line 14 already uses `if "parsed_output" in analysis_result` correctly.
- **Validate**: `pytest -v -k "report_gen"`

### Task 5: H1 — CI/CD pipeline

- **Action**: Create `.github/workflows/ci.yml` with:
  - **Trigger**: push to `main`, pull_request to `main`
  - **Matrix**: Python `["3.12", "3.13"]`
  - **Steps**: checkout → setup-python → install `.[dev]` + `python-dotenv` →
    ruff check → mypy src/ → pytest -v --cov=src --cov-report=term-missing
  - **Timeout**: 10 minutes
  - Use `PYTEST_ADDOPTS: "--color=yes"` for readable CI output
- **Mirror**: Standard GitHub Actions Python workflow. Project already has all the tool
  config in `pyproject.toml` — CI just runs the commands.
- **Validate**: `act push` (local) or merge to main (GitHub). Cannot fully validate
  locally without `act` installed; verify YAML syntax with a quick parse check.

## Validation

```bash
# All existing tests must pass
pytest -v -x

# _extract_code_block tests deduplicated (3 tests, not 6)
pytest -v -k "extract_code_block"

# Temp cleanup works (smoke test creates real temp dirs)
pytest -v -k "smoke"

# Lint + type check
ruff check .
mypy src/

# python-dotenv importable
python -c "import dotenv; print(dotenv.__version__)"
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `python-dotenv` load order differs from manual parser | Low | `load_dotenv(override=False)` matches existing behavior (env vars win) |
| atexit cleanup removes files still in use on Windows | Low | Cleanup only fires at process exit; subprocess already completed |
| `"parsed_output" in analysis_result` changes behavior for missing key | None | This is the fix — the old behavior was the bug |
| CI YAML syntax error | Low | Validate with `python -c "import yaml; yaml.safe_load(open(...))"` |

## Acceptance

- [x] H9: `_extract_code_block` lives in `src/agent/utils.py` only
- [x] L17: Tests deduplicated — 3 `extract_code_block` tests in `test_utils.py`, 0 elsewhere
- [x] H3: `llm.py` uses `python-dotenv`, manual parser removed
- [x] L12: `conftest.py` `set_llm_env` is `autouse=True`
- [x] H5: `atexit` handler registered, temp files/dirs cleaned on exit
- [x] H8: `report_gen.py:211` uses `"parsed_output" in analysis_result`
- [x] H1: `.github/workflows/ci.yml` created with lint+type+test matrix
- [x] All existing tests pass + new utils tests (94/94)
- [x] `ruff check .` + `mypy src/` clean
