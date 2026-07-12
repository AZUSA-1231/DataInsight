from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agent.graph import (
    _should_iterate,
    build_graph,
)
from src.agent.state import AgentState, AnalysisIntent


def _bt_tool_call_msg(**overrides: object) -> AIMessage:
    """Build a mock AIMessage with submit_planner_instruction tool call."""
    args: dict[str, object] = {
        "core_question": "Test requirement",
        "analysis_type": "diagnostic",
        "complexity": "moderate",
        "target_columns": [],
        "group_by": ["time period"],
        "filter_hint": None,
        "unit_suggestions": [],
        "is_revision": False,
        "target_unit_ids": [],
        "revision_notes": None,
        "suggestions": [],
        "caution_notes": None,
        "instruction_nl": "Test instruction for diagnostics.",
    }
    args.update(overrides)  # type: ignore[arg-type]
    return AIMessage(
        content="Test analysis explanation.",
        tool_calls=[
            {"name": "submit_planner_instruction", "args": args, "id": "call_test_001"}
        ],
    )


_PLAN_JSON = json.dumps(
    {
        "units": [
            {
                "unit_id": 1,
                "purpose": "按区域分析销售趋势",
                "model": "线性回归",
                "cautious": "region列有2%缺失值",
                "depends_on": [],
                "related_fields": ["销量", "地区"],
            }
        ],
        "alignment_notes": "基于当前数据，本报告能够部分回答用户问题。",
    },
    ensure_ascii=False,
)


@pytest.mark.unit
def test_graph_compiles() -> None:
    graph = build_graph()
    assert graph is not None


@pytest.mark.unit
def test_graph_node_names() -> None:
    graph = build_graph()
    node_names = list(graph.nodes.keys())

    assert "data_track" in node_names
    assert "business_track" in node_names
    assert "planner" in node_names
    assert "analysis" in node_names
    assert "report_gen" in node_names


@pytest.mark.integration
def test_graph_data_track_integration(
    sample_csv_path: str, set_llm_env: None) -> None:
    """Invoke graph: serial data_track → business_track → planner, mocked downstream."""
    _ = set_llm_env

    mock_bt = MagicMock()
    mock_bt.bind_tools.return_value = mock_bt
    mock_bt.invoke.return_value = _bt_tool_call_msg()

    mock_dm = MagicMock()
    mock_dm.invoke.return_value = MagicMock(content=_PLAN_JSON)

    mock_an = MagicMock()
    mock_an.invoke.return_value = MagicMock(content="print('{}')\n")

    mock_rg = MagicMock()
    mock_rg.invoke.return_value = MagicMock(content="# DataInsight Report\n\nMocked.")

    from src.sandbox.executor import SandboxResult

    an_sandbox_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 5, "cols": 2}}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    state = AgentState(
        file_path=sample_csv_path,
        user_requirement="Test requirement",
    )

    graph = build_graph()

    with (
        patch("src.agent.nodes.business_track.get_llm", return_value=mock_bt),
        patch("src.agent.nodes.planner.get_llm", return_value=mock_dm),
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_an),
        patch("src.agent.nodes.analysis.run_script", return_value=an_sandbox_result),
        patch("src.agent.nodes.report_gen.get_llm", return_value=mock_rg),
    ):
        graph.invoke(state)

    mock_bt.invoke.assert_called_once()
    mock_dm.invoke.assert_called_once()


@pytest.mark.integration
def test_graph_m2_full_pipeline(
    sample_csv_path: str, set_llm_env: None) -> None:
    """Full pipeline: data_track → business_track → planner."""
    _ = set_llm_env

    from src.agent.nodes.business_track import business_track_node
    from src.agent.nodes.data_track import data_track_node
    from src.agent.nodes.planner import planner_node

    mock_bt = MagicMock()
    mock_bt.bind_tools.return_value = mock_bt
    mock_bt.invoke.return_value = _bt_tool_call_msg()

    mock_dm = MagicMock()
    mock_dm.invoke.return_value = MagicMock(content=_PLAN_JSON)

    state = AgentState(
        file_path=sample_csv_path,
        user_requirement="Why did Q2 sales drop by 15%?",
    )

    with (
        patch("src.agent.nodes.business_track.get_llm", return_value=mock_bt),
        patch("src.agent.nodes.planner.get_llm", return_value=mock_dm),
    ):
        dt_update = data_track_node(state)
        state = AgentState(**(state.model_dump() | dt_update))
        bt_update, _ = business_track_node(state)
        state = AgentState(**(state.model_dump() | bt_update))
        dm_update = planner_node(state)
        state = AgentState(**(state.model_dump() | dm_update))

    mock_bt.invoke.assert_called_once()
    mock_dm.invoke.assert_called_once()

    assert state.data_profile is not None
    assert state.unified_columns is not None
    assert len(state.unified_columns) == 5  # name, age, salary, dept, hire_date
    assert state.analysis_intent is not None
    assert state.plan is not None
    assert isinstance(state.analysis_intent, AnalysisIntent)
    assert state.analysis_intent.analysis_type == "diagnostic"
    assert len(state.plan.units) == 1
    assert "部分回答用户问题" in state.plan.alignment_notes
    assert state.error is None


@pytest.mark.integration
def test_graph_m3_execution_integration(
    sample_csv_path: str, set_llm_env: None, temp_output_dir: str) -> None:
    """Full pipeline: data_track, business_track, planner,
    analysis with mocked LLMs and sandbox."""
    _ = set_llm_env

    from src.agent.nodes.analysis import analysis_node
    from src.agent.nodes.business_track import business_track_node
    from src.agent.nodes.data_track import data_track_node
    from src.agent.nodes.planner import planner_node
    from src.sandbox.executor import SandboxResult

    mock_bt = MagicMock()
    mock_bt.bind_tools.return_value = mock_bt
    mock_bt.invoke.return_value = _bt_tool_call_msg()

    mock_dm = MagicMock()
    mock_dm.invoke.return_value = MagicMock(content=_PLAN_JSON)

    mock_an = MagicMock()
    mock_an.invoke.return_value = MagicMock(content="print('{}')\n")

    an_sandbox_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 10, "cols": 3},'
        ' "cleaning_actions": ["dropped nulls"],'
        ' "charts": ["out/chart1.png"],'
        ' "statistics": {},'
        ' "insights": ["Sales rose in Q3"]}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    state = AgentState(
        file_path=sample_csv_path,
        user_requirement="Why did Q2 sales drop?",
    )

    with (
        patch("src.agent.nodes.business_track.get_llm", return_value=mock_bt),
        patch("src.agent.nodes.planner.get_llm", return_value=mock_dm),
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_an),
        patch("src.agent.nodes.analysis.run_script", return_value=an_sandbox_result),
    ):
        dt_update = data_track_node(state)
        state = AgentState(**(state.model_dump() | dt_update))
        bt_update, _ = business_track_node(state)
        state = AgentState(**(state.model_dump() | bt_update))
        dm_update = planner_node(state)
        state = AgentState(**(state.model_dump() | dm_update))
        an_update = analysis_node(state)
        state = AgentState(**(state.model_dump() | an_update))

    assert state.data_profile is not None
    assert state.unified_columns is not None
    assert state.analysis_intent is not None
    assert state.plan is not None
    assert state.analysis_result is not None
    assert state.error is None

    result = state.analysis_result
    assert "unit_results" in result
    assert len(result["unit_results"]) == 1
    assert result["unit_results"][0]["status"] == "success"
    assert result["unit_results"][0]["insights"] == ["Sales rose in Q3"]

    mock_bt.invoke.assert_called_once()
    mock_dm.invoke.assert_called_once()
    mock_an.invoke.assert_called_once()


@pytest.mark.integration
def test_graph_m4_full_pipeline(
    sample_csv_path: str,
    set_llm_env: None,
    sample_analysis_result: dict,
) -> None:
    """Full 5-node pipeline: data_track → business_track → planner →
    analysis → report_gen."""
    _ = set_llm_env

    from src.agent.nodes.analysis import analysis_node
    from src.agent.nodes.business_track import business_track_node
    from src.agent.nodes.data_track import data_track_node
    from src.agent.nodes.planner import planner_node
    from src.agent.nodes.report_gen import report_gen_node
    from src.sandbox.executor import SandboxResult

    mock_bt = MagicMock()
    mock_bt.bind_tools.return_value = mock_bt
    mock_bt.invoke.return_value = _bt_tool_call_msg()

    mock_dm = MagicMock()
    mock_dm.invoke.return_value = MagicMock(content=_PLAN_JSON)

    mock_an = MagicMock()
    mock_an.invoke.return_value = MagicMock(content="print('{}')\n")

    mock_rg = MagicMock()
    mock_rg.invoke.return_value = MagicMock(
        content="# DataInsight 数据分析报告\n\nFull report with 数据与业务对齐备忘."
    )

    an_sandbox_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 10, "cols": 3}}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    state = AgentState(
        file_path=sample_csv_path,
        user_requirement="Why did Q2 sales drop?",
    )

    with (
        patch("src.agent.nodes.business_track.get_llm", return_value=mock_bt),
        patch("src.agent.nodes.planner.get_llm", return_value=mock_dm),
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_an),
        patch("src.agent.nodes.analysis.run_script", return_value=an_sandbox_result),
        patch("src.agent.nodes.report_gen.get_llm", return_value=mock_rg),
    ):
        dt_update = data_track_node(state)
        state = AgentState(**(state.model_dump() | dt_update))
        bt_update, _ = business_track_node(state)
        state = AgentState(**(state.model_dump() | bt_update))
        dm_update = planner_node(state)
        state = AgentState(**(state.model_dump() | dm_update))
        an_update = analysis_node(state)
        state = AgentState(**(state.model_dump() | an_update))
        rg_update = report_gen_node(state)
        state = AgentState(**(state.model_dump() | rg_update))

    assert state.final_report is not None
    assert state.error is None
    assert "DataInsight" in state.final_report
    assert "数据与业务对齐备忘" in state.final_report

    mock_rg.invoke.assert_called_once()


@pytest.mark.integration
def test_graph_feedback_iteration(
    set_llm_env: None,
    sample_analysis_result: dict,
    sample_data_profile: object,
    sample_analysis_intent: object,
) -> None:
    """Feedback loop: user feedback → business_track (re-parses intent) →
    planner → analysis → report_gen regenerates."""
    _ = set_llm_env

    from src.agent.nodes.analysis import analysis_node
    from src.agent.nodes.business_track import business_track_node
    from src.agent.nodes.planner import planner_node
    from src.agent.nodes.report_gen import report_gen_node
    from src.agent.state import Plan, PlanUnit
    from src.sandbox.executor import SandboxResult

    existing_plan = Plan(
        units=[
            PlanUnit(
                unit_id=1, purpose="按区域分析销售趋势", model="线性回归",
                cautious="region列有2%缺失值", related_fields=["销量", "地区"],
            )
        ],
        alignment_notes="基于当前数据，能够部分回答用户问题。",
    )

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        unified_columns=["销量", "地区", "日期"],
        analysis_intent=sample_analysis_intent,
        plan=existing_plan,
        feedback="The chart on regional sales is wrong, use monthly data instead.",
    )

    mock_bt = MagicMock()
    mock_bt.bind_tools.return_value = mock_bt
    mock_bt.invoke.return_value = _bt_tool_call_msg(
        core_question="Analyze sales with monthly data",
        analysis_type="trend",
        is_revision=True,
        target_unit_ids=[1],
        revision_notes="Changed from quarterly to monthly granularity",
        instruction_nl="Revised: use monthly data for regional analysis.",
    )

    mock_dm = MagicMock()
    mock_dm.invoke.return_value = MagicMock(
        content=json.dumps(
            {
                "units": [
                    {
                        "unit_id": 1,
                        "purpose": "Monthly trend",
                        "model": "pandas.DataFrame.resample",
                        "cautious": "日期格式需统一",
                        "depends_on": [],
                        "related_fields": ["日期", "销量"],
                    }
                ],
                "alignment_notes": "修订版：基于用户反馈改用月度分组。",
            },
            ensure_ascii=False,
        )
    )

    mock_an = MagicMock()
    mock_an.invoke.return_value = MagicMock(content="print('{}')\n")

    mock_rg = MagicMock()
    mock_rg.invoke.return_value = MagicMock(
        content="# DataInsight 数据分析报告\n\nRevised report."
    )

    an_sandbox_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 10, "cols": 3}}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    with (
        patch("src.agent.nodes.business_track.get_llm", return_value=mock_bt),
        patch("src.agent.nodes.planner.get_llm", return_value=mock_dm),
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_an),
        patch("src.agent.nodes.analysis.run_script", return_value=an_sandbox_result),
        patch("src.agent.nodes.report_gen.get_llm", return_value=mock_rg),
    ):
        bt_update, _ = business_track_node(state)
        state = AgentState(**(state.model_dump() | bt_update))
        dm_update = planner_node(state)
        state = AgentState(**(state.model_dump() | dm_update))
        an_update = analysis_node(state)
        state = AgentState(**(state.model_dump() | an_update))
        rg_update = report_gen_node(state)
        state = AgentState(**(state.model_dump() | rg_update))

    assert state.feedback is None
    assert state.plan is not None
    assert "修订版" in state.plan.alignment_notes
    assert state.final_report is not None
    assert state.error is None

    mock_bt.invoke.assert_called_once()
    mock_dm.invoke.assert_called_once()
    mock_rg.invoke.assert_called_once()


@pytest.mark.unit
def test_graph_should_iterate() -> None:
    """Verify the feedback iteration routing logic."""

    state_no_feedback = AgentState(file_path="", user_requirement="")
    assert _should_iterate(state_no_feedback) == "__end__"

    state_with_feedback = AgentState(
        file_path="",
        user_requirement="",
        feedback="Change the chart type to bar",
    )
    assert _should_iterate(state_with_feedback) == "business_track"
