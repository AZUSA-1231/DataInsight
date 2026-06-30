from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.decision_match import (
    _build_decision_prompt,
    _extract_json,
    decision_match_node,
)
from src.agent.state import AgentState, ExecutionPlan

_EXECUTION_PLAN_JSON = json.dumps(
    {
        "feasibility_map": [
            {
                "intent_dimension": "region",
                "matched_columns": ["region"],
                "feasibility": "可直接实现",
                "confidence": "High",
                "reasoning": "Direct column match",
            }
        ],
        "model_selections": [
            {
                "analysis_step": "Sales trend",
                "method": "pandas.DataFrame.corr",
                "reasoning": "Continuous target with categorical dimension",
                "feasibility": "可直接实现",
            }
        ],
        "preprocessing_steps": [
            {
                "step": 1,
                "action": "drop_null_rows",
                "target_columns": ["region"],
                "urgency": "高优先",
                "reason": "2% nulls",
            }
        ],
        "analysis_steps": [
            {
                "step": 1,
                "action": "compute_correlation",
                "target_columns": ["sales", "region"],
                "method": "pandas.DataFrame.corr",
                "expected_output": "correlation matrix",
            }
        ],
        "alignment_notes": "基于当前数据，本报告能够部分回答用户问题。",
    },
    ensure_ascii=False,
)


@pytest.mark.unit
def test_extract_json_plain() -> None:
    text = '{"key": "value"}'
    assert _extract_json(text) == '{"key": "value"}'


@pytest.mark.unit
def test_extract_json_with_fence() -> None:
    text = '```json\n{"key": "value"}\n```'
    assert _extract_json(text) == '{"key": "value"}'


@pytest.mark.unit
def test_extract_json_with_text_surrounding() -> None:
    text = 'Some preamble\n{"key": "value"}\nSome trailing text'
    assert _extract_json(text) == '{"key": "value"}'


@pytest.mark.unit
def test_build_decision_prompt_structure(
    sample_data_profile: object, sample_analysis_intent: object
) -> None:
    prompt = _build_decision_prompt(
        sample_data_profile.model_dump_json(indent=2),
        "清洗建议内容。",
        sample_analysis_intent.model_dump_json(indent=2),
    )

    assert "feasibility_map" in prompt
    assert "model_selections" in prompt
    assert "preprocessing_steps" in prompt
    assert "analysis_steps" in prompt
    assert "alignment_notes" in prompt
    assert "清洗建议内容" in prompt
    assert "MANDATORY" in prompt


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
    assert "无法完全回答" in prompt or "fully answer" in prompt.lower()


@pytest.mark.unit
def test_decision_match_node_success(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = _EXECUTION_PLAN_JSON
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
    plan = new_state["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    assert len(plan.feasibility_map) == 1
    assert plan.feasibility_map[0]["feasibility"] == "可直接实现"
    assert len(plan.model_selections) == 1
    assert len(plan.preprocessing_steps) == 1
    assert len(plan.analysis_steps) == 1
    assert "无法完全回答" in plan.alignment_notes or "部分回答" in plan.alignment_notes
    mock_llm.invoke.assert_called_once()


@pytest.mark.unit
def test_decision_match_node_consumes_feedback(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
) -> None:
    _ = set_llm_env

    revised_json = json.dumps(
        {
            "feasibility_map": [
                {
                    "intent_dimension": "monthly",
                    "matched_columns": ["date"],
                    "feasibility": "可直接实现",
                    "confidence": "High",
                    "reasoning": "Revised per feedback",
                }
            ],
            "model_selections": [
                {
                    "analysis_step": "Monthly trend",
                    "method": "pandas.DataFrame.resample",
                    "reasoning": "Monthly grouping as requested",
                    "feasibility": "可直接实现",
                }
            ],
            "preprocessing_steps": [],
            "analysis_steps": [],
            "alignment_notes": "修订版：基于用户反馈改用月度分组。",
        },
        ensure_ascii=False,
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = revised_json
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        cleaning_insights="清洗建议。",
        analysis_intent=sample_analysis_intent,
        feedback="Use monthly data instead of daily.",
    )

    with patch("src.agent.nodes.decision_match.get_llm", return_value=mock_llm):
        new_state = decision_match_node(state)

    assert "execution_plan" in new_state
    assert isinstance(new_state["execution_plan"], ExecutionPlan)
    assert new_state.get("feedback") is None


@pytest.mark.unit
def test_decision_match_node_preserves_state(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = _EXECUTION_PLAN_JSON
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
    assert isinstance(new_state["execution_plan"], ExecutionPlan)


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


@pytest.mark.unit
def test_decision_match_node_invalid_json(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "not valid json at all"
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

    assert "error" in new_state
    assert "parse" in new_state["error"].lower() or "json" in new_state["error"].lower()
