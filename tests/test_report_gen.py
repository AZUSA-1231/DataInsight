from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.report_gen import (
    _build_full_report_prompt,
    _build_partial_report_prompt,
    _serialize_analysis_result,
    report_gen_node,
)
from src.agent.state import AgentState


@pytest.mark.unit
def test_serialize_analysis_result_with_unit_results() -> None:
    result = _serialize_analysis_result(
        {
            "status": "complete",
            "unit_results": [
                {
                    "unit_id": 1,
                    "status": "success",
                    "charts": ["out/chart1.png"],
                    "insights": ["Sales rose in Q3"],
                    "statistics": {"correlations": {"sales_revenue": 0.85}},
                    "error": None,
                    "retry_count": 0,
                }
            ],
        }
    )
    assert "unit_results" in result
    assert "Sales rose in Q3" in result
    assert "complete" in result


@pytest.mark.unit
def test_serialize_analysis_result_with_parsed_output() -> None:
    result = _serialize_analysis_result(
        {
            "retry_count": 0,
            "parsed_output": {
                "charts": ["out/chart1.png"],
                "statistics": {"correlations": {"sales_revenue": 0.85}},
                "insights": ["Sales rose in Q3"],
            },
        }
    )
    assert "charts" in result
    assert "Sales rose in Q3" in result


@pytest.mark.unit
def test_serialize_analysis_result_without_parsed_output() -> None:
    result = _serialize_analysis_result(
        {
            "retry_count": 3,
            "attempts": [{"code": "x", "error": "fail"}],
        }
    )
    assert "retry_count" in result
    assert "3" in result


@pytest.mark.unit
def test_build_full_report_prompt_structure(
    sample_data_profile: object, sample_analysis_intent: object
) -> None:
    prompt = _build_full_report_prompt(
        "清洗建议内容。",
        sample_data_profile.model_dump_json(indent=2),
        sample_analysis_intent.model_dump_json(indent=2),
        "数据与业务对齐备忘：测试。",
        '{"charts": ["out/chart1.png"], "statistics": {}, "insights": ["test"]}',
        "Why did sales drop?",
    )

    assert "DataInsight 数据分析报告" in prompt
    assert "执行摘要" in prompt
    assert "数据画像与清洗" in prompt
    assert "业务分析意图" in prompt
    assert "分析执行与结果" in prompt
    assert "数据与业务对齐备忘" in prompt
    assert "图表清单" in prompt
    assert "局限性与后续建议" in prompt
    assert "Why did sales drop?" in prompt
    assert "清洗建议内容" in prompt
    assert "数据与业务对齐备忘：测试" in prompt


@pytest.mark.unit
def test_build_full_report_prompt_mandatory_alignment() -> None:
    prompt = _build_full_report_prompt(
        "CI",
        "{}",
        "{}",
        "对齐备忘。",
        "{}",
        "question",
    )
    assert "MANDATORY" in prompt


@pytest.mark.unit
def test_build_partial_report_prompt_structure(
    sample_data_profile: object, sample_analysis_intent: object
) -> None:
    prompt = _build_partial_report_prompt(
        "清洗建议。",
        sample_data_profile.model_dump_json(indent=2),
        sample_analysis_intent.model_dump_json(indent=2),
        "对齐备忘。",
        "NameError: 'df' not defined",
        "Why?",
    )

    assert "部分报告" in prompt
    assert "执行错误说明" in prompt
    assert "NameError" in prompt
    assert "数据与业务对齐备忘" in prompt
    assert "清洗建议" in prompt


@pytest.mark.unit
def test_report_gen_node_full_report(
    set_llm_env: None,
    sample_analysis_result: dict,
    sample_data_profile: object,
    sample_analysis_intent: object,
    make_plan: object,
) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "# DataInsight 数据分析报告\n\nFull report content."
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        cleaning_insights="## 数据清洗建议\n清洗。",
        analysis_intent=sample_analysis_intent,
        plan=make_plan(),
        analysis_result=sample_analysis_result,
    )

    with patch("src.agent.nodes.report_gen.get_llm", return_value=mock_llm):
        new_state = report_gen_node(state)

    assert "final_report" in new_state
    assert "error" not in new_state
    assert "DataInsight" in new_state["final_report"]
    mock_llm.invoke.assert_called_once()


@pytest.mark.unit
def test_report_gen_node_partial_report(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
    make_plan: object,
) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "# DataInsight 数据分析报告 [部分报告]\n\nPartial."
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        cleaning_insights="清洗建议。",
        analysis_intent=sample_analysis_intent,
        plan=make_plan(),
        error="Analysis error (attempt 3/3): NameError",
    )

    with patch("src.agent.nodes.report_gen.get_llm", return_value=mock_llm):
        new_state = report_gen_node(state)

    assert "final_report" in new_state
    assert "部分报告" in new_state["final_report"]


@pytest.mark.unit
def test_report_gen_node_preserves_state(
    set_llm_env: None,
    sample_analysis_result: dict,
    sample_data_profile: object,
    sample_analysis_intent: object,
    make_plan: object,
) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Report."
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Why?",
        data_profile=sample_data_profile,
        cleaning_insights="CI",
        analysis_intent=sample_analysis_intent,
        plan=make_plan(),
        analysis_result=sample_analysis_result,
    )

    with patch("src.agent.nodes.report_gen.get_llm", return_value=mock_llm):
        new_state = report_gen_node(state)

    assert new_state["final_report"] == "Report."


@pytest.mark.unit
def test_report_gen_node_llm_error(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
    make_plan: object,
) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API error")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Why?",
        data_profile=sample_data_profile,
        cleaning_insights="CI",
        analysis_intent=sample_analysis_intent,
        plan=make_plan(),
    )

    with patch("src.agent.nodes.report_gen.get_llm", return_value=mock_llm):
        new_state = report_gen_node(state)

    assert "error" in new_state
    assert "API error" in new_state["error"]


@pytest.mark.unit
def test_report_gen_node_uses_plan_alignment(
    set_llm_env: None,
    sample_analysis_result: dict,
    sample_data_profile: object,
    sample_analysis_intent: object,
    make_plan: object,
) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="# Report\n\n对齐备忘内容。")

    plan = make_plan(alignment_notes="自定义对齐备忘：测试。")
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Why?",
        data_profile=sample_data_profile,
        cleaning_insights="CI",
        analysis_intent=sample_analysis_intent,
        plan=plan,
        analysis_result=sample_analysis_result,
    )

    with patch("src.agent.nodes.report_gen.get_llm", return_value=mock_llm):
        new_state = report_gen_node(state)

    assert new_state["final_report"] is not None
    call_args = mock_llm.invoke.call_args[0][0]
    assert "自定义对齐备忘：测试" in call_args


# --- M4: Per-Unit Chapter Tests ---


@pytest.mark.unit
def test_full_report_prompt_has_per_unit_instructions() -> None:
    """Full report prompt must instruct LLM to produce one subsection per unit."""
    prompt = _build_full_report_prompt(
        "CI", "{}", "{}", "对齐。",
        '{"status": "complete", "unit_results": []}',
        "question",
    )
    assert "### 3." in prompt
    assert "ONE subsection" in prompt
    assert "per analysis unit" in prompt


@pytest.mark.unit
def test_full_report_prompt_multi_unit() -> None:
    """Prompt with multiple unit_results should reference per-unit structure."""
    result_json = (
        '{"status": "complete", "unit_results": ['
        '{"unit_id": 1, "status": "success", "charts": [], "insights": ["A"], "statistics": {}}, '
        '{"unit_id": 2, "status": "success", "charts": [], "insights": ["B"], "statistics": {}}, '
        '{"unit_id": 3, "status": "success", "charts": [], "insights": ["C"], "statistics": {}}'
        "]}"
    )
    prompt = _build_full_report_prompt(
        "CI", "{}", "{}", "对齐。", result_json, "question",
    )
    assert "分析执行与结果" in prompt
    assert "subsection" in prompt
    assert "purpose" in prompt


@pytest.mark.unit
def test_partial_report_prompt_includes_plan_units() -> None:
    """Partial report prompt should include planned units JSON for the LLM to list."""
    plan_units_json = '[{"unit_id": 1, "purpose": "趋势分析", "model": "线性回归"}]'
    prompt = _build_partial_report_prompt(
        "CI", "{}", "{}", "对齐。", "error", "q", plan_units_json,
    )
    assert "趋势分析" in prompt
    assert "线性回归" in prompt
    assert "分析执行计划" in prompt


@pytest.mark.unit
def test_report_gen_node_passes_plan_units_to_partial(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
    sample_plan_multi: object,
) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "# 部分报告\n\n分析执行计划。"
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        data_profile=sample_data_profile,
        cleaning_insights="CI",
        analysis_intent=sample_analysis_intent,
        plan=sample_plan_multi,
        error="Analysis failed",
    )

    with patch("src.agent.nodes.report_gen.get_llm", return_value=mock_llm):
        new_state = report_gen_node(state)

    assert "final_report" in new_state
    prompt = mock_llm.invoke.call_args[0][0]
    assert "相关性分析" in prompt
    assert "聚类分析" in prompt
    assert "趋势预测" in prompt
