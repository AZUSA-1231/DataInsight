from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent.llm import get_llm
from src.agent.prompts import load_prompt
from src.agent.state import (
    AgentState,
    AnalysisIntent,
    PlannerInstruction,
    Suggestion,
    UnitSuggestion,
)
from src.agent.tools import BT_TOOLS, resolve_inspect_column

logger = logging.getLogger(__name__)

_MAX_AGENT_TURNS = 5


def _parse_unit_suggestions(raw: list[dict[str, object]]) -> list[UnitSuggestion]:
    """Parse raw unit suggestion dicts into UnitSuggestion models."""
    units: list[UnitSuggestion] = []
    for item in raw:
        try:
            model_val = item.get("model")
            fields_val = item.get("related_fields", [])
            units.append(
                UnitSuggestion(
                    purpose=str(item.get("purpose", "")),
                    model=str(model_val) if model_val else None,
                    related_fields=(
                        [str(f) for f in fields_val]
                        if isinstance(fields_val, list)
                        else []
                    ),
                    cautious=str(item.get("cautious", "")),
                )
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("BT: failed to parse unit suggestion", exc_info=True)
            continue
    return units


def _parse_suggestions(raw: list[dict[str, object]]) -> list[Suggestion]:
    """Parse a list of raw suggestion dicts into Suggestion models."""
    suggestions: list[Suggestion] = []
    for item in raw:
        try:
            category = str(item.get("category", ""))
            content = str(item.get("content", ""))
            rationale = str(item.get("rationale", ""))
            if not category or not content or not rationale:
                continue
            suggestions.append(
                Suggestion(category=category, content=content, rationale=rationale)
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("BT: failed to parse suggestion", exc_info=True)
            continue
    return suggestions


def _qualified_registry_columns(state: AgentState) -> list[str]:
    """Return all current Snapshot-head refs for BT field selection."""
    refs: list[str] = []
    for snapshot in sorted(state.snapshot_registry.values(), key=lambda item: item.name):
        checkpoint = state.checkpoint_registry.get(snapshot.current_checkpoint_id)
        if checkpoint is not None:
            refs.extend(checkpoint.columns)
    return refs


def _build_bt_user_context(state: AgentState) -> str:
    """Build the dynamic user context injected alongside the system prompt.

    This is NOT prompt assembly — the system prompt is stable. This block
    provides the current state: data, columns, conversation history, etc.
    """
    parts: list[str] = []

    # ── Data context ──
    unified_columns = _qualified_registry_columns(state) or state.unified_columns or []
    data_profile = state.data_profile

    registry_lines: list[str] = []
    for snapshot in sorted(
        state.snapshot_registry.values(), key=lambda item: item.name
    ):
        checkpoint = state.checkpoint_registry.get(snapshot.current_checkpoint_id)
        if checkpoint is None:
            registry_lines.append(
                f"  - {snapshot.name}: missing current checkpoint"
            )
            continue
        source = next(
            (item for item in state.data_sources if item.snapshot_id == snapshot.snapshot_id),
            None,
        )
        source_label = f", source={source.display_name}" if source else ""
        registry_lines.append(
            f"  - {snapshot.name}: {checkpoint.row_count} rows "
            f"(checkpoint={checkpoint.checkpoint_id}{source_label})"
        )
        profile_by_name = (
            {column.name: column for column in source.profile.columns}
            if source is not None
            else {}
        )
        for ref, node_id in checkpoint.columns.items():
            node = state.column_graph.nodes.get(node_id)
            dtype = node.dtype if node is not None else "unknown"
            profile = profile_by_name.get(node.name) if node is not None else None
            null_suffix = f", null_pct={profile.null_pct:.1f}%" if profile else ""
            registry_lines.append(f"      {ref} ({dtype}{null_suffix})")
    if registry_lines:
        parts.append(
            "SNAPSHOTS AND QUALIFIED COLUMNS (use exact refs):\n"
            + "\n".join(registry_lines)
        )

    if state.snapshot_registry:
        parts.append(
            "SOURCE PROFILES ARE GROUPED BY SNAPSHOT. Do not compare columns "
            "from different Snapshots unless the user asks for a Join."
        )

    if unified_columns:
        cols_with_types: list[str] = []
        if state.snapshot_registry:
            for ref in unified_columns:
                node = None
                for snapshot in state.snapshot_registry.values():
                    checkpoint = state.checkpoint_registry.get(
                        snapshot.current_checkpoint_id
                    )
                    if checkpoint is None:
                        continue
                    for current_ref, node_id in checkpoint.columns.items():
                        if current_ref == ref:
                            node = state.column_graph.nodes.get(node_id)
                            break
                    if node is not None:
                        break
                cols_with_types.append(f"  - {ref} ({node.dtype if node else 'unknown'})")
        elif data_profile and data_profile.columns:
            cols_with_types = [f"  - {cp.name} ({cp.dtype})" for cp in data_profile.columns]
        else:
            cols_with_types = [f"  - {c}" for c in unified_columns]
        parts.append(
            "AVAILABLE COLUMNS:\n" + "\n".join(cols_with_types)
        )
    elif not state.snapshot_registry:
        parts.append("AVAILABLE COLUMNS: (no data uploaded yet)")

    if state.data_sources:
        total_rows = sum(source.profile.shape[0] for source in state.data_sources)
        parts.append(
            "DATA SUMMARY BY SNAPSHOT: "
            + ", ".join(
                f"{snapshot.name}={checkpoint.row_count} rows"
                for snapshot in sorted(state.snapshot_registry.values(), key=lambda item: item.name)
                if (checkpoint := state.checkpoint_registry.get(snapshot.current_checkpoint_id))
            )
            + f" (uploaded rows total={total_rows})"
        )
    elif data_profile:
        parts.append(
            f"DATA SUMMARY: {data_profile.shape[0]} rows, {data_profile.shape[1]} columns"
        )

    # ── Workspace Plan ──
    if state.plan:
        plan_json = state.plan.model_dump_json(indent=2)
        parts.append(f"CURRENT WORKSPACE PLAN:\n{plan_json}")
    else:
        parts.append("CURRENT WORKSPACE PLAN: (none — generate from scratch)")

    # ── Feedback ──
    if state.feedback:
        parts.append(f"USER FEEDBACK (from previous report):\n{state.feedback}")

    # ── Conversation History ──
    history = state.dialogue_history or []
    if history:
        lines: list[str] = ["CONVERSATION HISTORY:"]
        for turn in history[-10:]:  # Last 10 turns (5 exchanges)
            role = "用户" if turn.get("role") == "user" else "BT"
            content = turn.get("content", "")
            if content:
                lines.append(f"[{role}]: {content}")
        parts.append("\n".join(lines))

    # ── Current message ──
    user_msg = state.user_requirement or ""
    empty_hint = "(empty — user is waiting for your suggestion)"
    parts.append(f"\nCURRENT USER MESSAGE:\n{user_msg if user_msg else empty_hint}")

    return "\n\n".join(parts)


def _build_planner_instruction_from_tool_args(args: dict[str, Any]) -> PlannerInstruction:
    """Build a PlannerInstruction from the LLM's tool call arguments."""
    return PlannerInstruction(
        core_question=str(args.get("core_question", "")),
        analysis_type=str(args.get("analysis_type", "descriptive")),
        complexity=str(args.get("complexity", "moderate")),
        target_columns=[str(c) for c in args.get("target_columns", [])],
        group_by=[str(c) for c in args.get("group_by", [])],
        filter_hint=args.get("filter_hint") if args.get("filter_hint") else None,
        unit_suggestions=_parse_unit_suggestions(args.get("unit_suggestions", [])),
        is_revision=bool(args.get("is_revision", False)),
        target_unit_ids=[int(i) for i in args.get("target_unit_ids", [])],
        revision_notes=args.get("revision_notes") if args.get("revision_notes") else None,
        suggestions=_parse_suggestions(args.get("suggestions", [])),
        caution_notes=args.get("caution_notes") if args.get("caution_notes") else None,
        instruction_nl=str(args.get("instruction_nl", "")),
    )


def _extract_conversational_text(response: AIMessage) -> str:
    """Extract the conversational text from an LLM response.

    When the LLM calls a tool, it may still include a text preamble.
    When it doesn't call a tool, the full content is the conversation.
    """
    content = response.content
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts).strip()
    return str(content).strip()


def business_track_node(state: AgentState) -> tuple[dict[str, object], dict[str, object]]:
    """BT Agent: intelligent conversational analyst with tool calling.

    Uses a stable system prompt + dynamic user context. The LLM decides
    whether to respond conversationally or call submit_planner_instruction
    when it has sufficient understanding of the user's goal.

    Supports inspect_column for querying column statistics during reasoning.

    Reads: state.user_requirement, state.dialogue_history, state.unified_columns,
           state.data_profile, state.plan, state.feedback
    Writes: state.planner_instruction (if tool called),
            state.analysis_intent (deprecated compat)

    Returns:
        (state_update, metadata) — state_update is for LangGraph merge;
        metadata carries bt_response, bt_tool_called for the dialogue route.
    """
    user_message = state.user_requirement or ""
    unified_columns = _qualified_registry_columns(state) or state.unified_columns or []

    logger.info(
        "BT Agent: msg=%d chars, columns=%d, plan=%s, history=%d turns",
        len(user_message),
        len(unified_columns),
        bool(state.plan),
        len(state.dialogue_history or []),
    )

    # ── Load stable system prompt ──
    try:
        system_prompt = load_prompt("bt_system.txt")
    except FileNotFoundError as e:
        logger.error("BT Agent: system prompt not found: %s", e)
        return {"error": f"BT Agent: {e}"}, {}

    # ── Build dynamic user context ──
    user_context = _build_bt_user_context(state)

    # ── CLI mode signal ──
    # In CLI mode (no dialogue_history, no plan — fresh one-shot invocation),
    # tell the BT to go straight to tool call without asking questions.
    is_cli_mode = not state.dialogue_history and not state.plan and bool(user_message)

    messages: list[SystemMessage | HumanMessage | AIMessage | ToolMessage] = [
        SystemMessage(content=system_prompt),
    ]

    if is_cli_mode:
        messages.append(
            HumanMessage(
                content=(
                    "MODE: CLI one-shot analysis. The user has no opportunity to "
                    "answer follow-up questions. If the request is clear enough, "
                    "call submit_planner_instruction directly. Only ask questions "
                    "if absolutely necessary.\n\n"
                    + user_context
                )
            )
        )
    else:
        messages.append(HumanMessage(content=user_context))

    # ── Agent loop ──
    try:
        llm = get_llm(temperature=0, node="business_track")
        llm_with_tools = llm.bind_tools(BT_TOOLS)
    except Exception as e:
        logger.error("BT Agent: failed to initialize LLM: %s", e)
        return {"error": f"BT Agent LLM error: {e}"}, {}

    final_text = ""
    planner_instruction: PlannerInstruction | None = None
    tool_called = False

    for _turn in range(_MAX_AGENT_TURNS):
        try:
            response = llm_with_tools.invoke(messages)
        except Exception as e:
            logger.error("BT Agent: LLM call failed: %s", e)
            return {"error": f"BT Agent LLM error: {e}"}, {}

        if not isinstance(response, AIMessage):
            final_text = str(response)
            break

        tool_calls = getattr(response, "tool_calls", None) or []

        if not tool_calls:
            # Pure conversational response — no tool called
            final_text = _extract_conversational_text(response)
            break

        # ── Process tool calls ──
        # Add the assistant's response to messages for the next turn
        messages.append(response)

        for tc in tool_calls:
            tool_name = tc.get("name", "")
            tool_args: dict[str, Any] = tc.get("args", {})

            if tool_name == "submit_planner_instruction":
                logger.info("BT Agent: submit_planner_instruction called")
                planner_instruction = _build_planner_instruction_from_tool_args(tool_args)
                tool_called = True
                final_text = _extract_conversational_text(response)
                # Append tool result message so the conversation is complete
                messages.append(
                    ToolMessage(
                        content="Instruction submitted. Planner will take over.",
                        tool_call_id=tc.get("id", ""),
                    )
                )
                break  # Exit tool_calls loop

            elif tool_name == "inspect_column":
                column_name = str(tool_args.get("column_name", ""))
                logger.info("BT Agent: inspect_column called for '%s'", column_name)
                result = resolve_inspect_column(column_name, state)
                messages.append(
                    ToolMessage(content=result, tool_call_id=tc.get("id", ""))
                )
                # Continue the loop — LLM will see the result and may call
                # submit_planner_instruction or continue conversation

            else:
                logger.warning("BT Agent: unknown tool called: %s", tool_name)
                messages.append(
                    ToolMessage(
                        content=f"Unknown tool: {tool_name}",
                        tool_call_id=tc.get("id", ""),
                    )
                )

        if tool_called:
            break  # Exit turn loop

    # ── Fallback: if no text was captured, use raw content ──
    if not final_text:
        try:
            final_text = str(response.content) if hasattr(response, "content") else str(response)
        except Exception:
            final_text = ""

    # ── Build backward-compatible AnalysisIntent ──
    analysis_intent: AnalysisIntent | None = None
    if planner_instruction is not None:
        analysis_intent = AnalysisIntent(
            core_question=planner_instruction.core_question,
            target_variable=(
                planner_instruction.target_columns[0]
                if planner_instruction.target_columns
                else None
            ),
            analysis_type=planner_instruction.analysis_type,
            dimensions=planner_instruction.group_by,
            comparison_baseline=None,
            expanded_question=None,
            complexity=planner_instruction.complexity,
            suggestions=planner_instruction.suggestions,
            caution_notes=planner_instruction.caution_notes,
        )

    logger.info(
        "BT Agent: done — tool_called=%s, instruction=%s, text=%d chars",
        tool_called,
        bool(planner_instruction),
        len(final_text),
    )

    state_update: dict[str, object] = {
        "analysis_intent": analysis_intent,
        "planner_instruction": planner_instruction,
        "feedback": None,
    }
    metadata: dict[str, object] = {
        "_bt_response": final_text,
        "_bt_tool_called": tool_called,
    }
    return state_update, metadata
