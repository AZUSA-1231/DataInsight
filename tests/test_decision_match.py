from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.decision_match import _build_decision_prompt, decision_match_node
from src.agent.state import AgentState


@pytest.mark.unit
def test_build_decision_prompt_structure() -> None:
    prompt = _build_decision_prompt("Data audit here.", "Business plan here.")

    assert "分析执行计划" in prompt
    assert "指标可行性映射" in prompt
    assert "数据缺口与替代方案" in prompt
    assert "清洗优先级" in prompt
    assert "分析执行步骤" in prompt
    assert "数据与业务对齐备忘" in prompt
    assert "Data audit here." in prompt
    assert "Business plan here." in prompt


@pytest.mark.unit
def test_build_decision_prompt_mandatory_alignment_notes() -> None:
    prompt = _build_decision_prompt("Data audit.", "Business plan.")

    assert "MANDATORY" in prompt or "mandatory" in prompt.lower()
    assert "无法完全回答" in prompt


@pytest.mark.unit
def test_decision_match_node_success(set_llm_env: None) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "## 分析执行计划\n\nExecution plan here."
    mock_llm.invoke.return_value = mock_response

    state: AgentState = {
        "file_path": "/tmp/test.csv",
        "user_requirement": "Analyze sales",
        "data_report": "## 数据技术盘报告\nAudit report.",
        "business_plan": "## 业务分析蓝图\nBusiness plan.",
    }

    with patch("src.agent.nodes.decision_match.get_llm", return_value=mock_llm):
        new_state = decision_match_node(state)

    assert "execution_plan" in new_state
    assert "error" not in new_state
    assert "分析执行计划" in new_state["execution_plan"]
    mock_llm.invoke.assert_called_once()


@pytest.mark.unit
def test_decision_match_node_preserves_state(set_llm_env: None) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Execution plan."
    mock_llm.invoke.return_value = mock_response

    state: AgentState = {
        "file_path": "/tmp/test.csv",
        "user_requirement": "Analyze sales",
        "data_report": "Audit report.",
        "business_plan": "Business plan.",
    }

    with patch("src.agent.nodes.decision_match.get_llm", return_value=mock_llm):
        new_state = decision_match_node(state)

    assert new_state["file_path"] == state["file_path"]
    assert new_state["user_requirement"] == state["user_requirement"]
    assert new_state["data_report"] == state["data_report"]
    assert new_state["business_plan"] == state["business_plan"]


@pytest.mark.unit
def test_decision_match_node_missing_data_report() -> None:
    state: AgentState = {
        "file_path": "/tmp/test.csv",
        "user_requirement": "Analyze sales",
        "business_plan": "Business plan.",
    }

    new_state = decision_match_node(state)

    assert "error" in new_state
    assert "data_report" in new_state["error"]
    assert "execution_plan" not in new_state


@pytest.mark.unit
def test_decision_match_node_missing_business_plan() -> None:
    state: AgentState = {
        "file_path": "/tmp/test.csv",
        "user_requirement": "Analyze sales",
        "data_report": "Audit report.",
    }

    new_state = decision_match_node(state)

    assert "error" in new_state
    assert "business_plan" in new_state["error"]
    assert "execution_plan" not in new_state
