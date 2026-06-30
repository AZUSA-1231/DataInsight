from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.decision_match import _build_decision_prompt, decision_match_node
from src.agent.state import AgentState


@pytest.mark.unit
def test_build_decision_prompt_structure(
    sample_data_profile: object, sample_analysis_intent: object
) -> None:
    prompt = _build_decision_prompt(
        sample_data_profile.model_dump_json(indent=2),
        "清洗建议内容。",
        sample_analysis_intent.model_dump_json(indent=2),
    )

    assert "分析执行计划" in prompt
    assert "指标可行性映射" in prompt
    assert "数据缺口与替代方案" in prompt
    assert "清洗优先级" in prompt
    assert "分析执行步骤" in prompt
    assert "数据与业务对齐备忘" in prompt
    assert "清洗建议内容" in prompt


@pytest.mark.unit
def test_build_decision_prompt_mandatory_alignment_notes(
    sample_data_profile: object, sample_analysis_intent: object
) -> None:
    prompt = _build_decision_prompt(
        sample_data_profile.model_dump_json(indent=2),
        "清洗建议。",
        sample_analysis_intent.model_dump_json(indent=2),
    )

    assert "MANDATORY" in prompt or "mandatory" in prompt.lower()
    assert "无法完全回答" in prompt


@pytest.mark.unit
def test_decision_match_node_success(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "## 分析执行计划\n\nExecution plan here."
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        cleaning_insights="## 数据清洗建议\n清理缺失值。",
        analysis_intent=sample_analysis_intent,
    )

    with patch("src.agent.nodes.decision_match.get_llm", return_value=mock_llm):
        new_state = decision_match_node(state)

    assert "execution_plan" in new_state
    assert "error" not in new_state
    assert "分析执行计划" in new_state["execution_plan"]
    mock_llm.invoke.assert_called_once()


@pytest.mark.unit
def test_decision_match_node_consumes_feedback(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "## 分析执行计划 [修订版]\n\nRevised."
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        cleaning_insights="清洗建议。",
        analysis_intent=sample_analysis_intent,
        feedback="Use different chart type.",
    )

    with patch("src.agent.nodes.decision_match.get_llm", return_value=mock_llm):
        new_state = decision_match_node(state)

    assert "execution_plan" in new_state
    assert new_state.get("feedback") is None  # consumed


@pytest.mark.unit
def test_decision_match_node_preserves_state(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Execution plan."
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        cleaning_insights="清洗建议。",
        analysis_intent=sample_analysis_intent,
    )

    with patch("src.agent.nodes.decision_match.get_llm", return_value=mock_llm):
        new_state = decision_match_node(state)

    assert new_state["execution_plan"] is not None


@pytest.mark.unit
def test_decision_match_node_missing_data_profile(sample_analysis_intent: object) -> None:
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        analysis_intent=sample_analysis_intent,
    )

    new_state = decision_match_node(state)

    assert "error" in new_state
    assert "data_profile" in new_state["error"]
    assert "execution_plan" not in new_state


@pytest.mark.unit
def test_decision_match_node_missing_analysis_intent(sample_data_profile: object) -> None:
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        cleaning_insights="清洗建议。",
    )

    new_state = decision_match_node(state)

    assert "error" in new_state
    assert "analysis_intent" in new_state["error"]
    assert "execution_plan" not in new_state
