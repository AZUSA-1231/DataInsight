from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.data_track import _build_audit_prompt, data_track_node
from src.agent.state import AgentState


@pytest.mark.unit
def test_build_audit_prompt_structure() -> None:
    inspection = json.dumps({"shape": {"rows": 10, "cols": 3}})
    prompt = _build_audit_prompt(inspection)

    assert "数据技术盘报告" in prompt
    assert "字段总览" in prompt
    assert "缺失值诊断" in prompt
    assert "异常值隐患" in prompt
    assert "需强清洗字段清单" in prompt
    assert "整体数据质量评分" in prompt
    assert inspection in prompt


@pytest.mark.unit
def test_build_audit_prompt_excludes_business_analysis() -> None:
    prompt = _build_audit_prompt("{}")

    # The prompt explicitly forbids business analysis — verify that instruction exists
    assert "do not suggest business metrics" in prompt.lower()
    assert "do not recommend analysis methods" in prompt.lower()
    assert "stay in your lane" in prompt.lower()


@pytest.mark.unit
def test_data_track_node_success(sample_csv_path: str, set_llm_env: None) -> None:
    _ = set_llm_env  # fixture side effect

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "# 数据技术盘报告\n\nTest audit report."
    mock_llm.invoke.return_value = mock_response

    state: AgentState = {
        "file_path": sample_csv_path,
        "user_requirement": "Analyze sales trend",
    }

    with patch("src.agent.nodes.data_track.get_llm", return_value=mock_llm):
        new_state = data_track_node(state)

    assert "data_report" in new_state
    assert "error" not in new_state
    assert "数据技术盘报告" in new_state["data_report"]
    mock_llm.invoke.assert_called_once()


@pytest.mark.unit
def test_data_track_node_inspection_failure() -> None:
    state: AgentState = {
        "file_path": "/nonexistent/file.csv",
        "user_requirement": "anything",
    }

    new_state = data_track_node(state)

    assert "error" in new_state
    assert new_state["error"] is not None
    assert "data_report" not in new_state


@pytest.mark.unit
def test_data_track_node_preserves_state(sample_csv_path: str, set_llm_env: None) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Audit report content."
    mock_llm.invoke.return_value = mock_response

    state: AgentState = {
        "file_path": sample_csv_path,
        "user_requirement": "Why did sales drop?",
    }

    with patch("src.agent.nodes.data_track.get_llm", return_value=mock_llm):
        new_state = data_track_node(state)

    assert new_state["file_path"] == state["file_path"]
    assert new_state["user_requirement"] == state["user_requirement"]
