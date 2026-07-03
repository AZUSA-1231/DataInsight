from __future__ import annotations

import json
import logging
from typing import Any, cast

from src.agent.llm import get_llm
from src.agent.state import AgentState

logger = logging.getLogger(__name__)


def _chart_basename(path: str) -> str:
    """Extract the filename from a chart path, stripping any unit_N_ prefix."""
    import os as _os
    import re

    name = _os.path.basename(path)
    return re.sub(r"^unit\d+_", "", name)


def _serialize_analysis_result(analysis_result: dict[str, object]) -> str:
    """Serialize analysis_result for inclusion in the report prompt.

    Handles both legacy (parsed_output) and new (unit_results) shapes.
    Chart paths are converted to basenames for markdown embedding.
    """
    if "unit_results" in analysis_result:
        # New per-unit shape: extract key fields for the LLM prompt
        summary = []
        for ur in cast(list[dict[str, Any]], analysis_result["unit_results"]):
            unit_id = ur.get("unit_id", "?")
            charts = [_chart_basename(c) for c in ur.get("charts", [])]
            # Prefix with unit_id to avoid filename collisions
            charts = [f"unit_{unit_id}_{c}" for c in charts]
            summary.append({
                "unit_id": unit_id,
                "status": ur.get("status"),
                "charts": charts,
                "insights": ur.get("insights", []),
                "statistics": ur.get("statistics", {}),
                "error": ur.get("error"),
                "retry_count": ur.get("retry_count"),
            })
        return json.dumps(
            {"status": analysis_result.get("status"), "unit_results": summary},
            ensure_ascii=False,
            indent=2,
        )
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
6. Section 3: write ONE subsection (### 3.{{N}}) per analysis unit. Each unit in
   ANALYSIS RESULTS maps to exactly one subsection. Include findings, charts,
   key statistics, and any errors/warnings for that unit.
7. For EACH chart listed in a unit's results, embed it using Markdown image
   syntax: `![what the chart shows](charts/unit_N_filename.png)`. The chart
   filenames are already in the ANALYSIS RESULTS — use them exactly as provided.
   Place images right after the **生成图表** line in each subsection, one image
   per line.

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
Start with a 1-2 sentence overall status (e.g. "全部 {{N}} 个分析单元执行成功" or
"{{S}} of {{N}} 个分析单元执行成功，{{F}} 个失败").

Then create ONE subsection per analysis unit from the ANALYSIS RESULTS:
### 3.{{N}} {{{{该单元的分析目的（purpose）}}}}
- **执行状态**: 成功 / 失败
- **主要发现**: 2-4 key insights from this unit's results
- **生成图表**: embed EACH chart image using `![description](charts/filename.png)` — use the filenames exactly from the unit's chart list. Then add a one-line note per chart explaining what the reader should see.
- **关键统计**: notable statistics or metrics
- **注意事项**: errors, warnings, or caveats if the unit had issues

## 4. 数据与业务对齐备忘 ← MANDATORY
Context: {alignment_notes}

- What the business wanted to know vs. what the data could actually answer
- Gaps between ideal metrics and available data
- Trade-offs and proxy metrics used
- Assumptions made in the analysis
- Honesty statement: "基于当前数据，本报告[能够/无法完全]回答用户问题，原因在于..."

## 5. 图表清单
List all charts that were embedded in Section 3 above, with one-line descriptions
of what each shows. Use `- **filename.png**: description` format.

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
    plan_units_json: str = "[]",
) -> str:
    return f"""You are a senior data analysis report writer. The analysis pipeline
encountered an ERROR during the execution phase. Generate a PARTIAL report with
what we have — the data profile, cleaning insights, and business analysis are
still valuable.

CRITICAL RULES:
1. Write in Chinese. Clearly mark the report as **[部分报告 — 分析执行未完成]**.
2. Explain what failed in plain language so a non-technical reader understands.
3. The "数据与业务对齐备忘" section is STILL mandatory.
4. Embed charts (if any were generated before the failure) with `![desc](charts/filename.png)`.

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

The following analysis units were planned but not executed. List each unit
with its purpose and planned method:
{plan_units_json}

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
           state.plan, state.analysis_result, state.error, state.user_requirement
    Writes: state.final_report
    """
    cleaning_insights = state.cleaning_insights or ""
    data_profile = state.data_profile
    analysis_intent = state.analysis_intent
    analysis_result = state.analysis_result or {}
    error = state.error
    user_requirement = state.user_requirement

    data_profile_json = data_profile.model_dump_json(indent=2) if data_profile else "{}"
    intent_json = analysis_intent.model_dump_json(indent=2) if analysis_intent else "{}"
    alignment_notes = state.plan.alignment_notes if state.plan else "无"

    has_results = bool(
        analysis_result.get("unit_results") or analysis_result.get("parsed_output")
    )

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
        plan_units = state.plan.units if state.plan else []
        plan_units_json = json.dumps(
            [{"unit_id": u.unit_id, "purpose": u.purpose, "model": u.model or "auto"}
             for u in plan_units],
            ensure_ascii=False,
            indent=2,
        )
        prompt = _build_partial_report_prompt(
            cleaning_insights,
            data_profile_json,
            intent_json,
            alignment_notes,
            error_msg,
            user_requirement,
            plan_units_json,
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
