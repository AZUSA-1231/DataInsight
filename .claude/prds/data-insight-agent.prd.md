# DataInsight — Progressive Data Analysis AI Agent

## Problem
Non-technical users (business analysts, students, developers unskilled in data engineering) face an extremely fragmented data analysis workflow: data morphology diagnosis (nulls, fake nulls, context-dependent zero values), missing-value strategy (mean/median imputation vs. deletion requires pre-judging field importance), model selection, debugging, and chart polishing — these steps are logically coupled and impose heavy cognitive load. Existing AI tools (ChatGPT, Copilot) tend to skip critical cleaning steps and jump straight to advanced modeling, producing unreliable results. **Without solving this, non-technical users are left choosing between expensive human data analysts and AI-generated reports that "look plausible but are wrong."**

## Evidence
- **First-hand experience**: The user's data mining course assignment required a full data science workflow — the data morphology diagnosis phase alone involved handling nulls, fake nulls (e.g. `"0"` strings), and context-sensitive special values (a `0` in one column might be meaningful but a missing-value sentinel in another). Every cleaning decision depended on pre-judging downstream analysis constraints. The entire pipeline was scattered and mentally exhausting.
- **Generalizability**: This is not an edge case — anyone working with raw data hits the same "data–business alignment gap."

## Users
- **Primary**: Non-technical users who need exploratory data analysis (EDA) — business analysts, product managers, students, domain experts. Trigger scenario: they have a CSV/Excel file and a business question ("Why did Q2 sales drop?"), and they need a trustworthy analysis report.
- **Not for**:
  - Professional data scientists who need fine-grained control over every pipeline stage (MVP does not expose manual intervention points)
  - Enterprise BI scenarios requiring live SQL database connections

## Hypothesis
We believe **a LangGraph-based state machine that enforces a four-stage pipeline — Parallel Dual-Track Assessment → Alignment & Trade-off → Sandbox Execution → Report Assembly** — will **enable non-technical users to produce defensible analysis reports in a single session**.
We'll know we're right when **≥80% of first-time analysis requests produce a valid report without human correction of data logic errors (cosmetic chart adjustments excluded)**.

## Success Metrics
| Metric | Target | How measured |
|---|---|---|
| First-shot report generation success rate | ≥ 80% | Sandbox code passes on first execution (no ReAct retry rounds > 1) |
| Data–business alignment disclosure coverage | 100% | Every report must contain a "Data & Business Alignment Notes" section |
| User correction rounds per session | ≤ 1 | Number of times the user requests a redo within one analysis session |
| Sandbox execution safety incidents | 0 | No unauthorized file access or network calls per execution |

## Scope

**MVP** — CLI entry point. User passes a CSV/Excel file path and a natural-language requirement. The agent executes the four-stage pipeline automatically and outputs a Markdown report (with embedded charts). Supports in-session iteration: the user can provide feedback on the report and the agent reuses cleaned data and prior analysis context for incremental revision.

**Out of scope**
- Web UI frontend — MVP is CLI-only; frontend is a later milestone
- SQL database connectors — MVP supports CSV/Excel files only
- Custom model training — all AI nodes use off-the-shelf LLM APIs orchestrated via LangChain/LangGraph
- Multi-user concurrency / session persistence — MVP is single-user, single-session
- Interactive chart editing — charts in reports are static images

## Delivery Milestones
<!-- Business outcomes, not engineering tasks. /plan turns each into a plan. -->
<!-- Status: pending | in-progress | complete -->

| # | Milestone | Outcome | Status | Plan |
|---|---|---|---|---|
| 1 | Four-stage state machine skeleton + Data Track node | User submits CSV + requirement → receives a *Data Technical Audit Report* | complete | [plan](../plans/data-insight-agent.plan.md) |
| 2 | Business Track + Decision Match node | Parallel dual-track complete → receives an *Analysis Execution Plan* | complete | [plan](../plans/data-insight-agent-m2.plan.md) |
| 3 | Sandbox execution + ReAct self-correction loop | Code runs successfully in sandbox, producing cleaned data + charts | complete | [plan](../plans/data-insight-agent-m3.plan.md) |
| 4 | Report assembly + in-session iteration | Full Markdown report delivered; user can request revisions within the session | complete | [plan](../plans/data-insight-agent-m4.plan.md) |

## Open Questions
- [ ] What is the CSV/Excel file size ceiling? How are sandbox memory limits defined?
- [ ] Sandbox security boundaries: are `subprocess`/`os.system` allowed? Is network access (`requests`/`urllib`) permitted?
- [ ] How are Chinese fonts (SimHei/WenQuanYi) pre-installed in the sandbox Docker image? What is the fallback if they are missing?
- [ ] What form does user dissatisfaction feedback take — free-text or structured options ("chart is wrong" / "conclusion is wrong")?
- [ ] LLM provider strategy: same model for all stages, or cheaper models for data auditing and stronger models for business reasoning?
- [ ] Excel multi-sheet scenario: default to the first sheet only, or let the user specify?

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM hallucinates non-existent data features during audit phase | Medium | High — downstream pipeline is corrupted | Data Track uses a deterministic script to produce structured metadata; LLM only interprets, never computes |
| Sandbox code execution timeout or infinite loop | Medium | Medium — poor UX | Sandbox execution capped with timeout (e.g. 120s); timeout triggers ReAct retry |
| Chinese font missing in sandbox → garbled chart text | High | Medium — report unreadable | Hardcoded font fallback in generated code + Dockerfile pre-installs Chinese font packages |
| User expects "one-click magic" but agent enforces a deliberate multi-stage process | Low | Medium — user may perceive the flow as slow | Real-time stage progress feedback so the user understands the value of each phase |

---
*Status: DRAFT — requirements only. Implementation planning pending via /plan.*
