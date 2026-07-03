from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.planner import _build_planner_prompt, _extract_json, planner_node
from src.agent.state import AgentState, Plan

_PLAN_JSON = (
    '{"cleaning": {"purpose": "处理缺失值和异常值", "model": null, '
    '"cautious": "0值可能是实际销售数据而非缺失", "depends_on": []}, '
    '"units": [{"unit_id": 1, "purpose": "按区域分析销售趋势", '
    '"model": "线性回归", "cautious": "region列有2%缺失值", '
    '"depends_on": []}], '
    '"alignment_notes": "基于当前数据，能够部分回答用户问题。"}'
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
def test_build_planner_prompt_structure(
    sample_data_profile: object, sample_analysis_intent: object
) -> None:
    prompt = _build_planner_prompt(
        sample_data_profile.model_dump_json(indent=2),
        "清洗建议内容。",
        sample_analysis_intent.model_dump_json(indent=2),
    )

    assert "cleaning" in prompt
    assert "units" in prompt
    assert "alignment_notes" in prompt
    assert "unit_id" in prompt
    assert "MANDATORY" in prompt
    assert "清洗建议内容" in prompt


@pytest.mark.unit
def test_build_planner_prompt_mandatory_alignment(
    sample_data_profile: object, sample_analysis_intent: object
) -> None:
    prompt = _build_planner_prompt(
        sample_data_profile.model_dump_json(indent=2),
        "清洗建议。",
        sample_analysis_intent.model_dump_json(indent=2),
    )

    assert "MANDATORY" in prompt or "mandatory" in prompt.lower()


@pytest.mark.unit
def test_planner_node_success(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = _PLAN_JSON
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        cleaning_insights="## 数据清洗建议\n清理缺失值。",
        analysis_intent=sample_analysis_intent,
    )

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        new_state = planner_node(state)

    assert "plan" in new_state
    assert "error" not in new_state

    plan = new_state["plan"]
    assert isinstance(plan, Plan)
    assert plan.cleaning.unit_id == 0
    assert len(plan.units) == 1
    assert plan.units[0].purpose == "按区域分析销售趋势"
    assert plan.units[0].model == "线性回归"

    mock_llm.invoke.assert_called_once()


@pytest.mark.unit
def test_planner_node_consumes_feedback(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
) -> None:
    _ = set_llm_env

    revised_json = (
        '{"cleaning": {"purpose": "处理缺失值", "model": null, '
        '"cautious": "注意0值", "depends_on": []}, '
        '"units": [{"unit_id": 1, "purpose": "月度趋势分析", '
        '"model": "pandas.resample", "cautious": "日期格式需统一", '
        '"depends_on": []}], '
        '"alignment_notes": "修订版：基于用户反馈改用月度分组。"}'
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

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        new_state = planner_node(state)

    assert "plan" in new_state
    assert isinstance(new_state["plan"], Plan)
    assert new_state.get("feedback") is None
    assert "修订版" in new_state["plan"].alignment_notes


@pytest.mark.unit
def test_planner_node_preserves_state(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = _PLAN_JSON
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        cleaning_insights="清洗建议。",
        analysis_intent=sample_analysis_intent,
    )

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        new_state = planner_node(state)

    assert new_state["plan"] is not None
    assert isinstance(new_state["plan"], Plan)


@pytest.mark.unit
def test_planner_node_missing_data_profile(sample_analysis_intent: object) -> None:
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        analysis_intent=sample_analysis_intent,
    )

    new_state = planner_node(state)

    assert "error" in new_state
    assert "data_profile" in new_state["error"]
    assert "plan" not in new_state


@pytest.mark.unit
def test_planner_node_missing_analysis_intent(sample_data_profile: object) -> None:
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        cleaning_insights="清洗建议。",
    )

    new_state = planner_node(state)

    assert "error" in new_state
    assert "analysis_intent" in new_state["error"]
    assert "plan" not in new_state


@pytest.mark.unit
def test_planner_node_invalid_json(
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

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        new_state = planner_node(state)

    assert "error" in new_state
    assert "parse" in new_state["error"].lower() or "json" in new_state["error"].lower()


@pytest.mark.unit
def test_planner_node_multiple_units(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
) -> None:
    _ = set_llm_env

    multi_json = (
        '{"cleaning": {"purpose": "清洗数据", "model": null, '
        '"cautious": "注意空值", "depends_on": []}, '
        '"units": ['
        '{"unit_id": 1, "purpose": "相关性分析", "model": "皮尔逊相关", '
        '"cautious": "样本量可能不足", "depends_on": []},'
        '{"unit_id": 2, "purpose": "聚类分析", "model": "KMeans", '
        '"cautious": "需先标准化", "depends_on": []},'
        '{"unit_id": 3, "purpose": "趋势预测", "model": "线性回归", '
        '"cautious": "时间序列需验证平稳性", "depends_on": []}'
        '], '
        '"alignment_notes": "三个分析维度覆盖了用户问题的核心方面。"}'
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = multi_json
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="全面分析销售数据",
        data_profile=sample_data_profile,
        cleaning_insights="清洗建议。",
        analysis_intent=sample_analysis_intent,
    )

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        new_state = planner_node(state)

    plan = new_state["plan"]
    assert isinstance(plan, Plan)
    assert len(plan.units) == 3
    assert plan.units[0].unit_id == 1
    assert plan.units[1].unit_id == 2
    assert plan.units[2].unit_id == 3
    assert plan.units[1].model == "KMeans"


# --- M3: Planner consumes enriched AnalysisIntent ---


@pytest.mark.unit
def test_planner_prompt_includes_suggestions(
    sample_data_profile: object, sample_analysis_intent: object
) -> None:
    """Planner prompt should include suggestion hooks from AnalysisIntent."""
    prompt = _build_planner_prompt(
        sample_data_profile.model_dump_json(indent=2),
        "清洗建议。",
        sample_analysis_intent.model_dump_json(indent=2),
    )

    assert "STRONG HINTS" in prompt
    assert "suggestions" in prompt
    assert "complexity" in prompt
    assert "expanded_question" in prompt
    assert "caution_notes" in prompt


@pytest.mark.unit
def test_planner_node_with_rich_intent(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
) -> None:
    """Planner node should succeed with M3-enriched analysis_intent."""
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = _PLAN_JSON
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Why did Q2 sales drop by 15%?",
        data_profile=sample_data_profile,
        cleaning_insights="清洗建议。",
        analysis_intent=sample_analysis_intent,
    )

    # Verify the intent has M3 fields before calling planner
    assert sample_analysis_intent.complexity == "moderate"
    assert len(sample_analysis_intent.suggestions) == 3

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        new_state = planner_node(state)

    assert "plan" in new_state
    assert "error" not in new_state
    assert isinstance(new_state["plan"], Plan)
