from __future__ import annotations

import json
import logging

from src.agent.llm import get_llm
from src.agent.state import AgentState

logger = logging.getLogger(__name__)


def _serialize_analysis_result(analysis_result: dict[str, object]) -> str:
    """Serialize analysis_result.parsed_output for inclusion in the report prompt."""
    if "parsed_output" in analysis_result:
        return json.dumps(analysis_result["parsed_output"], ensure_ascii=False, indent=2)
    return json.dumps(analysis_result, ensure_ascii=False, indent=2, default=str)


def _build_full_report_prompt(
    cleaning_insights: str,
    data_profile_json: str,
    analysis_intent_json: str,
    alignment_notes: str,
    analysis_result_json: str,
    user_requirement: str,
) -> str:
    return f"""You are a senior data analysis report writer. Assemble a comprehensive,
reader-friendly Markdown report from the structured analysis outputs below.

CRITICAL RULES:
1. Write the report in Chinese — all headings and body text.
2. Use the EXACT section structure specified below. Do not skip any section.
3. Condense, don't copy-paste. The inputs can be long; summarize key points.
4. The "数据与业务对齐备忘" section is MANDATORY.
5. Be honest about limitations — do not exaggerate confidence.

Report structure (use exactly these headings):

# DataInsight 数据分析报告

## 执行摘要
3-5 sentence summary: what was analyzed, key findings, and the bottom-line answer
to the user's question.

## 1. 数据画像与清洗
Summarize the Data Profile and Cleaning Insights:
- Dataset shape and key columns
- Data quality issues found
- Cleaning actions performed

## 2. 业务分析意图
Summarize the Analysis Intent:
- Core business question restated
- Analysis type and target variable
- Key dimensions and comparison baselines

## 3. 分析执行与结果
From the analysis results:
- Key statistical findings
- Chart descriptions and what each reveals
- Notable insights discovered

## 4. 数据与业务对齐备忘 ← MANDATORY
Context: {alignment_notes}

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

**CLEANING INSIGHTS:**

{cleaning_insights}

---

**DATA PROFILE (JSON):**

{data_profile_json}

---

**ANALYSIS INTENT (JSON):**

{analysis_intent_json}

---

**ANALYSIS RESULTS (JSON):**

{analysis_result_json}

---

**USER'S ORIGINAL QUESTION:**

{user_requirement}
"""


def _build_partial_report_prompt(
    cleaning_insights: str,
    data_profile_json: str,
    analysis_intent_json: str,
    alignment_notes: str,
    error_message: str,
    user_requirement: str,
) -> str:
    return f"""You are a senior data analysis report writer. The analysis pipeline
encountered an ERROR during the execution phase. Generate a PARTIAL report with
what we have — the data profile, cleaning insights, and business analysis are
still valuable.

CRITICAL RULES:
1. Write in Chinese. Clearly mark the report as **[部分报告 — 分析执行未完成]**.
2. Explain what failed in plain language so a non-technical reader understands.
3. The "数据与业务对齐备忘" section is STILL mandatory.

Report structure:

# DataInsight 数据分析报告 [部分报告]

## 执行摘要
Explain: the pipeline completed data profiling and business analysis successfully,
but the automated analysis phase failed. The report below contains all
pre-execution findings.

## 1. 数据画像与清洗
(Summarize Data Profile and Cleaning Insights)

## 2. 业务分析意图
(Summarize analysis_intent)

## 3. 分析执行计划 (未执行)
Context: {alignment_notes}

(Summarize what WAS planned but not executed)

## 4. 执行错误说明
Explain the error in accessible terms:
- What went wrong during analysis execution
- Whether this is a data issue or a system issue
- What the user can try (rephrase requirement? clean data manually?)

Error details: {error_message}

## 5. 数据与业务对齐备忘 ← MANDATORY
(Based on data profile + business analysis — what we know even without execution)

## 6. 后续建议
What the user can do next.

---

**CLEANING INSIGHTS:**

{cleaning_insights}

---

**DATA PROFILE (JSON):**

{data_profile_json}

---

**ANALYSIS INTENT (JSON):**

{analysis_intent_json}

---

**USER'S ORIGINAL QUESTION:**

{user_requirement}
"""


def report_gen_node(state: AgentState) -> dict[str, object]:
    """Stage 4 — Report Generation: assemble Markdown report with mandatory
    alignment notes.

    Reads: state.cleaning_insights, state.data_profile, state.analysis_intent,
           state.execution_plan, state.analysis_result, state.error,
           state.user_requirement
    Writes: state.final_report
    """
    cleaning_insights = state.cleaning_insights or ""
    data_profile = state.data_profile
    analysis_intent = state.analysis_intent
    execution_plan = state.execution_plan
    analysis_result = state.analysis_result or {}
    error = state.error
    user_requirement = state.user_requirement

    data_profile_json = data_profile.model_dump_json(indent=2) if data_profile else "{}"
    intent_json = analysis_intent.model_dump_json(indent=2) if analysis_intent else "{}"
    alignment_notes = execution_plan.alignment_notes if execution_plan else "无"

    has_results = bool(analysis_result.get("parsed_output") and not error)

    if has_results:
        logger.info("Report Gen: assembling full report")
        result_json = _serialize_analysis_result(analysis_result)
        prompt = _build_full_report_prompt(
            cleaning_insights,
            data_profile_json,
            intent_json,
            alignment_notes,
            result_json,
            user_requirement,
        )
    else:
        logger.info("Report Gen: assembling partial report (analysis failed or missing)")
        error_msg = error or "Analysis did not produce results."
        prompt = _build_partial_report_prompt(
            cleaning_insights,
            data_profile_json,
            intent_json,
            alignment_notes,
            error_msg,
            user_requirement,
        )

    try:
        llm = get_llm(temperature=0)
        response = llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        final_report = str(raw) if not isinstance(raw, str) else raw
    except Exception as e:
        logger.error("Report Gen: LLM call failed: %s", e)
        return {"error": f"Report Gen LLM error: {e}"}

    logger.info("Report Gen: report generated (%d chars)", len(final_report))
    return {"final_report": final_report}
