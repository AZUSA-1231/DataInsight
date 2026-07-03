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
    assert "only the json object" in prompt.lower()


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


# --- M3: Question Intelligence Tests ---


@pytest.mark.unit
def test_short_question_gets_expanded(set_llm_env: None) -> None:
    """Short/vague questions should get expanded_question with plausible dimensions."""
    _ = set_llm_env

    intent_json = json.dumps(
        {
            "core_question": "分析销售数据",
            "target_variable": None,
            "analysis_type": "descriptive",
            "dimensions": ["time period", "region", "product category"],
            "comparison_baseline": None,
            "complexity": "simple",
            "expanded_question": "分析销售数据的时间趋势、地区分布和产品类别差异",
            "suggestions": [
                {
                    "category": "dimension",
                    "content": "按时间维度观察销售趋势",
                    "rationale": "时间趋势是销售分析的基本维度",
                },
                {
                    "category": "dimension",
                    "content": "按地区细分销售表现",
                    "rationale": "地理差异可能揭示区域性机会或问题",
                },
            ],
            "caution_notes": "注意区分销售额与销售量；增长率需考虑基数效应",
        }
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = intent_json
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="分析销售数据",
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        new_state = business_track_node(state)

    assert "error" not in new_state
    intent = new_state["analysis_intent"]
    assert isinstance(intent, AnalysisIntent)
    assert intent.complexity == "simple"
    assert intent.expanded_question is not None
    assert len(intent.expanded_question) > len("分析销售数据")
    assert len(intent.suggestions) >= 2


@pytest.mark.unit
def test_complex_question_gets_structured(set_llm_env: None) -> None:
    """Complex multi-part questions should produce more suggestions and higher complexity."""
    _ = set_llm_env

    intent_json = json.dumps(
        {
            "core_question": "为什么Q2销售额下降了15%？如果按地区看哪个区域最严重？",
            "target_variable": "sales",
            "analysis_type": "diagnostic",
            "dimensions": ["time period", "region", "product category", "customer segment"],
            "comparison_baseline": "Q1",
            "complexity": "complex",
            "expanded_question": None,
            "suggestions": [
                {
                    "category": "dimension",
                    "content": "按时间序列分解以定位下降发生的时间点",
                    "rationale": "15%下降可能在特定周/月集中发生",
                },
                {
                    "category": "dimension",
                    "content": "按地区细分以识别最严重区域",
                    "rationale": "用户明确询问了地区差异",
                },
                {
                    "category": "method",
                    "content": "使用贡献度分析量化各维度对下降的贡献",
                    "rationale": "多维度同时变化，需分解各因素贡献",
                },
                {
                    "category": "comparison",
                    "content": "对比去年同期数据排除季节性影响",
                    "rationale": "Q2可能本身是淡季",
                },
            ],
            "caution_notes": "相关性不等于因果关系；外部因素可能未体现在数据中",
        }
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = intent_json
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="为什么Q2销售额下降了15%？如果按地区看哪个区域最严重？",
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        new_state = business_track_node(state)

    assert "error" not in new_state
    intent = new_state["analysis_intent"]
    assert isinstance(intent, AnalysisIntent)
    assert intent.complexity == "complex"
    assert intent.expanded_question is None  # already detailed
    assert len(intent.suggestions) >= 3
    assert len(intent.dimensions) >= 3


@pytest.mark.unit
def test_suggestions_have_required_fields(set_llm_env: None) -> None:
    """Each Suggestion must have category, content, and rationale populated."""
    _ = set_llm_env

    intent_json = json.dumps(
        {
            "core_question": "Predict next quarter revenue",
            "target_variable": "revenue",
            "analysis_type": "predictive",
            "dimensions": ["time period"],
            "comparison_baseline": None,
            "complexity": "moderate",
            "expanded_question": None,
            "suggestions": [
                {
                    "category": "method",
                    "content": "使用时间序列预测模型",
                    "rationale": "历史趋势是预测的基础",
                },
                {
                    "category": "caution",
                    "content": "注意数据时间跨度是否足够",
                    "rationale": "少于2年的数据不适合做季度预测",
                },
            ],
            "caution_notes": "预测假设历史模式延续；外部冲击不可预见",
        }
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = intent_json
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Predict next quarter revenue",
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        new_state = business_track_node(state)

    assert "error" not in new_state
    suggestions = new_state["analysis_intent"].suggestions
    assert len(suggestions) == 2
    for s in suggestions:
        assert s.category in ("dimension", "method", "comparison", "caution")
        assert len(s.content) > 0
        assert len(s.rationale) > 0


@pytest.mark.unit
def test_backward_compat_missing_m3_fields(set_llm_env: None) -> None:
    """LLM response missing M3 fields should still parse with defaults."""
    _ = set_llm_env

    # Minimal valid JSON with only legacy fields
    intent_json = json.dumps(
        {
            "core_question": "Analyze sales trend",
            "target_variable": "sales",
            "analysis_type": "trend",
            "dimensions": ["time"],
            "comparison_baseline": None,
        }
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = intent_json
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales trend",
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        new_state = business_track_node(state)

    assert "error" not in new_state
    intent = new_state["analysis_intent"]
    assert isinstance(intent, AnalysisIntent)
    assert intent.complexity == "moderate"  # default
    assert intent.expanded_question is None  # default
    assert intent.suggestions == []  # default
    assert intent.caution_notes is None  # default


@pytest.mark.unit
def test_suggestions_parse_malformed_entries(set_llm_env: None) -> None:
    """Malformed suggestion entries should be silently skipped."""
    _ = set_llm_env

    intent_json = json.dumps(
        {
            "core_question": "Analyze churn",
            "target_variable": None,
            "analysis_type": "diagnostic",
            "dimensions": [],
            "comparison_baseline": None,
            "complexity": "simple",
            "suggestions": [
                {"category": "method", "content": "有效建议", "rationale": "合理"},
                {"bad_key": "missing required fields"},
                {},
                {"category": "dimension", "content": "另一个有效建议", "rationale": "合理2"},
            ],
        }
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = intent_json
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze churn",
    )

    with patch("src.agent.nodes.business_track.get_llm", return_value=mock_llm):
        new_state = business_track_node(state)

    assert "error" not in new_state
    suggestions = new_state["analysis_intent"].suggestions
    assert len(suggestions) == 2  # only the valid entries parsed
