from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, cast

from src.agent.llm import get_llm
from src.agent.state import AgentState

logger = logging.getLogger(__name__)


def _chart_basename(path: str) -> str:
    """Extract the filename from a chart path, stripping any unit_N_ prefix."""
    name = os.path.basename(path)
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
                "stale": ur.get("stale", False),
                "run_id": ur.get("run_id"),
                "input_checkpoint_ids": ur.get("input_checkpoint_ids", []),
                "output_checkpoint_id": ur.get("output_checkpoint_id"),
                "row_count_before": ur.get("row_count_before"),
                "row_count_after": ur.get("row_count_after"),
                "row_count_delta": ur.get("row_count_delta"),
                "warnings": ur.get("warnings", []),
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
    data_profile_json: str,
    analysis_intent_json: str,
    alignment_notes: str,
    analysis_result_json: str,
    user_requirement: str,
    runtime_context_json: str = "{}",
) -> str:
    return f"""You are a senior data analysis report writer. Assemble a comprehensive,
reader-friendly Markdown report from the structured analysis outputs below.

CRITICAL RULES:
1. Write the report in Chinese — all headings and body text.
2. Use the EXACT section structure specified below. Do not skip any section.
3. Condense, don't copy-paste. The inputs can be long; summarize key points.
4. The "数据与业务对齐备忘" section is MANDATORY.
5. Be honest about limitations — do not exaggerate confidence.
6. Section 2: write ONE subsection (### 2.{{N}}) per analysis unit. Each unit in
   ANALYSIS RESULTS maps to exactly one subsection. Include findings, charts,
  key statistics, and any errors/warnings for that unit.
8. Explicitly disclose each structured JOIN_* warning, row-count expansion or
   unmatched-key limitation. Mark stale units as not current and do not present
   their outputs as final evidence.
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

## 1. 业务分析意图
Summarize the Analysis Intent:
- Core business question restated
- Analysis type and target variable
- Key dimensions and comparison baselines

## 2. 分析执行与结果
Start with a 1-2 sentence overall status (e.g. "全部 {{N}} 个分析单元执行成功" or
"{{S}} of {{N}} 个分析单元执行成功，{{F}} 个失败").

Then create ONE subsection per analysis unit from the ANALYSIS RESULTS:
### 2.{{N}} {{{{该单元的分析目的（purpose）}}}}
- **执行状态**: 成功 / 失败
- **主要发现**: 2-4 key insights from this unit's results
- **生成图表**: embed EACH chart using `![description](charts/filename.png)` with exact
  filenames from the unit's chart list. Add a one-line note per chart.
- **关键统计**: notable statistics or metrics
- **注意事项**: errors, warnings, or caveats if the unit had issues

## 3. 数据与业务对齐备忘 ← MANDATORY
Context: {alignment_notes}

- What the business wanted to know vs. what the data could actually answer
- Gaps between ideal metrics and available data
- Trade-offs and proxy metrics used
- Assumptions made in the analysis
- Honesty statement: "基于当前数据，本报告[能够/无法完全]回答用户问题，原因在于..."

## 4. 图表清单
List all charts that were embedded in Section 2 above, with one-line descriptions
of what each shows. Use `- **filename.png**: description` format.

## 5. 局限性与后续建议
- Limitations of the current analysis
- What additional data would improve it
- Suggested next steps for the user

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

---

**V2 SNAPSHOT, CHECKPOINT, AND COLUMN LINEAGE CONTEXT (JSON):**

{runtime_context_json}
"""


def _build_partial_report_prompt(
    data_profile_json: str,
    analysis_intent_json: str,
    alignment_notes: str,
    error_message: str,
    user_requirement: str,
    plan_units_json: str = "[]",
    runtime_context_json: str = "{}",
) -> str:
    return f"""You are a senior data analysis report writer. The analysis pipeline
encountered an ERROR during the execution phase. Generate a PARTIAL report with
what we have — the data profile and business analysis are still valuable.

CRITICAL RULES:
1. Write in Chinese. Clearly mark the report as **[部分报告 — 分析执行未完成]**.
2. Explain what failed in plain language so a non-technical reader understands.
3. The "数据与业务对齐备忘" section is STILL mandatory.
4. Embed charts (if any were generated before the failure) with `![desc](charts/filename.png)`.
5. Mention any retained checkpoints, stale units, Join warnings, or row-count
   limitations present in the v2 runtime context.

Report structure:

# DataInsight 数据分析报告 [部分报告]

## 执行摘要
Explain: the pipeline completed data profiling and business analysis successfully,
but the automated analysis phase failed. The report below contains all
pre-execution findings.

## 1. 业务分析意图
(Summarize analysis_intent)

## 2. 分析执行计划 (未执行)
Context: {alignment_notes}

The following analysis units were planned but not executed. List each unit
with its purpose and planned method:
{plan_units_json}

## 3. 执行错误说明
Explain the error in accessible terms:
- What went wrong during analysis execution
- Whether this is a data issue or a system issue
- What the user can try (rephrase requirement? re-upload data?)

Error details: {error_message}

## 4. 数据与业务对齐备忘 ← MANDATORY
(Based on data profile + business analysis — what we know even without execution)

## 5. 后续建议
What the user can do next.

---

**DATA PROFILE (JSON):**

{data_profile_json}

---

**ANALYSIS INTENT (JSON):**

{analysis_intent_json}

---

**USER'S ORIGINAL QUESTION:**

{user_requirement}

---

**V2 SNAPSHOT, CHECKPOINT, AND COLUMN LINEAGE CONTEXT (JSON):**

{runtime_context_json}
"""


def _build_v2_report_context(state: AgentState) -> str:
    """Serialize durable multi-source and lineage context for report writing."""
    sources: list[dict[str, object]] = []
    for source in sorted(state.data_sources, key=lambda item: item.display_name):
        snapshot = state.snapshot_registry.get(source.snapshot_id)
        sources.append(
            {
                "source_id": source.source_id,
                "snapshot_id": source.snapshot_id,
                "snapshot": snapshot.name if snapshot else None,
                "display_name": source.display_name,
                "profile": source.profile.model_dump(mode="json"),
            }
        )

    snapshots: list[dict[str, object]] = []
    lineage: list[dict[str, object]] = []
    for snapshot in sorted(state.snapshot_registry.values(), key=lambda item: item.name):
        checkpoint = state.checkpoint_registry.get(snapshot.current_checkpoint_id)
        if checkpoint is None:
            continue
        snapshots.append(
            {
                "snapshot": snapshot.name,
                "snapshot_id": snapshot.snapshot_id,
                "checkpoint_id": checkpoint.checkpoint_id,
                "row_count": checkpoint.row_count,
                "producer_unit_id": snapshot.created_by_unit_id,
                "parent_snapshots": snapshot.parent_snapshot_ids,
                "column_refs": list(checkpoint.columns),
            }
        )
        for ref, node_id in checkpoint.columns.items():
            node = state.column_graph.nodes.get(node_id)
            if node is None:
                continue
            lineage.append(
                {
                    "ref": ref,
                    "snapshot": snapshot.name,
                    "dtype": node.dtype,
                    "source_column": node.source_column,
                    "origin_refs": list(node.origin_columns),
                    "derived_from": [
                        state.column_graph.nodes[parent_id].ref
                        for parent_id in node.derived_from_node_ids
                        if parent_id in state.column_graph.nodes
                    ],
                    "created_by_unit_id": node.created_by_unit_id,
                }
            )

    return json.dumps(
        {"sources": sources, "snapshots": snapshots, "lineage": lineage},
        ensure_ascii=False,
        indent=2,
    )


def report_gen_node(state: AgentState) -> dict[str, object]:
    """Stage 4 — Report Generation: assemble Markdown report with mandatory
    alignment notes.

    Reads: state.data_profile, state.analysis_intent, state.plan,
           state.analysis_result, state.error, state.user_requirement
    Writes: state.final_report
    """
    data_profile = state.data_profile
    analysis_intent = state.analysis_intent
    analysis_result = state.analysis_result or {}
    error = state.error
    user_requirement = state.user_requirement

    data_profile_json = data_profile.model_dump_json(indent=2) if data_profile else "{}"
    intent_json = analysis_intent.model_dump_json(indent=2) if analysis_intent else "{}"
    alignment_notes = state.plan.alignment_notes if state.plan else "无"

    runtime_context_json = _build_v2_report_context(state)

    has_results = bool(
        analysis_result.get("unit_results") or analysis_result.get("parsed_output")
    )

    if has_results:
        logger.info("Report Gen: assembling full report")
        result_json = _serialize_analysis_result(analysis_result)
        prompt = _build_full_report_prompt(
            data_profile_json,
            intent_json,
            alignment_notes,
            result_json,
            user_requirement,
            runtime_context_json,
        )
    else:
        logger.info("Report Gen: assembling partial report (analysis failed or missing)")
        error_msg = error or "Analysis did not produce results."
        plan_units = state.plan.units if state.plan else []
        plan_units_json = json.dumps(
            [{"unit_id": u.unit_id, "purpose": u.purpose, "model": u.model_hint or "auto"}
             for u in plan_units],
            ensure_ascii=False,
            indent=2,
        )
        prompt = _build_partial_report_prompt(
            data_profile_json,
            intent_json,
            alignment_notes,
            error_msg,
            user_requirement,
            plan_units_json,
            runtime_context_json,
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
