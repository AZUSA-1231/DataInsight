from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.business_track import _build_intent_prompt, business_track_node
from src.agent.state import AgentState, AnalysisIntent


@pytest.mark.unit
def test_build_intent_prompt_structure() -> None:
    prompt = _build_intent_prompt("Analyze sales trend")

    assert "core_question" in prompt
    assert "target_variable" in prompt
    assert "analysis_type" in prompt
    assert "dimensions" in prompt
    assert "comparison_baseline" in prompt
    assert "Analyze sales trend" in prompt
    assert "JSON" in prompt


@pytest.mark.unit
def test_build_intent_prompt_excludes_data_references() -> None:
    prompt = _build_intent_prompt("Why did sales drop?")

    assert "do not invent column names" in prompt.lower()
    assert "no access to the data" in prompt.lower()
    assert "narrow" in prompt.lower()


@pytest.mark.unit
def test_business_track_node_success(set_llm_env: None) -> None:
    _ = set_llm_env

    intent_json = json.dumps(
        {
            "core_question": "Analyze Q2 revenue by product line",
            "target_variable": "revenue",
            "analysis_type": "diagnostic",
            "dimensions": ["time period", "product category"],
            "comparison_baseline": "Q1 same year",
        }
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = intent_json
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze Q2 revenue by product line",
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        new_state = business_track_node(state)

    assert "analysis_intent" in new_state
    assert "error" not in new_state
    assert isinstance(new_state["analysis_intent"], AnalysisIntent)
    assert new_state["analysis_intent"].analysis_type == "diagnostic"
    mock_llm.invoke.assert_called_once()


@pytest.mark.unit
def test_business_track_node_preserves_state(set_llm_env: None) -> None:
    _ = set_llm_env

    intent_json = json.dumps(
        {
            "core_question": "Why did retention drop?",
            "target_variable": None,
            "analysis_type": "diagnostic",
            "dimensions": [],
            "comparison_baseline": None,
        }
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = intent_json
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Why did retention drop?",
        cleaning_insights="Existing cleaning insights",
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        new_state = business_track_node(state)

    assert isinstance(new_state["analysis_intent"], AnalysisIntent)
    assert new_state["analysis_intent"].core_question == "Why did retention drop?"


@pytest.mark.unit
def test_business_track_node_llm_error(set_llm_env: None) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API timeout")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Anything",
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        new_state = business_track_node(state)

    assert "error" in new_state
    assert "API timeout" in new_state["error"]
    assert "analysis_intent" not in new_state


@pytest.mark.unit
def test_business_track_node_invalid_json(set_llm_env: None) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Not a JSON response — just some markdown text."
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        new_state = business_track_node(state)

    assert "error" in new_state
    assert "JSON" in new_state["error"]
    assert "analysis_intent" not in new_state


@pytest.mark.unit
def test_business_track_node_json_in_fence(set_llm_env: None) -> None:
    """LLM may return JSON inside markdown code fences — should strip and parse."""
    _ = set_llm_env

    intent_json = json.dumps(
        {
            "core_question": "Analyze revenue",
            "target_variable": "revenue",
            "analysis_type": "trend",
            "dimensions": ["time"],
            "comparison_baseline": None,
        }
    )
    fence_wrapped = f"```\n{intent_json}\n```"

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = fence_wrapped
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze revenue",
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        new_state = business_track_node(state)

    assert "error" not in new_state
    assert isinstance(new_state["analysis_intent"], AnalysisIntent)
    assert new_state["analysis_intent"].analysis_type == "trend"
