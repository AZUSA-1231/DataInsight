from __future__ import annotations

import json
import logging
from typing import Any

from src.agent.llm import get_llm
from src.agent.plan_validation import PlanValidationError, validate_plan
from src.agent.prompts import load_prompt
from src.agent.state import AgentState, Plan, PlannerInstruction, PlanUnit
from src.agent.utils import _extract_json

logger = logging.getLogger(__name__)


def _qualified_registry_columns(state: AgentState) -> list[str]:
    """Return current-head qualified refs in Snapshot order."""
    refs: list[str] = []
    for snapshot in sorted(state.snapshot_registry.values(), key=lambda item: item.name):
        checkpoint = state.checkpoint_registry.get(snapshot.current_checkpoint_id)
        if checkpoint is not None:
            refs.extend(checkpoint.columns)
    return refs


def _source_profile_context(state: AgentState) -> str:
    """Serialize source profiles grouped by Snapshot for the Planner."""
    profiles: list[dict[str, object]] = []
    for source in sorted(state.data_sources, key=lambda item: item.display_name):
        snapshot = state.snapshot_registry.get(source.snapshot_id)
        profiles.append(
            {
                "source_id": source.source_id,
                "snapshot_id": source.snapshot_id,
                "snapshot": snapshot.name if snapshot else None,
                "display_name": source.display_name,
                "profile": source.profile.model_dump(mode="json"),
            }
        )
    return json.dumps(profiles, ensure_ascii=False, indent=2)


def _build_planner_user_context(state: AgentState) -> str:
    """Build the dynamic context injected alongside the Planner system prompt.

    The Planner receives all five information sources and reads them
    holistically — no more if/elif prompt branches.
    """
    parts: list[str] = []

    # ── 1. Conversation History ──
    history = state.dialogue_history or []
    if history:
        lines: list[str] = ["=== FULL CONVERSATION HISTORY ==="]
        for turn in history:
            role = "用户" if turn.get("role") == "user" else "BT Analyst"
            content = turn.get("content", "")
            if content:
                lines.append(f"[{role}]: {content}")
        parts.append("\n".join(lines))
    else:
        parts.append(
            "=== FULL CONVERSATION HISTORY ===\n"
            "(no conversation history — CLI one-shot invocation)"
        )

    # ── 2. PlannerInstruction ──
    instruction = state.planner_instruction
    if instruction:
        parts.append(
            "=== PLANNER INSTRUCTION (from Business Track) ===\n"
            "READ THE instruction_nl FIELD FIRST — it's the analyst's handoff brief.\n\n"
            f"instruction_nl (ANALYST'S BRIEF — READ THIS FIRST):\n{instruction.instruction_nl}\n\n"
            f"core_question: {instruction.core_question}\n"
            f"analysis_type: {instruction.analysis_type}\n"
            f"complexity: {instruction.complexity}\n"
            f"target_columns: {instruction.target_columns or '(none)'}\n"
            f"group_by: {instruction.group_by or '(none)'}\n"
            f"filter_hint: {instruction.filter_hint or '(none)'}\n"
            f"is_revision: {instruction.is_revision}\n"
            f"target_unit_ids: {instruction.target_unit_ids or '(none — fresh plan)'}\n"
            f"revision_notes: {instruction.revision_notes or '(none)'}\n"
            f"caution_notes: {instruction.caution_notes or '(none)'}\n"
            f"unit_suggestions: {_format_unit_suggestions(instruction)}\n"
            f"suggestions: {_format_suggestions(instruction)}"
        )
    elif state.analysis_intent:
        # Fallback: legacy AnalysisIntent
        intent = state.analysis_intent
        parts.append(
            "=== ANALYSIS INTENT (legacy — no PlannerInstruction available) ===\n"
            f"{intent.model_dump_json(indent=2)}\n\n"
            "Note: This is business-level language. Translate it to concrete "
            "column names and methods using the AVAILABLE COLUMNS below."
        )
    else:
        parts.append(
            "=== PLANNER INSTRUCTION ===\n"
            "(no instruction available — generate a best-effort Plan from the data alone)"
        )

    # ── 3. Data Profile ──
    registry_lines: list[str] = []
    for snapshot in sorted(
        state.snapshot_registry.values(), key=lambda item: item.name
    ):
        checkpoint = state.checkpoint_registry.get(snapshot.current_checkpoint_id)
        if checkpoint is None:
            registry_lines.append(
                f"  - Snapshot {snapshot.name}: missing current checkpoint"
            )
            continue
        registry_lines.append(
            f"  - Snapshot {snapshot.name}: {checkpoint.row_count} rows "
            f"(checkpoint={checkpoint.checkpoint_id})"
        )
        source = next(
            (
                source
                for source in state.data_sources
                if source.snapshot_id == snapshot.snapshot_id
            ),
            None,
        )
        profile_by_name = (
            {column.name: column for column in source.profile.columns}
            if source is not None
            else {}
        )
        for ref, node_id in checkpoint.columns.items():
            node = state.column_graph.nodes.get(node_id)
            dtype = node.dtype if node is not None else "unknown"
            local_name = ref[len(snapshot.name) + 1 :]
            profile = profile_by_name.get(local_name)
            null_suffix = f", null_pct={profile.null_pct:.1f}%" if profile else ""
            registry_lines.append(f"      {ref} ({dtype}{null_suffix})")

    if registry_lines:
        parts.append(
            "=== SNAPSHOTS AND QUALIFIED COLUMNS (use exact refs) ===\n"
            + "\n".join(registry_lines)
        )

    if state.data_sources:
        parts.append(
            "=== SOURCE PROFILES GROUPED BY SNAPSHOT ===\n"
            + _source_profile_context(state)
        )

    data_profile = state.data_profile
    if data_profile:
        parts.append(
            "=== DATA PROFILE ===\n"
            + data_profile.model_dump_json(indent=2)
        )
    else:
        parts.append("=== DATA PROFILE ===\n(not available)")

    # ── 4. Unified Columns ──
    columns = _qualified_registry_columns(state) or state.unified_columns or []
    parts.append(
        "=== AVAILABLE COLUMNS (use EXACT names) ===\n"
        + "\n".join(f"  - {c}" for c in columns)
        if columns
        else "=== AVAILABLE COLUMNS ===\n(none)"
    )

    # ── 5. Workspace Plan ──
    plan = state.plan
    if plan:
        parts.append(
            "=== CURRENT WORKSPACE PLAN ===\n"
            + plan.model_dump_json(indent=2)
        )
    else:
        parts.append("=== CURRENT WORKSPACE PLAN ===\n(none — generate from scratch)")

    return "\n\n".join(parts)


def _format_unit_suggestions(instruction: PlannerInstruction) -> str:
    """Format unit_suggestions for display in the Planner context."""
    if not instruction.unit_suggestions:
        return "(none — derive from data profile)"
    lines: list[str] = []
    for u in instruction.unit_suggestions:
        lines.append(
            f"  - purpose: \"{u.purpose}\", fields: {u.related_fields}, "
            f"model: {u.model or 'auto'}, cautious: \"{u.cautious}\""
        )
    return "\n".join(lines)


def _format_suggestions(instruction: PlannerInstruction) -> str:
    """Format general suggestions for display in the Planner context."""
    if not instruction.suggestions:
        return "(none)"
    return "\n".join(
        f"  - [{s.category}] {s.content} (rationale: {s.rationale})"
        for s in instruction.suggestions
    )


def _parse_plan_from_json(parsed: dict[str, Any]) -> Plan:
    """Round-trip Planner JSON through the complete Pydantic Plan contract."""
    raw_units = parsed.get("units")
    if isinstance(raw_units, list) and raw_units and all(
        isinstance(unit, dict) and "operation" not in unit for unit in raw_units
    ):
        # Explicit compatibility boundary for Cycle 4 LLM fixtures. Real v2
        # Planner output always takes the strict model_validate path below.
        return Plan(
            units=[PlanUnit.model_validate(unit) for unit in raw_units],
            alignment_notes=str(parsed.get("alignment_notes", "")),
        )
    return Plan.model_validate(parsed)


def planner_node(state: AgentState) -> dict[str, object]:
    """Planner Agent: reads full context, reasons holistically, produces Plan.

    Reads all five information sources from state:
    1. Full conversation history (state.dialogue_history)
    2. BT's PlannerInstruction (state.planner_instruction) — with instruction_nl
    3. Data profile (state.data_profile)
    4. Unified columns (state.unified_columns)
    5. Current workspace Plan (state.plan)

    The Planner is the final decision-maker on HOW to execute. It trusts the
    BT's column assignments (they have access to the data) but validates
    against the data profile. It trusts the conversation history as much as
    the structured instruction.

    Writes: state.plan (Plan)
    """
    data_profile = state.data_profile
    unified_columns = _qualified_registry_columns(state) or state.unified_columns or []
    has_registry_data = bool(state.snapshot_registry)

    if not data_profile and not has_registry_data:
        logger.error("Planner: data_profile is missing from state")
        return {"error": "Planner: data_profile not available (Data Track may have failed)"}

    if not unified_columns and not has_registry_data:
        logger.error("Planner: unified_columns is empty — Data Track may have failed")
        return {"error": "Planner: unified_columns not available (Data Track may have failed)"}

    logger.info(
        "Planner: instruction=%s, columns=%d, workspace=%s, history=%d turns",
        bool(state.planner_instruction),
        len(unified_columns),
        bool(state.plan),
        len(state.dialogue_history or []),
    )

    # ── Load stable system prompt ──
    try:
        system_prompt = load_prompt("planner_system.txt")
    except FileNotFoundError as e:
        logger.error("Planner: system prompt not found: %s", e)
        return {"error": f"Planner: {e}"}

    # ── Build dynamic user context ──
    user_context = _build_planner_user_context(state)

    # ── LLM call ──
    try:
        llm = get_llm(temperature=0, node="planner")
        from langchain_core.messages import HumanMessage, SystemMessage

        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_context),
        ])
        content = response.content if hasattr(response, "content") else str(response)
        content = str(content) if not isinstance(content, str) else content
    except Exception as e:
        logger.error("Planner: LLM call failed: %s", e)
        return {"error": f"Planner LLM error: {e}"}

    # ── JSON extraction + parsing ──
    json_text = _extract_json(content)

    try:
        parsed = json.loads(json_text)
        plan = _parse_plan_from_json(parsed)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error("Planner: failed to parse Plan JSON: %s", e)
        logger.debug("Planner: raw LLM output (first 500 chars): %s", content[:500])
        return {"error": f"Planner: failed to parse structured output: {e}"}

    try:
        validate_plan(plan, state)
    except PlanValidationError as exc:
        logger.error("Planner: generated Plan failed validation: %s", exc)
        return {
            "error": f"Planner: generated Plan failed validation: {exc}",
            "_plan_validation_issues": [issue.model_dump() for issue in exc.issues],
        }

    logger.info(
        "Planner: plan generated — %d analysis unit(s)",
        len(plan.units),
    )

    return {"plan": plan}
