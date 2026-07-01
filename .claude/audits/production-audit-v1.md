# Production Audit: DataInsight V2.1

**Date**: 2026-07-01
**Audit type**: Production Readiness (Layer 1 — Comprehensive)
**Scope**: Full codebase after V2 refactor + V2.1 test hardening
**Methodology**: [production-audit skill](C:\Users\YANdz\.claude\skills\ecc\production-audit\SKILL.md)

---

## Score: 72/100 — Launchable with Caveats

The core pipeline is solid: 81 tests passing, ruff + mypy clean, structured Pydantic state,
dual ReAct retry loops with partial-report fallback. Three HIGH items prevent a higher score:
no CI, sandbox lacks network/filesystem isolation, and LLM-generated code runs without
static analysis.

---

## Blockers

_None. No authentication bypass, no secrets exposure, no data corruption risk, no
missing rollback path (CLI tool — not applicable)._

---

## High-Value Fixes

### H1 — Add CI/CD pipeline

**Risk**: No automated testing on push/PR. Code quality relies entirely on developer
discipline (pre-commit hooks not configured).

**Fix**: Add `.github/workflows/ci.yml`:
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: ruff format --check .
      - run: mypy src/
      - run: pytest -v
```

**Why HIGH**: Without CI, regressions are only caught when someone manually runs tests.
This is the single biggest operational gap.

### H2 — Sandbox hardening: network guard

**Risk**: LLM-generated code runs in `subprocess.run()` with no network restrictions
(decision D2). A compromised or hallucinating LLM could generate code that exfiltrates
data via `requests.post()` or `socket`.

**Fix**: Add a pre-execution static scan that rejects scripts containing banned patterns:
```python
_BANNED_PATTERNS = [
    r"requests\.",
    r"urllib",
    r"socket\.",
    r"subprocess\.",
    r"os\.system\(",
    r"shutil\.rmtree",
    r"os\.remove\(",
]
```
Reject the script before sandbox execution if any pattern matches. The prompt already
tells the LLM "NO network calls, NO subprocess" but this is advisory only (D17).

**Why HIGH**: The prompt constraint is a nudge, not enforcement. A static guard is
defense-in-depth — cheap to implement, zero false positives for legitimate analysis.

### H3 — Sandbox hardening: filesystem guard

**Risk**: Generated code can read arbitrary files on the system (`open("/etc/passwd")`)
or write outside the temp directory.

**Fix**: At minimum, scan for file read/write outside sanctioned paths. Longer-term,
evaluate `restrictedpython` or a Docker sandbox (already noted in D2).

**Why HIGH**: Same "prompt nudge vs. enforcement" gap as H2.

---

## Medium-Value Fixes

### M1 — `__main__.py` test coverage (currently 0%)

The CLI entry point has 182 statements at 0% coverage. While it's mostly glue code
(argparse + print + file I/O), the feedback loop logic (lines 278-315) and
`_save_intermediates` (lines 106-196) have enough branching to warrant tests.

**Fix**: Add 3-5 integration tests that mock `build_graph()` and verify:
- `--output` flag writes to the correct path
- `--save-intermediates` creates the expected files
- Feedback loop exits on empty input
- Missing `.env` prints correct error message

### M2 — Run `bandit` security scan

Python security linter not yet run on this codebase:
```bash
pip install bandit && bandit -r src/
```

Expected findings: `subprocess.run()` with user-influenced args (sandbox/executor.py
— but this is by design since we intentionally run LLM-generated code). The `assert`
statements in llm.py may also flag (bandit B101) — these are safe because they guard
validated-just-above None values.

### M3 — Temp file lifecycle

Generated scripts accumulate in OS temp directory (decision D13). For a CLI tool used
occasionally this is fine, but add a `--cleanup` flag or auto-delete scripts older
than 7 days.

### M4 — Inspection script path resolution

`_INSPECTION_SCRIPT` uses `os.path.join(__file__, "..", "..", "sandbox", ...)` which
is fragile (decision D3). Replace with `importlib.resources` or at minimum
`Path(__file__).resolve().parents[2] / "sandbox" / "inspection_script.py"`.

---

## Evidence Checked

| Category | Files | Status |
|----------|-------|--------|
| Git state | `git status --short --branch`, `git log --oneline -20` | Clean working tree, 17 commits on master |
| Secrets | `.env`, `.env.example`, `src/agent/llm.py` | `.env` git-ignored, manual parser, no hardcoded keys |
| Sandbox security | `src/sandbox/executor.py`, `src/agent/nodes/preprocessing.py`, `src/agent/nodes/analysis.py` | Subprocess only, prompt-based constraints, no static guard |
| State integrity | `src/agent/state.py` | Pydantic BaseModel, Optional fields with None defaults |
| Pipeline graph | `src/agent/graph.py` | 6 nodes, dual ReAct retry (max 3), partial report fallback, feedback loop |
| Error handling | All 6 node files | `state.error` pattern, never raise, downstream checks |
| LLM config | `src/agent/llm.py` | Fail-fast on missing env vars, timeout=120s, max_retries=1 |
| Data inspection | `src/sandbox/inspection_script.py` | Deterministic (not LLM), 6-encoding fallback chain |
| Test suite | `pytest -v`, `pytest --cov=src` | 81/81 passing, 67% coverage, core nodes 92-100% |
| Lint & type | `ruff check .`, `mypy src/` | All clean |
| CI/CD | `.github/` | **Absent** — no workflows |
| Docker | `Dockerfile*` | **Absent** — intentional (D2) |
| Dependencies | `pyproject.toml` | Pinned with `>=`, dev deps separate |
| Documentation | `CLAUDE.md`, `.env.example`, `decisions.md` | Clear quick start, 32 architecture decisions documented |

---

## Evidence Missing

- **No E2E test with real LLM** — All 81 tests mock the LLM. A real end-to-end run
  (with actual API call) would validate the full integration chain. Mitigated by the
  smoke test (test_smoke.py) which uses real subprocess with mock LLM output.
- **No performance benchmarks** — No data on how the pipeline performs with 100K+ row
  datasets under various LLM providers.
- **No Windows-specific CI** — The project explicitly handles Windows encoding issues
  (D8, D16) but CI would only run on ubuntu-latest. Consider a Windows matrix entry.
- **No bandit scan results** — Python security linter not yet executed.

---

## Strengths

1. **Error resilience**: Every node signals errors via `state.error` rather than
   crashing. Dual ReAct loops (preprocessing + analysis, max 3 each) with partial
   report fallback. This is production-grade error handling.
2. **Type safety**: Pydantic AgentState with mypy strict. Runtime validation catches
   shape errors that TypedDict silently allowed in MVP.
3. **Test quality**: 81 tests, AAA pattern, `make_execution_plan` factory with
   `is not None` sentinel pattern, smoke test for real sandbox. Lessons from
   Phase 3-4 bugs (L1-L4) have been systematically addressed.
4. **Architecture decisions documented**: 32 decisions in `decisions.md` covering
   sandbox trade-offs, encoding strategy, retry design, and migration rationale.
5. **Defense in depth for encoding**: 6-encoding detection chain, `errors="replace"`
   on subprocess output, `or ""` guards on stdout/stderr. This is hard-won Windows
   robustness.
6. **Clean dependency management**: `pyproject.toml` with `[project.optional-dependencies]`
   for dev tooling. No unused or unversioned dependencies.

---

## Risk Lenses Assessment

### Security & Auth

| Check | Status | Notes |
|-------|--------|-------|
| Secrets out of code | PASS | `.env` file, manual parser, git-ignored |
| Auth enforced server-side | N/A | CLI tool, no server |
| Rate limiting | N/A | CLI tool |
| CSRF / CORS | N/A | CLI tool |
| AI prompt injection defense | PARTIAL | Prompt tells LLM "no network, no subprocess" but no enforcement |
| Upload validation | N/A | File path from CLI args, validated with `Path.exists()` |

### Data Integrity

| Check | Status | Notes |
|-------|--------|-------|
| Migrations forward clean | N/A | No database |
| Idempotent retries | PASS | ReAct retries are idempotent (fresh temp dir each attempt) |
| Data flow integrity | PASS | Pydantic models enforce schema at each stage |

### Operations

| Check | Status | Notes |
|-------|--------|-------|
| Start from clean checkout | PASS | `pip install -e ".[dev]"` documented in CLAUDE.md |
| Required env vars validated | PASS | `_check_prerequisites()` fail-fast with clear messages |
| Health check | N/A | CLI tool |
| Deploy/rollback docs | N/A | CLI tool |
| CI/CD | FAIL | No `.github/workflows/` |
| Logging | PASS | `logger.info/error` with char counts, structured format |

### User Experience

| Check | Status | Notes |
|-------|--------|-------|
| Critical paths tested | PASS | Full pipeline integration tests |
| Loading/empty/error states | PASS | Streaming progress display, clear error messages |
| Support path on failure | PASS | Partial report on error, feedback loop for iteration |

---

## Next Action

Start with H1 (CI/CD pipeline) — it's the cheapest to implement and provides immediate
value by running on the next push. Then H2 (network guard) which is ~15 lines of regex
and eliminates the highest-severity sandbox risk.

Want me to implement H1 + H2 now?
