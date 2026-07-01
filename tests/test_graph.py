from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agent.graph import (
    _should_iterate,
    _should_retry_analysis,
    _should_retry_preprocessing,
    build_graph,
)
from src.agent.state import AgentState, AnalysisIntent, ExecutionPlan

_INTENT_JSON = json.dumps(
    {
        "core_question": "Test requirement",
        "target_variable": None,
        "analysis_type": "diagnostic",
        "dimensions": ["time period"],
        "comparison_baseline": None,
    }
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
    assert "decision_match" in node_names
    assert "preprocessing" in node_names
    assert "analysis" in node_names
    assert "report_gen" in node_names


@pytest.mark.integration
def test_graph_data_track_integration(
    sample_csv_path: str, set_llm_env: None, make_execution_plan: object
) -> None:
    """Invoke the graph with parallel data_track + business_track and mocked downstream nodes."""
    _ = set_llm_env

    mock_dt = MagicMock()
    mock_dt.invoke.return_value = MagicMock(content="## 数据清洗建议\n\nCleaning insights.")

    mock_bt = MagicMock()
    mock_bt.invoke.return_value = MagicMock(content=_INTENT_JSON)

    mock_dm = MagicMock()
    mock_dm.invoke.return_value = MagicMock(
        content=make_execution_plan(preprocessing_steps=[]).model_dump_json()
    )

    mock_pre = MagicMock()
    mock_pre.invoke.return_value = MagicMock(content="print('{}')\n")

    mock_an = MagicMock()
    mock_an.invoke.return_value = MagicMock(content="print('{}')\n")

    mock_rg = MagicMock()
    mock_rg.invoke.return_value = MagicMock(content="# DataInsight Report\n\nMocked.")

    from src.sandbox.executor import SandboxResult

    pre_sandbox_result = SandboxResult(
        stdout=(
            '{"cleaned_shape": {"rows": 5, "cols": 2}, "cleaning_actions": [],'
            ' "cleaned_data_path": "/tmp/out/cleaned_data.csv"}'
        ),
        stderr="",
        exit_code=0,
        timed_out=False,
    )

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
        patch("src.agent.nodes.data_track.get_llm", return_value=mock_dt),
        patch("src.agent.nodes.business_track.get_llm", return_value=mock_bt),
        patch("src.agent.nodes.decision_match.get_llm", return_value=mock_dm),
        patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_pre),
        patch("src.agent.nodes.preprocessing.run_script", return_value=pre_sandbox_result),
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_an),
        patch("src.agent.nodes.analysis.run_script", return_value=an_sandbox_result),
        patch("src.agent.nodes.report_gen.get_llm", return_value=mock_rg),
    ):
        graph.invoke(state)

    # Both parallel tracks should have been called
    mock_dt.invoke.assert_called_once()
    mock_bt.invoke.assert_called_once()
    mock_dm.invoke.assert_called_once()
    mock_an.invoke.assert_called_once()


@pytest.mark.integration
def test_graph_m2_full_pipeline(
    sample_csv_path: str, set_llm_env: None, make_execution_plan: object
) -> None:
    """Full M1+M2 pipeline: data_track → business_track → decision_match."""
    _ = set_llm_env

    from src.agent.nodes.business_track import business_track_node
    from src.agent.nodes.data_track import data_track_node
    from src.agent.nodes.decision_match import decision_match_node

    mock_dt = MagicMock()
    mock_dt_response = MagicMock()
    mock_dt_response.content = "## 数据清洗建议\n\nCleaning insights."
    mock_dt.invoke.return_value = mock_dt_response

    mock_bt = MagicMock()
    mock_bt_response = MagicMock()
    mock_bt_response.content = _INTENT_JSON
    mock_bt.invoke.return_value = mock_bt_response

    mock_dm = MagicMock()
    mock_dm_response = MagicMock()
    mock_dm_response.content = make_execution_plan(preprocessing_steps=[]).model_dump_json()
    mock_dm.invoke.return_value = mock_dm_response

    state = AgentState(
        file_path=sample_csv_path,
        user_requirement="Why did Q2 sales drop by 15%?",
    )

    with (
        patch("src.agent.nodes.data_track.get_llm", return_value=mock_dt),
        patch("src.agent.nodes.business_track.get_llm", return_value=mock_bt),
        patch("src.agent.nodes.decision_match.get_llm", return_value=mock_dm),
    ):
        dt_update = data_track_node(state)
        state = AgentState(**(state.model_dump() | dt_update))
        bt_update = business_track_node(state)
        state = AgentState(**(state.model_dump() | bt_update))
        dm_update = decision_match_node(state)
        state = AgentState(**(state.model_dump() | dm_update))

    mock_dt.invoke.assert_called_once()
    mock_bt.invoke.assert_called_once()
    mock_dm.invoke.assert_called_once()

    assert state.data_profile is not None
    assert state.cleaning_insights is not None
    assert state.analysis_intent is not None
    assert state.execution_plan is not None
    assert "数据清洗建议" in (state.cleaning_insights or "")
    assert isinstance(state.analysis_intent, AnalysisIntent)
    assert state.analysis_intent.analysis_type == "diagnostic"
    assert isinstance(state.execution_plan, ExecutionPlan)
    assert len(state.execution_plan.feasibility_map) == 1
    assert "部分回答用户问题" in state.execution_plan.alignment_notes
    assert state.error is None


@pytest.mark.integration
def test_graph_m3_execution_integration(
    sample_csv_path: str, set_llm_env: None, temp_output_dir: str, make_execution_plan: object
) -> None:
    """Full M1+M2+M3a+M3b pipeline: data_track, business_track, decision_match,
    preprocessing, analysis with mocked LLMs and sandbox."""
    _ = set_llm_env

    from src.agent.nodes.analysis import analysis_node
    from src.agent.nodes.business_track import business_track_node
    from src.agent.nodes.data_track import data_track_node
    from src.agent.nodes.decision_match import decision_match_node
    from src.agent.nodes.preprocessing import preprocessing_node
    from src.sandbox.executor import SandboxResult

    mock_dt = MagicMock()
    mock_dt.invoke.return_value = MagicMock(content="## 数据清洗建议\n\nClean.")

    mock_bt = MagicMock()
    mock_bt.invoke.return_value = MagicMock(content=_INTENT_JSON)

    mock_dm = MagicMock()
    mock_dm.invoke.return_value = MagicMock(
        content=make_execution_plan(preprocessing_steps=[]).model_dump_json()
    )

    mock_pre = MagicMock()
    mock_pre.invoke.return_value = MagicMock(content="print('{}')\n")

    mock_an = MagicMock()
    mock_an.invoke.return_value = MagicMock(content="print('{}')\n")

    pre_sandbox_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 10, "cols": 3},'
        ' "cleaning_actions": ["dropped nulls"],'
        ' "cleaned_data_path": "/tmp/out/cleaned_data.csv"}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

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
        patch("src.agent.nodes.data_track.get_llm", return_value=mock_dt),
        patch("src.agent.nodes.business_track.get_llm", return_value=mock_bt),
        patch("src.agent.nodes.decision_match.get_llm", return_value=mock_dm),
        patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_pre),
        patch("src.agent.nodes.preprocessing.run_script", return_value=pre_sandbox_result),
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_an),
        patch("src.agent.nodes.analysis.run_script", return_value=an_sandbox_result),
    ):
        dt_update = data_track_node(state)
        state = AgentState(**(state.model_dump() | dt_update))
        bt_update = business_track_node(state)
        state = AgentState(**(state.model_dump() | bt_update))
        dm_update = decision_match_node(state)
        state = AgentState(**(state.model_dump() | dm_update))
        pre_update = preprocessing_node(state)
        state = AgentState(**(state.model_dump() | pre_update))
        an_update = analysis_node(state)
        state = AgentState(**(state.model_dump() | an_update))

    assert state.data_profile is not None
    assert state.analysis_intent is not None
    assert state.execution_plan is not None
    assert isinstance(state.execution_plan, ExecutionPlan)
    assert state.preprocessing_result is not None
    assert state.preprocessing_result["skipped"] is True
    assert state.preprocessing_result["cleaned_data_path"] == sample_csv_path
    assert state.analysis_result is not None
    assert state.error is None

    result = state.analysis_result
    assert "parsed_output" in result
    assert result["parsed_output"]["insights"] == ["Sales rose in Q3"]
    assert result["retry_count"] == 0

    mock_dt.invoke.assert_called_once()
    mock_bt.invoke.assert_called_once()
    mock_dm.invoke.assert_called_once()
    mock_an.invoke.assert_called_once()


@pytest.mark.unit
def test_graph_conditional_edges_preprocessing() -> None:
    """Verify the preprocessing ReAct retry routing logic."""

    # Success (no error) — go to analysis
    state_ok = AgentState(file_path="", user_requirement="")
    assert _should_retry_preprocessing(state_ok) == "analysis"

    # Error + retry_count < 3 — retry preprocessing
    state_retry = AgentState(
        file_path="",
        user_requirement="",
        error="KeyError: 'region'",
        preprocessing_result={"retry_count": 1},
    )
    assert _should_retry_preprocessing(state_retry) == "preprocessing"

    # Error + retry_count >= 3 — give up, go to report_gen
    state_give_up = AgentState(
        file_path="",
        user_requirement="",
        error="failed again",
        preprocessing_result={"retry_count": 3},
    )
    assert _should_retry_preprocessing(state_give_up) == "report_gen"


@pytest.mark.unit
def test_graph_conditional_edges_analysis() -> None:
    """Verify the analysis ReAct retry routing logic."""

    # No error — go to report_gen
    state_no_error = AgentState(file_path="", user_requirement="")
    assert _should_retry_analysis(state_no_error) == "report_gen"

    # Error + retry_count < 3 — retry analysis
    state_with_error = AgentState(
        file_path="",
        user_requirement="",
        error="something failed",
        analysis_result={"retry_count": 1},
    )
    assert _should_retry_analysis(state_with_error) == "analysis"

    # Error + retry_count >= 3 — give up, go to report_gen
    state_max_retries = AgentState(
        file_path="",
        user_requirement="",
        error="failed again",
        analysis_result={"retry_count": 3},
    )
    assert _should_retry_analysis(state_max_retries) == "report_gen"


@pytest.mark.integration
def test_graph_m4_full_pipeline(
    sample_csv_path: str,
    set_llm_env: None,
    sample_analysis_result: dict,
    make_execution_plan: object,
) -> None:
    """Full 6-node pipeline: data_track → business_track → decision_match →
    preprocessing → analysis → report_gen."""
    _ = set_llm_env

    from src.agent.nodes.analysis import analysis_node
    from src.agent.nodes.business_track import business_track_node
    from src.agent.nodes.data_track import data_track_node
    from src.agent.nodes.decision_match import decision_match_node
    from src.agent.nodes.preprocessing import preprocessing_node
    from src.agent.nodes.report_gen import report_gen_node
    from src.sandbox.executor import SandboxResult

    mock_dt = MagicMock()
    mock_dt.invoke.return_value = MagicMock(content="## 数据清洗建议\n\nClean.")

    mock_bt = MagicMock()
    mock_bt.invoke.return_value = MagicMock(content=_INTENT_JSON)

    mock_dm = MagicMock()
    mock_dm.invoke.return_value = MagicMock(
        content=make_execution_plan(preprocessing_steps=[]).model_dump_json()
    )

    mock_pre = MagicMock()
    mock_pre.invoke.return_value = MagicMock(content="print('{}')\n")

    mock_an = MagicMock()
    mock_an.invoke.return_value = MagicMock(content="print('{}')\n")

    mock_rg = MagicMock()
    mock_rg.invoke.return_value = MagicMock(
        content="# DataInsight 数据分析报告\n\nFull report with 数据与业务对齐备忘."
    )

    pre_sandbox_result = SandboxResult(
        stdout=(
            '{"cleaned_shape": {"rows": 10, "cols": 3}, "cleaning_actions": [],'
            ' "cleaned_data_path": "/tmp/out/cleaned_data.csv"}'
        ),
        stderr="",
        exit_code=0,
        timed_out=False,
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
        patch("src.agent.nodes.data_track.get_llm", return_value=mock_dt),
        patch("src.agent.nodes.business_track.get_llm", return_value=mock_bt),
        patch("src.agent.nodes.decision_match.get_llm", return_value=mock_dm),
        patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_pre),
        patch("src.agent.nodes.preprocessing.run_script", return_value=pre_sandbox_result),
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_an),
        patch("src.agent.nodes.analysis.run_script", return_value=an_sandbox_result),
        patch("src.agent.nodes.report_gen.get_llm", return_value=mock_rg),
    ):
        dt_update = data_track_node(state)
        state = AgentState(**(state.model_dump() | dt_update))
        bt_update = business_track_node(state)
        state = AgentState(**(state.model_dump() | bt_update))
        dm_update = decision_match_node(state)
        state = AgentState(**(state.model_dump() | dm_update))
        pre_update = preprocessing_node(state)
        state = AgentState(**(state.model_dump() | pre_update))
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
    make_execution_plan: object,
) -> None:
    """Feedback loop: user feedback → decision_match revises → preprocessing →
    analysis → report_gen regenerates."""
    _ = set_llm_env

    from src.agent.nodes.analysis import analysis_node
    from src.agent.nodes.decision_match import decision_match_node
    from src.agent.nodes.preprocessing import preprocessing_node
    from src.agent.nodes.report_gen import report_gen_node
    from src.sandbox.executor import SandboxResult

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        cleaning_insights="## 数据清洗建议\nClean.",
        analysis_intent=sample_analysis_intent,
        execution_plan=make_execution_plan(
            preprocessing_steps=[], analysis_steps=[], model_selections=[]
        ),
        feedback="The chart on regional sales is wrong, use monthly data instead.",
    )

    mock_dm = MagicMock()
    mock_dm.invoke.return_value = MagicMock(
        content=make_execution_plan(
            feasibility_map=[
                {
                    "intent_dimension": "monthly",
                    "matched_columns": ["date"],
                    "feasibility": "可直接实现",
                    "confidence": "High",
                    "reasoning": "Monthly grouping per feedback",
                }
            ],
            model_selections=[
                {
                    "analysis_step": "Monthly trend",
                    "method": "pandas.DataFrame.resample",
                    "reasoning": "Monthly resample as requested",
                    "feasibility": "可直接实现",
                }
            ],
            preprocessing_steps=[],
            analysis_steps=[],
            alignment_notes="修订版：基于用户反馈改用月度分组。",
        ).model_dump_json()
    )

    mock_pre = MagicMock()
    mock_pre.invoke.return_value = MagicMock(content="print('{}')\n")

    mock_an = MagicMock()
    mock_an.invoke.return_value = MagicMock(content="print('{}')\n")

    mock_rg = MagicMock()
    mock_rg.invoke.return_value = MagicMock(content="# DataInsight 数据分析报告\n\nRevised report.")

    pre_sandbox_result = SandboxResult(
        stdout=(
            '{"cleaned_shape": {"rows": 10, "cols": 3}, "cleaning_actions": [],'
            ' "cleaned_data_path": "/tmp/out/cleaned_data.csv"}'
        ),
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    an_sandbox_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 10, "cols": 3}}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    with (
        patch("src.agent.nodes.decision_match.get_llm", return_value=mock_dm),
        patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_pre),
        patch("src.agent.nodes.preprocessing.run_script", return_value=pre_sandbox_result),
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_an),
        patch("src.agent.nodes.analysis.run_script", return_value=an_sandbox_result),
        patch("src.agent.nodes.report_gen.get_llm", return_value=mock_rg),
    ):
        dm_update = decision_match_node(state)
        state = AgentState(**(state.model_dump() | dm_update))
        pre_update = preprocessing_node(state)
        state = AgentState(**(state.model_dump() | pre_update))
        an_update = analysis_node(state)
        state = AgentState(**(state.model_dump() | an_update))
        rg_update = report_gen_node(state)
        state = AgentState(**(state.model_dump() | rg_update))

    assert state.feedback is None
    assert state.execution_plan is not None
    assert isinstance(state.execution_plan, ExecutionPlan)
    assert "修订版" in state.execution_plan.alignment_notes
    assert state.final_report is not None
    assert state.error is None

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
    assert _should_iterate(state_with_feedback) == "decision_match"
