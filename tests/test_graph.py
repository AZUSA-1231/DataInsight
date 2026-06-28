from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

import pytest

from src.agent.graph import build_graph
from src.agent.state import AgentState


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
    assert "execution" in node_names
    assert "report_gen" in node_names


@pytest.mark.integration
def test_graph_data_track_integration(
    sample_csv_path: str, set_llm_env: None
) -> None:
    """Invoke the graph with a real Data Track node and mocked downstream nodes.

    All downstream LLMs are mocked. The graph stops at execution (stub)
    which raises NotImplementedError.
    """
    _ = set_llm_env

    mock_dt = MagicMock()
    mock_dt.invoke.return_value = MagicMock(content="# 数据技术盘报告\n\nIntegration test report.")

    mock_bt = MagicMock()
    mock_bt.invoke.return_value = MagicMock(content="## 业务分析蓝图\n\nBusiness plan.")

    mock_dm = MagicMock()
    mock_dm.invoke.return_value = MagicMock(content="## 分析执行计划\n\nExecution plan.")

    mock_ex = MagicMock()
    mock_ex.invoke.return_value = MagicMock(content="print('{}')\n")

    from src.sandbox.executor import SandboxResult

    sandbox_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 5, "cols": 2}}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    state: AgentState = {
        "file_path": sample_csv_path,
        "user_requirement": "Test requirement",
    }

    graph = build_graph()

    with (
        patch("src.agent.nodes.data_track.get_llm", return_value=mock_dt),
        patch("src.agent.nodes.business_track.get_llm", return_value=mock_bt),
        patch("src.agent.nodes.decision_match.get_llm", return_value=mock_dm),
        patch("src.agent.nodes.execution.get_llm", return_value=mock_ex),
        patch("src.agent.nodes.execution.run_script", return_value=sandbox_result),
        contextlib.suppress(NotImplementedError),
    ):
        graph.invoke(state)

    mock_dt.invoke.assert_called_once()
    mock_bt.invoke.assert_called_once()
    mock_dm.invoke.assert_called_once()
    mock_ex.invoke.assert_called_once()


@pytest.mark.integration
def test_graph_m2_full_pipeline(
    sample_csv_path: str, set_llm_env: None
) -> None:
    """Full M1+M2 pipeline: data_track → business_track → decision_match.

    Nodes are called sequentially (matching graph edge order) with mocked LLMs.
    We verify state flows correctly through all three real nodes.
    """
    _ = set_llm_env

    from src.agent.nodes.business_track import business_track_node
    from src.agent.nodes.data_track import data_track_node
    from src.agent.nodes.decision_match import decision_match_node

    mock_dt = MagicMock()
    mock_dt_response = MagicMock()
    mock_dt_response.content = "## 数据技术盘报告\n\nData audit."
    mock_dt.invoke.return_value = mock_dt_response

    mock_bt = MagicMock()
    mock_bt_response = MagicMock()
    mock_bt_response.content = "## 业务分析蓝图\n\nBusiness plan."
    mock_bt.invoke.return_value = mock_bt_response

    mock_dm = MagicMock()
    mock_dm_response = MagicMock()
    mock_dm_response.content = "## 分析执行计划\n\nExecution plan with 数据与业务对齐备忘."
    mock_dm.invoke.return_value = mock_dm_response

    state: AgentState = {
        "file_path": sample_csv_path,
        "user_requirement": "Why did Q2 sales drop by 15%?",
    }

    with (
        patch("src.agent.nodes.data_track.get_llm", return_value=mock_dt),
        patch("src.agent.nodes.business_track.get_llm", return_value=mock_bt),
        patch("src.agent.nodes.decision_match.get_llm", return_value=mock_dm),
    ):
        state = data_track_node(state)
        state = business_track_node(state)
        state = decision_match_node(state)

    # All three nodes should have been called
    mock_dt.invoke.assert_called_once()
    mock_bt.invoke.assert_called_once()
    mock_dm.invoke.assert_called_once()

    # Verify each node populated its state field
    assert "data_report" in state
    assert "business_plan" in state
    assert "execution_plan" in state
    assert "数据技术盘报告" in state["data_report"]
    assert "业务分析蓝图" in state["business_plan"]
    assert "分析执行计划" in state["execution_plan"]
    assert "数据与业务对齐备忘" in state["execution_plan"]

    # Verify no error propagated through the three working nodes
    assert "error" not in state


@pytest.mark.integration
def test_graph_m3_execution_integration(
    sample_csv_path: str, set_llm_env: None, temp_output_dir: str
) -> None:
    """Full M1+M2+M3 pipeline: all 4 real nodes with mocked LLMs and sandbox.

    Verifies state flows correctly: data_track → business_track → decision_match → execution.
    """
    _ = set_llm_env

    from src.agent.nodes.business_track import business_track_node
    from src.agent.nodes.data_track import data_track_node
    from src.agent.nodes.decision_match import decision_match_node
    from src.agent.nodes.execution import execution_node
    from src.sandbox.executor import SandboxResult

    # Mocks for each node
    mock_dt = MagicMock()
    mock_dt.invoke.return_value = MagicMock(content="## 数据技术盘报告\n\nAudit.")

    mock_bt = MagicMock()
    mock_bt.invoke.return_value = MagicMock(content="## 业务分析蓝图\n\nBusiness plan.")

    mock_dm = MagicMock()
    mock_dm.invoke.return_value = MagicMock(content="## 分析执行计划\n\nAlign.")

    mock_ex = MagicMock()
    mock_ex.invoke.return_value = MagicMock(content="print('{}')\n")

    sandbox_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 10, "cols": 3},'
        ' "cleaning_actions": ["dropped nulls"],'
        ' "charts": ["out/chart1.png"],'
        ' "statistics": {},'
        ' "insights": ["Sales rose in Q3"]}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    state: AgentState = {
        "file_path": sample_csv_path,
        "user_requirement": "Why did Q2 sales drop?",
    }

    with (
        patch("src.agent.nodes.data_track.get_llm", return_value=mock_dt),
        patch("src.agent.nodes.business_track.get_llm", return_value=mock_bt),
        patch("src.agent.nodes.decision_match.get_llm", return_value=mock_dm),
        patch("src.agent.nodes.execution.get_llm", return_value=mock_ex),
        patch("src.agent.nodes.execution.run_script", return_value=sandbox_result),
    ):
        state = data_track_node(state)
        state = business_track_node(state)
        state = decision_match_node(state)
        state = execution_node(state)

    assert "data_report" in state
    assert "business_plan" in state
    assert "execution_plan" in state
    assert "execution_result" in state
    assert "error" not in state

    result = state["execution_result"]
    assert "parsed_output" in result
    assert result["parsed_output"]["insights"] == ["Sales rose in Q3"]
    assert result["retry_count"] == 0

    # All 4 LLM mocks were called
    mock_dt.invoke.assert_called_once()
    mock_bt.invoke.assert_called_once()
    mock_dm.invoke.assert_called_once()
    mock_ex.invoke.assert_called_once()


@pytest.mark.unit
def test_graph_conditional_edges() -> None:
    """Verify the ReAct retry routing logic."""
    from src.agent.graph import _should_retry_execution

    # No error — go to report_gen
    state_no_error: AgentState = {
        "file_path": "",
        "user_requirement": "",
    }
    assert _should_retry_execution(state_no_error) == "report_gen"

    # Error + retry_count < 3 — retry execution
    state_with_error: AgentState = {
        "file_path": "",
        "user_requirement": "",
        "error": "something failed",
        "execution_result": {"retry_count": 1},
    }
    assert _should_retry_execution(state_with_error) == "execution"

    # Error + retry_count >= 3 — give up, go to report_gen
    state_max_retries: AgentState = {
        "file_path": "",
        "user_requirement": "",
        "error": "failed again",
        "execution_result": {"retry_count": 3},
    }
    assert _should_retry_execution(state_max_retries) == "report_gen"


@pytest.mark.integration
def test_graph_m4_full_pipeline(
    sample_csv_path: str, set_llm_env: None, sample_execution_result: dict,
) -> None:
    """Full 5-node pipeline ending with report_gen."""
    _ = set_llm_env

    from src.agent.nodes.business_track import business_track_node
    from src.agent.nodes.data_track import data_track_node
    from src.agent.nodes.decision_match import decision_match_node
    from src.agent.nodes.execution import execution_node
    from src.agent.nodes.report_gen import report_gen_node
    from src.sandbox.executor import SandboxResult

    mock_dt = MagicMock()
    mock_dt.invoke.return_value = MagicMock(content="## 数据技术盘报告\n\nAudit.")

    mock_bt = MagicMock()
    mock_bt.invoke.return_value = MagicMock(content="## 业务分析蓝图\n\nPlan.")

    mock_dm = MagicMock()
    mock_dm.invoke.return_value = MagicMock(content="## 分析执行计划\n\nAlign.")

    mock_ex = MagicMock()
    mock_ex.invoke.return_value = MagicMock(content="print('{}')\n")

    mock_rg = MagicMock()
    mock_rg.invoke.return_value = MagicMock(
        content="# DataInsight 数据分析报告\n\nFull report with 数据与业务对齐备忘."
    )

    sandbox_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 10, "cols": 3}}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    state: AgentState = {
        "file_path": sample_csv_path,
        "user_requirement": "Why did Q2 sales drop?",
    }

    with (
        patch("src.agent.nodes.data_track.get_llm", return_value=mock_dt),
        patch("src.agent.nodes.business_track.get_llm", return_value=mock_bt),
        patch("src.agent.nodes.decision_match.get_llm", return_value=mock_dm),
        patch("src.agent.nodes.execution.get_llm", return_value=mock_ex),
        patch("src.agent.nodes.execution.run_script", return_value=sandbox_result),
        patch("src.agent.nodes.report_gen.get_llm", return_value=mock_rg),
    ):
        state = data_track_node(state)
        state = business_track_node(state)
        state = decision_match_node(state)
        state = execution_node(state)
        state = report_gen_node(state)

    assert "final_report" in state
    assert "error" not in state
    assert "DataInsight" in state["final_report"]
    assert "数据与业务对齐备忘" in state["final_report"]

    mock_rg.invoke.assert_called_once()


@pytest.mark.integration
def test_graph_feedback_iteration(
    set_llm_env: None, sample_execution_result: dict,
) -> None:
    """Feedback loop: user feedback → decision_match revises → report_gen regenerates."""
    _ = set_llm_env

    from src.agent.nodes.decision_match import decision_match_node
    from src.agent.nodes.execution import execution_node
    from src.agent.nodes.report_gen import report_gen_node
    from src.sandbox.executor import SandboxResult

    # Initial state with feedback (as if CLI set it after first run)
    state: AgentState = {
        "file_path": "/tmp/test.csv",
        "user_requirement": "Analyze sales",
        "data_report": "## 数据技术盘报告\nAudit.",
        "business_plan": "## 业务分析蓝图\nPlan.",
        "execution_plan": "## 分析执行计划\nOld plan.",
        "execution_result": sample_execution_result,
        "feedback": "The chart on regional sales is wrong, use monthly data instead.",
    }

    mock_dm = MagicMock()
    mock_dm.invoke.return_value = MagicMock(
        content="## 分析执行计划 [修订版]\n\nRevised plan with monthly grouping."
    )

    mock_ex = MagicMock()
    mock_ex.invoke.return_value = MagicMock(content="print('{}')\n")

    mock_rg = MagicMock()
    mock_rg.invoke.return_value = MagicMock(content="# DataInsight 数据分析报告\n\nRevised report.")

    sandbox_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 10, "cols": 3}}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    with (
        patch("src.agent.nodes.decision_match.get_llm", return_value=mock_dm),
        patch("src.agent.nodes.execution.get_llm", return_value=mock_ex),
        patch("src.agent.nodes.execution.run_script", return_value=sandbox_result),
        patch("src.agent.nodes.report_gen.get_llm", return_value=mock_rg),
    ):
        # Feedback iteration: decision_match → execution → report_gen
        state = decision_match_node(state)
        state = execution_node(state)
        state = report_gen_node(state)

    # Feedback should be consumed
    assert "feedback" not in state
    assert "修订版" in state["execution_plan"]
    assert "final_report" in state
    assert "error" not in state

    mock_dm.invoke.assert_called_once()
    mock_rg.invoke.assert_called_once()


@pytest.mark.unit
def test_graph_should_iterate() -> None:
    """Verify the feedback iteration routing logic."""
    from src.agent.graph import _should_iterate

    # No feedback → end
    state_no_feedback: AgentState = {
        "file_path": "",
        "user_requirement": "",
    }
    assert _should_iterate(state_no_feedback) == "__end__"

    # Has feedback → go back to decision_match
    state_with_feedback: AgentState = {
        "file_path": "",
        "user_requirement": "",
        "feedback": "Change the chart type to bar",
    }
    assert _should_iterate(state_with_feedback) == "decision_match"
