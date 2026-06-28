from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.business_track import _build_business_prompt, business_track_node
from src.agent.state import AgentState


@pytest.mark.unit
def test_build_business_prompt_structure() -> None:
    prompt = _build_business_prompt("Analyze sales trend")

    assert "业务分析蓝图" in prompt
    assert "业务问题重述" in prompt
    assert "理想指标体系" in prompt
    assert "维度与切分" in prompt
    assert "理想图表方案" in prompt
    assert "数据需求清单" in prompt
    assert "Analyze sales trend" in prompt


@pytest.mark.unit
def test_build_business_prompt_excludes_data_references() -> None:
    prompt = _build_business_prompt("Why did sales drop?")

    assert "do not have access to the data" in prompt.lower()
    assert "do not reference the data file" in prompt.lower()
    assert "stay in your lane" in prompt.lower()


@pytest.mark.unit
def test_business_track_node_success(set_llm_env: None) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "## 业务分析蓝图\n\nTest business plan."
    mock_llm.invoke.return_value = mock_response

    state: AgentState = {
        "file_path": "/tmp/test.csv",
        "user_requirement": "Analyze Q2 revenue by product line",
    }

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        new_state = business_track_node(state)

    assert "business_plan" in new_state
    assert "error" not in new_state
    assert "业务分析蓝图" in new_state["business_plan"]
    mock_llm.invoke.assert_called_once()


@pytest.mark.unit
def test_business_track_node_preserves_state(set_llm_env: None) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Business plan content."
    mock_llm.invoke.return_value = mock_response

    state: AgentState = {
        "file_path": "/tmp/test.csv",
        "user_requirement": "Why did retention drop?",
        "data_report": "Existing audit report",
    }

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        new_state = business_track_node(state)

    assert new_state["file_path"] == state["file_path"]
    assert new_state["user_requirement"] == state["user_requirement"]
    assert new_state["data_report"] == state["data_report"]


@pytest.mark.unit
def test_business_track_node_llm_error(set_llm_env: None) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API timeout")

    state: AgentState = {
        "file_path": "/tmp/test.csv",
        "user_requirement": "Anything",
    }

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        new_state = business_track_node(state)

    assert "error" in new_state
    assert "API timeout" in new_state["error"]
    assert "business_plan" not in new_state
