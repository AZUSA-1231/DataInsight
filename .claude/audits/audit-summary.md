# Audit Summary: DataInsight V2.1 — First Audit Phase

**Date**: 2026-07-01
**Scope**: Full codebase (19 source files, 10 test files, 1 configuration)
**Methodology**: 4-audit layered approach (L1-L3)

---

## Overall Score: 72/100 (L1) → 58/100 (Post-L2 findings)

L1 production-audit baseline was 72. L2 security and silent-failure audits revealed
additional CRITICAL and HIGH findings that would lower the score further under
production-audit scoring rules (security findings cap score at 69, missing guardrails).

---

## Consolidated Findings by Severity

### CRITICAL (3) — Must fix before external use

| ID | Finding | Source | Layer |
|----|---------|--------|-------|
| C1 | **LLM-generated code executes with zero sandbox isolation** | `executor.py:38-45` | L2a |
| | subprocess.run with no network/filesystem/memory isolation. Prompt-based constraints are advisory only. | | |
| C2 | **Prompt injection chain: user input → code generation** | `__main__.py` → `business_track` → `decision_match` → `preprocessing/analysis` | L2a |
| | Raw user requirement/feedback reaches code-gen prompts without sanitization | | |
| C3 | **Feedback loop infinite cycle on decision_match LLM failure** | `decision_match.py:213-215` | L2b |
| | Except block returns error but forgets `feedback: None`; `_should_iterate` routes back forever until recursion_limit hits | | |

### HIGH (9) — Should fix before sharing with others

| ID | Finding | Source | Layer |
|----|---------|--------|-------|
| H1 | **No CI/CD pipeline** | `.github/` absent | L1 |
| H2 | **No AST static analysis of LLM-generated code** | `preprocessing.py:200`, `analysis.py:210` | L2a, L1 |
| H3 | **Manual .env parser has edge-case bugs** | `llm.py:11-28` | L2a |
| H4 | **No file path restrictions or extension validation** | `__main__.py:60` | L2a |
| H5 | **Temp files/dirs never cleaned up** | `preprocessing.py:168`, `analysis.py:180` | L2a |
| H6 | **No input length limits** | `__main__.py:75,282` | L2a |
| H7 | **`data_track_node` missing LLM try/except** | `data_track.py:108-111` | L2b, L3 |
| H8 | **Empty analysis_result misdiagnosed as failure** | `report_gen.py:211` | L2b |
| H9 | **`_extract_code_block` defined identically in 2 files** | `preprocessing.py:16`, `analysis.py:16` | L3 |

### MEDIUM (20) — Defense-in-depth improvements

| ID | Finding | Source | Layer |
|----|---------|--------|-------|
| M1 | `__main__.py` 0% test coverage | `__main__.py` | L1 |
| M2 | Run bandit security scan | — | L1 |
| M3 | Temp file lifecycle management | `preprocessing.py`, `analysis.py` | L1 |
| M4 | Inspection script path resolution fragile | `data_track.py:13` | L1 |
| M5 | Output path derived from user input | `__main__.py:241` | L2a |
| M6 | LLM model/base URL printed to stdout | `__main__.py:54-55` | L2a |
| M7 | Error messages leak internal filesystem paths | `preprocessing.py:251`, `analysis.py:261` | L2a |
| M8 | Unbounded JSON parsing from LLM output | All nodes | L2a |
| M9 | PII sent to external LLM without warning | All prompt builders | L2a |
| M10 | `_load_dotenv` silently swallows OSError | `llm.py:29-30` | L2b |
| M11 | CLI doesn't explicitly warn on partial report | `__main__.py:261-272` | L2b |
| M12 | Error messages truncated to 500 chars, losing diagnostics | `preprocessing.py:251`, `analysis.py:261` | L2b |
| M13 | `_should_retry_analysis` no defense for empty result + no error | `graph.py:28-32` | L2b |
| M14 | `cleaned_data_path: ""` silently falls through to raw data | `analysis.py:168-174` | L2b |
| M15 | Preprocessing/analysis node structural duplication (~70%) | `preprocessing.py`, `analysis.py` | L3 |
| M16 | LLM invocation pattern repeated 6 times | All 6 nodes | L3 |
| M17 | `_save_intermediates` 85 lines, 3 responsibilities | `__main__.py:106-196` | L3 |
| M18 | Empty `__init__.py` placeholder dirs (analysis, api, report) | `src/*/` | L3 |
| M19 | `execution_plan: object` type — should be `ExecutionPlan` | `preprocessing.py:24`, `analysis.py:24` | L3 |
| M20 | Test fixtures return `object` instead of concrete types | `conftest.py` | L3 |

### LOW (17) — Nice to have

<details>
<summary>Expand</summary>

| ID | Finding | Layer |
|----|---------|-------|
| L1 | No file extension validation in argparse | L2a |
| L2 | No signal handler for graceful Ctrl+C cleanup | L2a |
| L3 | `.env` resolved relative to CWD, not project root | L2a |
| L4 | `_extract_json()` fragile heuristic fallback | L2a |
| L5 | No feedback iteration limit | L2a |
| L6 | LLM failure in node loses attempt history | L2b |
| L7 | `_save_intermediates` silently passes on OSError | L2b |
| L8 | `_extract_json` debug log truncates raw output | L2b |
| L9 | TimeoutExpired handler .decode() without explicit encoding | L2b |
| L10 | `_build_clean_code_prompt` misleading "clean" prefix | L3 |
| L11 | Abbreviated variable names `pre_result` / `an_result` | L3 |
| L12 | `set_llm_env` could be autouse=True | L3 |
| L13 | `main()` function 90 lines with duplicated run+save logic | L3 |
| L14 | `_build_decision_prompt` / `_with_feedback` 80% duplicated | L3 |
| L15 | Node return types could use TypedDict | L3 |
| L16 | scipy/scikit-learn hard deps only used by LLM code | L3 |
| L17 | `_extract_code_block` tests duplicated in 2 test files | L3 |

</details>

---

## Fix Priority Matrix

Immediate (before external use):
```
C1 → H2: Sandbox hardening (AST scan + Docker/nsjail)
C2 → H6: Input sanitization + prompt injection defense
C3:       decision_match except block fix (1 line)
H7:       data_track_node try/except (5 lines)
```

Short-term (before sharing project with other developers):
```
H1: CI/CD pipeline
H3: Replace manual .env parser with python-dotenv
H4: File path validation
H5: Temp file cleanup strategy
H8: Empty-result vs error distinction in report_gen
H9: Extract shared _extract_code_block
```

Medium-term (improve maintainability):
```
M1-M20: Incremental improvements as time allows
Priority: M15+M16 (de-duplication) would eliminate ~100 lines of repeated code
```

---

## Audit Trail

| Layer | Source | Report | Date |
|-------|--------|--------|------|
| L1 | production-audit skill | [production-audit-v1.md](production-audit-v1.md) | 2026-07-01 |
| L2a | security-reviewer agent | (embedded above) | 2026-07-01 |
| L2b | silent-failure-hunter agent | (embedded above) | 2026-07-01 |
| L3 | code-reviewer agent | (embedded above) | 2026-07-01 |

## Related

- [decisions.md](../decisions.md) — 32 architecture decisions
- [data-insight-agent-v2.plan.md](../plans/data-insight-agent-v2.plan.md) — V2 refactor plan
- [data-insight-agent-v2.1-plan.md](../plans/data-insight-agent-v2.1-plan.md) — V2.1 test hardening
