from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.business_track import business_track_node
from src.agent.state import AgentState, AnalysisIntent, PlannerInstruction

# ── BT Agent: conversational response tests ───────────────────────

@pytest.mark.unit
def test_bt_agent_conversational_response(set_llm_env: None, bt_chat_msg: object) -> None:
    """BT Agent returns conversational text when LLM doesn't call a tool."""
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.invoke.return_value = bt_chat_msg

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="分析销售数据",
        unified_columns=["sales", "region", "date"],
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        result, meta = business_track_node(state)

    assert "error" not in result
    assert meta["_bt_tool_called"] is False
    assert "您想从哪个维度" in meta["_bt_response"]
    assert result["planner_instruction"] is None
    assert result["analysis_intent"] is None
    mock_llm.bind_tools.assert_called_once()
    mock_llm.invoke.assert_called_once()


@pytest.mark.unit
def test_bt_agent_submits_instruction(
    set_llm_env: None, bt_tool_call_msg: object
) -> None:
    """BT Agent calls submit_planner_instruction when ready."""
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.invoke.return_value = bt_tool_call_msg

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Why did Q2 sales drop by 15%?",
        unified_columns=["sales", "region", "date"],
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        result, meta = business_track_node(state)

    assert "error" not in result
    assert meta["_bt_tool_called"] is True
    assert isinstance(result["planner_instruction"], PlannerInstruction)
    assert result["planner_instruction"].core_question == "Why did Q2 sales drop by 15%?"
    assert result["planner_instruction"].analysis_type == "diagnostic"
    assert result["planner_instruction"].target_columns == ["sales"]
    assert result["planner_instruction"].group_by == ["region", "date"]
    assert len(result["planner_instruction"].instruction_nl) > 0

    # Backward-compat AnalysisIntent
    assert isinstance(result["analysis_intent"], AnalysisIntent)
    assert result["analysis_intent"].analysis_type == "diagnostic"

    # feedback should be consumed
    assert result["feedback"] is None


@pytest.mark.unit
def test_bt_agent_with_dialogue_history(
    set_llm_env: None, bt_tool_call_msg: object
) -> None:
    """BT Agent receives dialogue history in its user context."""
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.invoke.return_value = bt_tool_call_msg

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="按地区拆分",
        unified_columns=["sales", "region", "date"],
        dialogue_history=[
            {"role": "user", "content": "分析Q2销售趋势"},
            {"role": "assistant", "content": "我将按地区和产品线分析Q2销售趋势..."},
        ],
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        result, meta = business_track_node(state)

    assert "error" not in result
    assert meta["_bt_tool_called"] is True
    # Verify history was injected into the prompt
    call_args = mock_llm.invoke.call_args[0][0]
    # Find the HumanMessage containing user context with history
    history_found = False
    for msg in call_args:
        content = getattr(msg, "content", "")
        if isinstance(content, str) and "Q2销售趋势" in content:
            history_found = True
            break
    assert history_found


@pytest.mark.unit
def test_bt_agent_inspects_column(set_llm_env: None) -> None:
    """BT Agent calls inspect_column, sees result, then calls submit_planner_instruction."""
    _ = set_llm_env

    from langchain_core.messages import AIMessage

    # First call: inspect_column, second call: submit_planner_instruction
    inspect_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "inspect_column",
                "args": {"column_name": "region"},
                "id": "call_inspect_001",
            }
        ],
    )
    submit_msg = AIMessage(
        content="I've checked the region column. Submitting now.",
        tool_calls=[
            {
                "name": "submit_planner_instruction",
                "args": {
                    "core_question": "Analyze sales by region",
                    "analysis_type": "descriptive",
                    "complexity": "simple",
                    "target_columns": ["sales"],
                    "group_by": ["region"],
                    "filter_hint": None,
                    "unit_suggestions": [],
                    "is_revision": False,
                    "target_unit_ids": [],
                    "revision_notes": None,
                    "suggestions": [],
                    "caution_notes": None,
                    "instruction_nl": "Regional analysis of sales data.",
                },
                "id": "call_submit_002",
            }
        ],
    )

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.invoke.side_effect = [inspect_msg, submit_msg]

    from src.agent.state import ColumnProfile, DataProfile

    data_profile = DataProfile(
        file_path="/tmp/test.csv",
        shape=(100, 3),
        columns=[
            ColumnProfile(
                name="region", dtype="object", null_count=2, null_pct=2.0,
                unique_count=4, unique_pct=4.0,
            ),
            ColumnProfile(
                name="sales", dtype="float64", null_count=0, null_pct=0.0,
                unique_count=50, unique_pct=50.0,
            ),
        ],
        statistics={
            "region": {"count": 98, "unique": 4, "top": "East", "freq": 30},
        },
        head_sample=[{"region": "East", "sales": 500.0}],
    )

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales by region",
        unified_columns=["sales", "region"],
        data_profile=data_profile,
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        result, meta = business_track_node(state)

    assert "error" not in result
    assert meta["_bt_tool_called"] is True
    assert result["planner_instruction"].analysis_type == "descriptive"
    assert result["planner_instruction"].group_by == ["region"]
    assert mock_llm.invoke.call_count == 2


@pytest.mark.unit
def test_bt_agent_revision_scenario(
    set_llm_env: None,
) -> None:
    """BT Agent with workspace + revision message → is_revision=True."""
    _ = set_llm_env

    from src.agent.state import Plan, PlanUnit

    workspace = Plan(
        units=[
            PlanUnit(
                unit_id=1, purpose="按地区分析趋势", model="线性回归",
                cautious="region列有缺失", related_fields=["region"],
            )
        ],
        alignment_notes="第一版计划。",
    )

    from langchain_core.messages import AIMessage

    revision_msg = AIMessage(
        content="我理解了，您想修改第1个分析单元。让我提交修订指令。",
        tool_calls=[
            {
                "name": "submit_planner_instruction",
                "args": {
                    "core_question": "把地区分析拆成华东和华南",
                    "analysis_type": "comparative",
                    "complexity": "moderate",
                    "target_columns": ["sales"],
                    "group_by": ["region"],
                    "filter_hint": None,
                    "unit_suggestions": [],
                    "is_revision": True,
                    "target_unit_ids": [1],
                    "revision_notes": "Split region analysis into East and South China",
                    "suggestions": [],
                    "caution_notes": None,
                    "instruction_nl": "用户要求将地区分析拆分为华东和华南两个区域。",
                },
                "id": "call_revise_001",
            }
        ],
    )

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.invoke.return_value = revision_msg

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="把地区分析拆成华东和华南",
        unified_columns=["sales", "region"],
        plan=workspace,
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        result, meta = business_track_node(state)

    assert "error" not in result
    assert meta["_bt_tool_called"] is True
    assert result["planner_instruction"].is_revision is True
    assert result["planner_instruction"].target_unit_ids == [1]
    assert result["planner_instruction"].revision_notes is not None


@pytest.mark.unit
def test_bt_agent_cli_mode_direct_tool_call(
    set_llm_env: None, bt_tool_call_msg: object
) -> None:
    """CLI mode (no history, no plan, has message) → BT goes straight to tool call."""
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.invoke.return_value = bt_tool_call_msg

    # CLI mode: no dialogue_history, no plan, has message
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Why did Q2 sales drop?",
        unified_columns=["sales", "region", "date"],
        # No dialogue_history, no plan → CLI mode
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        result, _ = business_track_node(state)

    assert "error" not in result
    # CLI mode prompt should contain indication
    call_args = mock_llm.invoke.call_args[0][0]
    cli_found = False
    for msg in call_args:
        content = getattr(msg, "content", "")
        if isinstance(content, str) and "CLI" in content:
            cli_found = True
            break
    assert cli_found


@pytest.mark.unit
def test_bt_agent_consumes_feedback(set_llm_env: None, bt_tool_call_msg: object) -> None:
    """BT Agent consumes feedback (sets to None in return dict)."""
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.invoke.return_value = bt_tool_call_msg

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Reanalyze with monthly data",
        unified_columns=["sales", "region", "date"],
        feedback="The chart was wrong, use monthly data instead.",
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        result, _ = business_track_node(state)

    assert "error" not in result
    assert result["feedback"] is None


@pytest.mark.unit
def test_bt_agent_llm_error(set_llm_env: None) -> None:
    """BT Agent handles LLM errors gracefully."""
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.invoke.side_effect = RuntimeError("API timeout")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        result, _ = business_track_node(state)

    assert "error" in result
    assert "API timeout" in result["error"]


@pytest.mark.unit
def test_bt_agent_no_columns(set_llm_env: None, bt_chat_msg: object) -> None:
    """BT Agent handles scenario with no data uploaded."""
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.invoke.return_value = bt_chat_msg

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="分析销售",
        # No unified_columns → no data
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        result, meta = business_track_node(state)

    assert "error" not in result
    assert meta["_bt_tool_called"] is False
    assert result["planner_instruction"] is None
