from __future__ import annotations

import json
import logging

from src.agent.llm import get_llm
from src.agent.state import AgentState

logger = logging.getLogger(__name__)


def _serialize_execution_result(execution_result: dict[str, object]) -> str:
    """Serialize execution_result for inclusion in the report prompt."""
    if "parsed_output" in execution_result:
        return json.dumps(execution_result["parsed_output"], ensure_ascii=False, indent=2)
    return json.dumps(execution_result, ensure_ascii=False, indent=2, default=str)


def _build_full_report_prompt(
    data_report: str,
    business_plan: str,
    execution_plan: str,
    execution_result_json: str,
    user_requirement: str,
) -> str:
    return f"""You are a senior data analysis report writer. Assemble a comprehensive,
reader-friendly Markdown report from the four analysis-stage outputs below.

CRITICAL RULES:
1. Write the report in Chinese — all headings and body text.
2. Use the EXACT section structure specified below. Do not skip any section.
3. Condense, don't copy-paste. The inputs can be long; summarize key points.
4. The "数据与业务对齐备忘" section is MANDATORY per our quality standards.
5. Be honest about limitations — do not exaggerate confidence.

Report structure (use exactly these headings):

# DataInsight 数据分析报告

## 执行摘要
3-5 sentence summary: what was analyzed, key findings, and the bottom-line answer
to the user's question.

## 1. 数据技术审计
Summarize the Data Technical Audit:
- Data quality grade and key issues
- Columns with high missing rates
- Columns requiring aggressive cleaning

## 2. 业务分析框架
Summarize the Business Analysis Blueprint:
- Core business question restated
- Ideal KPIs and metrics (哪些是核心指标)
- Analysis dimensions and comparison baselines

## 3. 分析执行与结果
From the execution results:
- What cleaning actions were performed
- Key statistical findings
- Chart descriptions and what each reveals
- Notable insights discovered

## 4. 数据与业务对齐备忘 ← MANDATORY
- What the business wanted to know vs. what the data could actually answer
- Gaps between ideal metrics and available data
- Trade-offs and proxy metrics used
- Assumptions made in the analysis
- Honesty statement: "基于当前数据，本报告[能够/无法完全]回答用户问题，原因在于..."

## 5. 图表清单
List all generated charts with brief descriptions.

## 6. 局限性与后续建议
- Limitations of the current analysis
- What additional data would improve it
- Suggested next steps for the user

---

**DATA TECHNICAL AUDIT REPORT:**

{data_report}

---

**BUSINESS ANALYSIS BLUEPRINT:**

{business_plan}

---

**ANALYSIS EXECUTION PLAN:**

{execution_plan}

---

**EXECUTION RESULTS (JSON):**

{execution_result_json}

---

**USER'S ORIGINAL QUESTION:**

{user_requirement}
"""


def _build_partial_report_prompt(
    data_report: str,
    business_plan: str,
    execution_plan: str,
    error_message: str,
    user_requirement: str,
) -> str:
    return f"""You are a senior data analysis report writer. The analysis pipeline
encountered an ERROR during the execution phase (sandbox code generation/execution).
Generate a PARTIAL report with what we have — the data audit, business analysis,
and execution plan are still valuable.

CRITICAL RULES:
1. Write in Chinese. Clearly mark the report as **[部分报告 — 分析执行未完成]**.
2. Explain what failed in plain language so a non-technical reader understands.
3. The "数据与业务对齐备忘" section is STILL mandatory.

Report structure:

# DataInsight 数据分析报告 [部分报告]

## 执行摘要
Explain: the pipeline completed data auditing and business analysis successfully,
but the automated code execution phase failed. The report below contains all
pre-execution findings.

## 1. 数据技术审计
(Summarize data_report)

## 2. 业务分析框架
(Summarize business_plan)

## 3. 分析执行计划 (未执行)
(Summarize execution_plan — what WAS planned but not run)

## 4. 执行错误说明
Explain the error in accessible terms:
- What went wrong during code execution
- Whether this is a data issue or a system issue
- What the user can try (rephrase requirement? clean data manually?)

Error details: {error_message}

## 5. 数据与业务对齐备忘 ← MANDATORY
(Based on data audit + business analysis — what we know even without execution)

## 6. 后续建议
What the user can do next.

---

**DATA TECHNICAL AUDIT REPORT:**

{data_report}

---

**BUSINESS ANALYSIS BLUEPRINT:**

{business_plan}

---

**ANALYSIS EXECUTION PLAN:**

{execution_plan}

---

**USER'S ORIGINAL QUESTION:**

{user_requirement}
"""


def report_gen_node(state: AgentState) -> AgentState:
    """Stage 4 — Report Generation: assemble Markdown report with mandatory alignment notes.

    Reads: state["data_report"], state["business_plan"], state["execution_plan"],
           state["execution_result"], state["error"], state["user_requirement"]
    Writes: state["final_report"]
    """
    data_report = state.get("data_report", "")
    business_plan = state.get("business_plan", "")
    execution_plan = state.get("execution_plan", "")
    execution_result = state.get("execution_result", {})
    error = state.get("error")
    user_requirement = state["user_requirement"]

    has_execution_results = bool(
        execution_result.get("parsed_output") and not error
    )

    if has_execution_results:
        logger.info("Report Gen: assembling full report")
        result_json = _serialize_execution_result(execution_result)
        prompt = _build_full_report_prompt(
            data_report, business_plan, execution_plan, result_json, user_requirement
        )
    else:
        logger.info("Report Gen: assembling partial report (execution failed or missing)")
        error_msg = error or "Execution did not produce results."
        prompt = _build_partial_report_prompt(
            data_report, business_plan, execution_plan, error_msg, user_requirement
        )

    try:
        llm = get_llm(temperature=0)
        response = llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        final_report = raw if isinstance(raw, str) else str(raw)
    except Exception as e:
        logger.error("Report Gen: LLM call failed: %s", e)
        return {**state, "error": f"Report Gen LLM error: {e}"}

    logger.info("Report Gen: report generated (%d chars)", len(final_report))
    return {**state, "final_report": final_report}
