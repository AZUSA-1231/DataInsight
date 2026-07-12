from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.planner import planner_node
from src.agent.state import AgentState, Plan
from src.agent.utils import _extract_json

_PLAN_JSON = (
    '{"units": [{"unit_id": 1, "purpose": "按区域分析销售趋势", '
    '"model": "线性回归", "cautious": "region列有2%缺失值", '
    '"depends_on": [], "input_columns": ["销量", "地区"], '
    '"output_columns": [], "related_fields": ["销量", "地区"]}], '
    '"alignment_notes": "基于当前数据，能够部分回答用户问题。"}'
)


# ── _extract_json tests (preserved — mature utility) ──────────────


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


# ── Planner Agent: core tests ─────────────────────────────────────


@pytest.mark.unit
def test_planner_agent_success(
    set_llm_env: None,
    sample_data_profile: object,
    sample_planner_instruction: object,
) -> None:
    """Planner Agent produces a Plan from PlannerInstruction + data profile."""
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=_PLAN_JSON)

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        unified_columns=["销量", "地区", "日期"],
        planner_instruction=sample_planner_instruction,
    )

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        result = planner_node(state)

    assert "plan" in result
    assert "error" not in result

    plan = result["plan"]
    assert isinstance(plan, Plan)
    assert len(plan.units) == 1
    assert plan.units[0].purpose == "按区域分析销售趋势"
    assert plan.units[0].model_hint == "线性回归"
    assert plan.units[0].related_fields == ["销量", "地区"]

    mock_llm.invoke.assert_called_once()
    # Verify instruction_nl is injected into the context
    call_arg = mock_llm.invoke.call_args[0][0][1]  # HumanMessage
    assert "诊断Q2销售下降" in call_arg.content


@pytest.mark.unit
def test_planner_agent_reads_conversation_history(
    set_llm_env: None,
    sample_data_profile: object,
    sample_planner_instruction: object,
) -> None:
    """Planner Agent receives full conversation history in its context."""
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=_PLAN_JSON)

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="按地区拆分",
        data_profile=sample_data_profile,
        unified_columns=["销量", "地区", "日期"],
        planner_instruction=sample_planner_instruction,
        dialogue_history=[
            {"role": "user", "content": "分析Q2销售趋势"},
            {"role": "assistant", "content": "我将按地区和产品线分析Q2销售趋势..."},
            {"role": "user", "content": "按地区拆分，不要按产品"},
        ],
    )

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        result = planner_node(state)

    assert "plan" in result
    assert "error" not in result
    call_arg = mock_llm.invoke.call_args[0][0][1]  # HumanMessage
    assert "CONVERSATION HISTORY" in call_arg.content
    assert "Q2销售趋势" in call_arg.content
    assert "按地区拆分" in call_arg.content


@pytest.mark.unit
def test_planner_agent_reads_instruction_nl(
    set_llm_env: None,
    sample_data_profile: object,
    sample_planner_instruction: object,
) -> None:
    """Planner context emphasizes instruction_nl as the primary input."""
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=_PLAN_JSON)

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        unified_columns=["销量", "地区", "日期"],
        planner_instruction=sample_planner_instruction,
    )

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        result = planner_node(state)

    assert "plan" in result
    assert "error" not in result
    call_arg = mock_llm.invoke.call_args[0][0][1]  # HumanMessage
    assert "READ THIS FIRST" in call_arg.content
    assert "instruction_nl" in call_arg.content


@pytest.mark.unit
def test_planner_agent_falls_back_to_analysis_intent(
    set_llm_env: None,
    sample_data_profile: object,
    sample_analysis_intent: object,
) -> None:
    """Planner falls back to legacy AnalysisIntent when no PlannerInstruction."""
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=_PLAN_JSON)

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        unified_columns=["销量", "地区", "日期"],
        analysis_intent=sample_analysis_intent,
        # No planner_instruction
    )

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        result = planner_node(state)

    assert "plan" in result
    assert "error" not in result
    call_arg = mock_llm.invoke.call_args[0][0][1]  # HumanMessage
    assert "ANALYSIS INTENT" in call_arg.content
    assert "legacy" in call_arg.content.lower()


@pytest.mark.unit
def test_planner_agent_revision_merges_units(
    set_llm_env: None,
    sample_data_profile: object,
) -> None:
    """Planner handles revision (is_revision=true) with workspace."""
    _ = set_llm_env

    from src.agent.state import Plan, PlannerInstruction, PlanUnit

    workspace = Plan(
        units=[
            PlanUnit(
                unit_id=1, purpose="按地区分析趋势", model="线性回归",
                cautious="region列有缺失", related_fields=["地区"],
            )
        ],
        alignment_notes="用户草稿。",
    )

    revision_instr = PlannerInstruction(
        core_question="把地区分析拆成华东和华南",
        analysis_type="comparative",
        complexity="moderate",
        target_columns=["销量"],
        group_by=["地区"],
        is_revision=True,
        target_unit_ids=[1],
        revision_notes="Split region analysis into East and South China",
        instruction_nl="用户要求将地区分析拆分为华东和华南两个区域。",
    )

    revision_json = (
        '{"units": [{"unit_id": 1, "purpose": "华东地区销售趋势", '
        '"model": "线性回归", "cautious": "华东地区样本量可能不足", '
        '"depends_on": [], "input_columns": ["销量", "地区"], '
        '"output_columns": [], "related_fields": ["销量", "地区"]}, '
        '{"unit_id": 2, "purpose": "华南地区销售趋势", '
        '"model": "线性回归", "cautious": "华南地区数据质量需检查", '
        '"depends_on": [], "input_columns": ["销量", "地区"], '
        '"output_columns": [], "related_fields": ["销量", "地区"]}], '
        '"alignment_notes": "修订版：按用户要求拆分地区分析。"}'
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=revision_json)

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="把地区分析拆成华东和华南",
        data_profile=sample_data_profile,
        unified_columns=["销量", "地区", "日期"],
        planner_instruction=revision_instr,
        plan=workspace,
    )

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        result = planner_node(state)

    assert "plan" in result
    assert "error" not in result
    plan = result["plan"]
    assert len(plan.units) == 2
    assert "修订版" in plan.alignment_notes


@pytest.mark.unit
def test_planner_agent_with_workspace(
    set_llm_env: None,
    sample_data_profile: object,
    sample_planner_instruction: object,
) -> None:
    """Planner sees workspace Plan in context."""
    _ = set_llm_env

    from src.agent.state import Plan, PlanUnit

    workspace = Plan(
        units=[
            PlanUnit(
                unit_id=1, purpose="按地区分析趋势", model="线性回归",
                cautious="region列有缺失", related_fields=["地区"],
            )
        ],
        alignment_notes="用户草稿。",
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=_PLAN_JSON)

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        unified_columns=["销量", "地区", "日期"],
        planner_instruction=sample_planner_instruction,
        plan=workspace,
    )

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        result = planner_node(state)

    assert "plan" in result
    assert "error" not in result
    call_arg = mock_llm.invoke.call_args[0][0][1]  # HumanMessage
    assert "WORKSPACE PLAN" in call_arg.content


@pytest.mark.unit
def test_planner_agent_missing_data_profile() -> None:
    """Planner returns error when data_profile is missing."""
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        unified_columns=["销量"],
    )

    result = planner_node(state)
    assert "error" in result
    assert "data_profile" in result["error"]
    assert "plan" not in result


@pytest.mark.unit
def test_planner_agent_missing_unified_columns(
    sample_data_profile: object,
) -> None:
    """Planner returns error when unified_columns is empty."""
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
    )

    result = planner_node(state)
    assert "error" in result
    assert "unified_columns" in result["error"]


@pytest.mark.unit
def test_planner_agent_invalid_json(
    set_llm_env: None,
    sample_data_profile: object,
    sample_planner_instruction: object,
) -> None:
    """Planner handles invalid JSON from LLM gracefully."""
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="not valid json at all")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        unified_columns=["销量", "地区"],
        planner_instruction=sample_planner_instruction,
    )

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        result = planner_node(state)

    assert "error" in result
    assert "parse" in str(result["error"]).lower() or "json" in str(result["error"]).lower()


@pytest.mark.unit
def test_planner_agent_multiple_units(
    set_llm_env: None,
    sample_data_profile: object,
    sample_planner_instruction: object,
) -> None:
    """Planner can produce multiple analysis units."""
    _ = set_llm_env

    multi_json = (
        '{"units": ['
        '{"unit_id": 1, "purpose": "相关性分析", "model": "皮尔逊相关", '
        '"cautious": "样本量可能不足", "depends_on": [], '
        '"input_columns": ["销量", "地区"], "output_columns": [], '
        '"related_fields": ["销量", "地区"]},'
        '{"unit_id": 2, "purpose": "聚类分析", "model": "KMeans", '
        '"cautious": "需先标准化", "depends_on": [], '
        '"input_columns": ["销量"], "output_columns": ["Cluster"], '
        '"related_fields": ["销量"]},'
        '{"unit_id": 3, "purpose": "趋势预测", "model": "线性回归", '
        '"cautious": "时间序列需验证平稳性", "depends_on": [], '
        '"input_columns": ["日期", "销量"], "output_columns": ["prediction"], '
        '"related_fields": ["日期", "销量"]}'
        '], '
        '"alignment_notes": "三个分析维度覆盖了用户问题的核心方面。"}'
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=multi_json)

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="全面分析销售数据",
        data_profile=sample_data_profile,
        unified_columns=["销量", "地区", "日期"],
        planner_instruction=sample_planner_instruction,
    )

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        result = planner_node(state)

    plan = result["plan"]
    assert isinstance(plan, Plan)
    assert len(plan.units) == 3
    assert plan.units[0].unit_id == 1
    assert plan.units[1].unit_id == 2
    assert plan.units[2].unit_id == 3
    assert plan.units[1].model_hint == "KMeans"
    assert plan.units[0].output_columns == []
    assert plan.units[1].output_columns == ["Cluster"]
    assert plan.units[2].output_columns == ["prediction"]


@pytest.mark.unit
def test_planner_agent_input_output_columns_with_deps(
    set_llm_env: None,
    sample_data_profile: object,
    sample_planner_instruction: object,
) -> None:
    """Planner correctly parses input_columns/output_columns with depends_on chain."""
    _ = set_llm_env

    deps_json = (
        '{"units": ['
        '{"unit_id": 1, "purpose": "KMeans聚类", "model": "sklearn.cluster.KMeans", '
        '"cautious": "需标准化", "depends_on": [], '
        '"input_columns": ["销量", "地区"], "output_columns": ["Cluster"], '
        '"related_fields": ["销量", "地区"]},'
        '{"unit_id": 2, "purpose": "按聚类结果分析趋势", "model": "pandas.DataFrame.groupby", '
        '"cautious": "聚类结果可能有偏", "depends_on": [1], '
        '"input_columns": ["日期", "Cluster"], "output_columns": [], '
        '"related_fields": ["日期", "Cluster"]}'
        '], '
        '"alignment_notes": "Unit 2 依赖 Unit 1 的 Cluster 列。"}'
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=deps_json)

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="聚类后按类别分析趋势",
        data_profile=sample_data_profile,
        unified_columns=["销量", "地区", "日期"],
        planner_instruction=sample_planner_instruction,
    )

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        result = planner_node(state)

    assert "plan" in result
    assert "error" not in result
    plan = result["plan"]
    assert len(plan.units) == 2

    u1 = plan.units[0]
    assert u1.unit_id == 1
    assert u1.input_columns == ["销量", "地区"]
    assert u1.output_columns == ["Cluster"]
    assert u1.depends_on == []

    u2 = plan.units[1]
    assert u2.unit_id == 2
    assert u2.input_columns == ["日期", "Cluster"]
    assert "Cluster" in u2.input_columns
    assert u2.output_columns == []
    assert u2.depends_on == [1]


@pytest.mark.unit
def test_planner_agent_without_instruction(
    set_llm_env: None,
    sample_data_profile: object,
) -> None:
    """Planner tolerates missing both instruction and intent (generates best-effort Plan)."""
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=_PLAN_JSON)

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        data_profile=sample_data_profile,
        unified_columns=["销量", "地区"],
        # No planner_instruction, no analysis_intent
    )

    with patch("src.agent.nodes.planner.get_llm", return_value=mock_llm):
        result = planner_node(state)

    assert "plan" in result
    assert "error" not in result
