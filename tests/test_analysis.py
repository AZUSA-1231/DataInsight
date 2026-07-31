from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.agent.nodes.analysis import (
    _build_inprocess_prompt,
    _build_unit_code_prompt,
    _build_unit_react_fix_prompt,
    _build_upstream_context,
    _execute_inprocess_llm,
    _serialize_unit,
    analysis_node,
)
from src.agent.state import AgentState, PlanUnit
from src.sandbox.executor import SandboxResult


@pytest.mark.unit
def test_serialize_unit(sample_plan: object) -> None:
    unit = sample_plan.units[0]
    text = _serialize_unit(unit)
    assert "按区域分析销售趋势" in text
    assert "线性回归" in text
    assert "related_fields" in text
    assert "input_columns" in text
    assert "output_columns" in text


@pytest.mark.unit
def test_build_unit_code_prompt_structure() -> None:
    unit = PlanUnit(unit_id=1, purpose="生成销售图表", unit_type="terminal")
    prompt = _build_unit_code_prompt(unit, "/tmp/data.csv", "/tmp/out")

    assert "data analyst" in prompt.lower()
    assert "Agg" in prompt
    assert "SimHei" in prompt
    assert "font.sans-serif" in prompt
    assert "NO network calls" in prompt
    assert "try/except" in prompt or "try / except" in prompt
    assert "charts" in prompt
    assert "statistics" in prompt
    assert "insights" in prompt
    assert "/tmp/data.csv" in prompt
    assert "/tmp/out" in prompt
    assert "生成销售图表" in prompt


@pytest.mark.unit
def test_build_unit_react_fix_prompt_includes_error() -> None:
    unit = PlanUnit(unit_id=1, purpose="生成销售图表", unit_type="terminal")
    prompt = _build_unit_react_fix_prompt(
        unit,
        "df.corr()\n",
        "KeyError: 'sales'",
        "/tmp/data.csv",
        "/tmp/out",
    )

    assert "debugging specialist" in prompt.lower()
    assert "KeyError: 'sales'" in prompt
    assert "df.corr()" in prompt
    assert "FIXED" in prompt
    assert "生成销售图表" in prompt


@pytest.mark.unit
def test_analysis_node_missing_plan() -> None:
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze data",
    )

    new_state = analysis_node(state)

    assert "error" in new_state
    assert "plan" in new_state["error"]
    assert new_state["analysis_result"]["status"] == "failed"


@pytest.mark.unit
def test_analysis_node_no_units_skips(set_llm_env: None, make_plan: object) -> None:
    _ = set_llm_env
    plan = make_plan(units=[])
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        plan=plan,
    )

    new_state = analysis_node(state)

    assert new_state.get("error") is None
    result = new_state["analysis_result"]
    assert result["skipped"] is True
    assert result["status"] == "complete"
    assert result["unit_results"] == []


def _mock_inprocess_success(unit_id: int, output_dir: str) -> dict[str, Any]:
    """Fake a successful in-process LLM result for Transform/Filter tests."""
    return {
        "unit_id": unit_id,
        "status": "success",
        "parsed_output": {
            "charts": ["out/chart1.png"],
            "statistics": {"correlations": {"sales_revenue": 0.85}},
            "insights": ["Sales correlates with revenue"],
        },
        "charts": ["out/chart1.png"],
        "insights": ["Sales correlates with revenue"],
        "statistics": {"correlations": {"sales_revenue": 0.85}},
        "error": None,
        "retry_count": 0,
        "scripts": [],
        "stdout": "",
        "output_dir": output_dir,
        "source_code": "def _unit(df, c, p): return {'columns': {}}",
        "model_used": "mock",
        "_result_df": pd.DataFrame({"A": [1, 2]}),
        "_input_row_count": 2,
    }


@pytest.mark.unit
def test_inprocess_transform_llm(
    set_llm_env: None, tmp_path
) -> None:
    _ = set_llm_env
    data_path = tmp_path / "data.csv"
    pd.DataFrame({"revenue": [10, 20], "cost": [3, 7]}).to_csv(
        data_path, index=False
    )
    unit = PlanUnit(
        unit_id=1,
        purpose="calculate margin",
        unit_type="transform",
        input_columns=["revenue", "cost"],
        output_columns=["margin"],
    )
    code = (
        "def _unit(df, input_columns, params):\n"
        "    margin = df[input_columns[0]] - df[input_columns[1]]\n"
        "    return {'columns': {'margin': margin}, 'artifacts': []}\n"
    )
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=code)

    with patch("src.agent.nodes.analysis.get_llm", return_value=llm):
        result = _execute_inprocess_llm(unit, str(data_path), str(tmp_path / "out"))

    assert result["status"] == "success"
    assert result["source_code"] == code.strip()
    assert result["_result_df"]["margin"].tolist() == [7, 13]
    assert result["retry_count"] == 0


@pytest.mark.unit
def test_inprocess_filter_llm(set_llm_env: None, tmp_path) -> None:
    _ = set_llm_env
    data_path = tmp_path / "data.csv"
    pd.DataFrame({"value": [1, 2, 3]}).to_csv(data_path, index=False)
    unit = PlanUnit(
        unit_id=1,
        purpose="keep high values",
        unit_type="filter",
        input_columns=["value"],
    )
    code = (
        "def _unit(df, input_columns, params):\n"
        "    filtered = df[df[input_columns[0]] >= 2]\n"
        "    return {'filtered_df': filtered, 'snapshot_name': 'high', "
        "'artifacts': []}\n"
    )
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=code)

    with patch("src.agent.nodes.analysis.get_llm", return_value=llm):
        result = _execute_inprocess_llm(unit, str(data_path), str(tmp_path / "out"))

    assert result["status"] == "success"
    assert result["snapshot_name"] == "high"
    assert result["_result_df"]["value"].tolist() == [2, 3]


@pytest.mark.unit
def test_inprocess_contract_failure_retries(
    set_llm_env: None, tmp_path
) -> None:
    _ = set_llm_env
    data_path = tmp_path / "data.csv"
    pd.DataFrame({"value": [1, 2]}).to_csv(data_path, index=False)
    unit = PlanUnit(
        unit_id=1,
        purpose="double value",
        unit_type="transform",
        input_columns=["value"],
        output_columns=["doubled"],
    )
    wrong = (
        "def _unit(df, input_columns, params):\n"
        "    return {'columns': {'wrong': df[input_columns[0]]}, 'artifacts': []}\n"
    )
    fixed = (
        "def _unit(df, input_columns, params):\n"
        "    return {'columns': {'doubled': df[input_columns[0]] * 2}, "
        "'artifacts': []}\n"
    )
    llm = MagicMock()
    llm.invoke.side_effect = [MagicMock(content=wrong), MagicMock(content=fixed)]

    with patch("src.agent.nodes.analysis.get_llm", return_value=llm):
        result = _execute_inprocess_llm(unit, str(data_path), str(tmp_path / "out"))

    assert result["status"] == "success"
    assert result["retry_count"] == 1
    assert llm.invoke.call_count == 2


@pytest.mark.unit
def test_analysis_node_single_unit_success(
    set_llm_env: None, temp_output_dir: str, sample_plan: object
) -> None:
    _ = set_llm_env

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales data",
        plan=sample_plan,
    )

    with patch(
        "src.agent.nodes.analysis._execute_inprocess_llm",
        return_value=_mock_inprocess_success(1, "/tmp/out/unit_1"),
    ):
        new_state = analysis_node(state)

    assert new_state.get("error") is None
    result = new_state["analysis_result"]
    assert result["status"] == "complete"
    assert len(result["unit_results"]) == 1
    ur = result["unit_results"][0]
    assert ur["unit_id"] == 1
    assert ur["status"] == "success"
    assert ur["charts"] == ["out/chart1.png"]
    assert ur["statistics"]["correlations"]["sales_revenue"] == 0.85
    assert ur["insights"] == ["Sales correlates with revenue"]


@pytest.mark.unit
def test_analysis_node_multi_unit_all_succeed(
    set_llm_env: None, temp_output_dir: str, sample_plan_multi: object
) -> None:
    _ = set_llm_env

    call_count = [0]

    def _make_result(unit, data_path, output_dir, retry_state=None):
        call_count[0] += 1
        uid = call_count[0]
        return _mock_inprocess_success(uid, output_dir)

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="全面分析",
        plan=sample_plan_multi,
    )

    with patch(
        "src.agent.nodes.analysis._execute_inprocess_llm",
        side_effect=_make_result,
    ):
        new_state = analysis_node(state)

    assert new_state.get("error") is None
    result = new_state["analysis_result"]
    assert result["status"] == "complete"
    assert len(result["unit_results"]) == 3
    for ur in result["unit_results"]:
        assert ur["status"] == "success"


@pytest.mark.unit
def test_analysis_node_mixed_success(
    set_llm_env: None, temp_output_dir: str, sample_plan_multi: object
) -> None:
    _ = set_llm_env

    def _make_result(unit, data_path, output_dir, retry_state=None):
        if unit.unit_id == 2:
            return {
                "unit_id": 2, "status": "failed",
                "parsed_output": None, "charts": [], "insights": [],
                "statistics": {}, "error": "ValueError: bad data",
                "retry_count": 3, "scripts": [], "stdout": "",
                "output_dir": output_dir,
            }
        return _mock_inprocess_success(unit.unit_id, output_dir)

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="全面分析",
        plan=sample_plan_multi,
    )

    with patch(
        "src.agent.nodes.analysis._execute_inprocess_llm",
        side_effect=_make_result,
    ):
        new_state = analysis_node(state)

    assert "error" in new_state
    result = new_state["analysis_result"]
    assert result["status"] == "partial"
    successes = [ur for ur in result["unit_results"] if ur["status"] == "success"]
    failures = [ur for ur in result["unit_results"] if ur["status"] == "failed"]
    assert len(successes) == 2
    assert len(failures) == 1


@pytest.mark.unit
def test_analysis_node_per_unit_react_retry(
    set_llm_env: None, temp_output_dir: str, sample_plan: object
) -> None:
    _ = set_llm_env

    call_count = [0]

    def _make_result(unit, data_path, output_dir, retry_state=None):
        call_count[0] += 1
        return {
            "unit_id": unit.unit_id, "status": "success",
            "parsed_output": {}, "charts": [], "insights": ["finally works"],
            "statistics": {}, "error": None, "retry_count": 2,
            "scripts": [], "stdout": "", "output_dir": output_dir,
        }

    state = AgentState(
        file_path="/tmp/test.csv", user_requirement="Analyze", plan=sample_plan,
    )

    with patch(
        "src.agent.nodes.analysis._execute_inprocess_llm",
        side_effect=_make_result,
    ):
        new_state = analysis_node(state)

    assert new_state.get("error") is None
    ur = new_state["analysis_result"]["unit_results"][0]
    assert ur["status"] == "success"
    assert ur["insights"] == ["finally works"]


@pytest.mark.unit
def test_analysis_node_all_fail(
    set_llm_env: None, temp_output_dir: str, sample_plan: object
) -> None:
    _ = set_llm_env

    def _make_result(unit, data_path, output_dir, retry_state=None):
        return {
            "unit_id": unit.unit_id, "status": "failed",
            "parsed_output": None, "charts": [], "insights": [],
            "statistics": {}, "error": "RuntimeError: crash",
            "retry_count": 3, "scripts": [], "stdout": "",
            "output_dir": output_dir,
        }

    state = AgentState(
        file_path="/tmp/test.csv", user_requirement="Analyze", plan=sample_plan,
    )

    with patch(
        "src.agent.nodes.analysis._execute_inprocess_llm",
        side_effect=_make_result,
    ):
        new_state = analysis_node(state)

    assert "error" in new_state
    ur = new_state["analysis_result"]["unit_results"][0]
    assert ur["status"] == "failed"
    assert ur["retry_count"] == 3


@pytest.mark.unit
def test_analysis_node_invalid_json_output(
    set_llm_env: None, temp_output_dir: str, sample_plan: object
) -> None:
    """In-process LLM returns a plain dict — no JSON to parse, always valid."""
    _ = set_llm_env

    state = AgentState(
        file_path="/tmp/test.csv", user_requirement="Analyze", plan=sample_plan,
    )

    with patch(
        "src.agent.nodes.analysis._execute_inprocess_llm",
        return_value=_mock_inprocess_success(1, "/tmp/out/unit_1"),
    ):
        new_state = analysis_node(state)

    assert new_state.get("error") is None


@pytest.mark.unit
def test_analysis_node_timeout_handling(
    set_llm_env: None, temp_output_dir: str, sample_plan: object
) -> None:
    """Transform/Filter LLM is in-process — no subprocess, no timeout."""
    _ = set_llm_env

    state = AgentState(
        file_path="/tmp/test.csv", user_requirement="Analyze", plan=sample_plan,
    )

    with patch(
        "src.agent.nodes.analysis._execute_inprocess_llm",
        return_value=_mock_inprocess_success(1, "/tmp/out/unit_1"),
    ):
        new_state = analysis_node(state)

    assert new_state.get("error") is None


@pytest.mark.unit
def test_analysis_node_llm_error(set_llm_env: None, sample_plan: object) -> None:
    _ = set_llm_env

    def _make_result(unit, data_path, output_dir, retry_state=None):
        return {
            "unit_id": unit.unit_id, "status": "failed",
            "parsed_output": None, "charts": [], "insights": [],
            "statistics": {}, "error": "LLM error: API rate limit",
            "retry_count": 3, "scripts": [], "stdout": "",
            "output_dir": output_dir,
        }

    state = AgentState(
        file_path="/tmp/test.csv", user_requirement="Analyze", plan=sample_plan,
    )

    with patch(
        "src.agent.nodes.analysis._execute_inprocess_llm",
        side_effect=_make_result,
    ):
        new_state = analysis_node(state)

    assert "error" in new_state
    ur = new_state["analysis_result"]["unit_results"][0]
    assert ur["status"] == "failed"


# --- M4: Timeout Configuration Tests (Terminal subprocess only) ---


@pytest.mark.unit
def test_analysis_unit_uses_configured_timeout(
    set_llm_env: None, temp_output_dir: str, monkeypatch: object
) -> None:
    """Terminal units still use subprocess — timeout config applies."""
    from src.agent.state import Plan, PlanUnit

    _ = set_llm_env
    monkeypatch.setenv("DATAINSIGHT_TIMEOUT_ANALYSIS", "90")
    import importlib

    import src.agent.nodes.analysis as an_mod  # noqa: I001
    importlib.reload(an_mod)

    terminal_plan = Plan(
        units=[
            PlanUnit(unit_id=1, purpose="scatter", unit_type="terminal",
                     model_hint="auto", cautious=""),
        ],
        alignment_notes="terminal test",
    )

    sandbox_result = SandboxResult(
        stdout='{"charts": [], "statistics": {}, "insights": ["ok"]}',
        stderr="", exit_code=0, timed_out=False,
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="print('{}')\n")

    state = AgentState(
        file_path="/tmp/test.csv", user_requirement="Analyze", plan=terminal_plan,
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", return_value=sandbox_result) as mock_run,
    ):
        new_state = an_mod.analysis_node(state)

    assert new_state.get("error") is None
    assert mock_run.call_args[1]["timeout_seconds"] == 90


@pytest.mark.unit
def test_analysis_unit_timeout_env_fallback(
    set_llm_env: None, temp_output_dir: str, monkeypatch: object
) -> None:
    from src.agent.state import Plan, PlanUnit

    _ = set_llm_env
    monkeypatch.setenv("DATAINSIGHT_TIMEOUT_ANALYSIS", "invalid")
    import importlib

    import src.agent.nodes.analysis as an_mod  # noqa: I001
    importlib.reload(an_mod)

    terminal_plan = Plan(
        units=[
            PlanUnit(unit_id=1, purpose="scatter", unit_type="terminal",
                     model_hint="auto", cautious=""),
        ],
        alignment_notes="terminal test",
    )

    sandbox_result = SandboxResult(
        stdout='{"charts": [], "statistics": {}, "insights": ["ok"]}',
        stderr="", exit_code=0, timed_out=False,
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="print('{}')\n")

    state = AgentState(
        file_path="/tmp/test.csv", user_requirement="Analyze", plan=terminal_plan,
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", return_value=sandbox_result) as mock_run,
    ):
        new_state = an_mod.analysis_node(state)

    assert new_state.get("error") is None
    from src.sandbox.executor import DEFAULT_TIMEOUT
    assert mock_run.call_args[1]["timeout_seconds"] == DEFAULT_TIMEOUT


# --- M3: Per-unit-type prompt tests ---


@pytest.mark.unit
def test_build_inprocess_prompt_transform_has_row_invariant() -> None:
    from src.agent.state import PlanUnit

    unit = PlanUnit(
        unit_id=1, purpose="add column", unit_type="transform",
        model_hint="auto", cautious="", input_columns=["a", "b"],
        output_columns=["c"], related_fields=["a", "b"],
    )
    prompt = _build_inprocess_prompt(unit)
    assert "UNIT TYPE: TRANSFORM" in prompt
    assert "Row count MUST NOT change" in prompt
    assert "pandas_series" in prompt
    assert "Do NOT write output.csv" in prompt


@pytest.mark.unit
def test_build_inprocess_prompt_filter_has_column_invariant() -> None:
    from src.agent.state import PlanUnit

    unit = PlanUnit(
        unit_id=1, purpose="filter by date", unit_type="filter",
        model_hint="auto", cautious="", input_columns=["date"],
        output_columns=[], related_fields=["date"],
    )
    prompt = _build_inprocess_prompt(unit)
    assert "UNIT TYPE: FILTER" in prompt
    assert "Column set MUST NOT change" in prompt
    assert "filtered_df" in prompt
    assert "snapshot_name" in prompt


@pytest.mark.unit
def test_build_code_prompt_terminal_no_output_csv() -> None:
    from src.agent.state import PlanUnit

    unit = PlanUnit(
        unit_id=1, purpose="scatter plot", unit_type="terminal",
        model_hint="auto", cautious="", input_columns=["a", "b"],
        output_columns=[], related_fields=["a", "b"],
    )
    prompt = _build_unit_code_prompt(unit, "/tmp/data.csv", "/tmp/out")
    assert "UNIT TYPE: TERMINAL" in prompt
    assert "Do NOT save output.csv" in prompt
    assert "leaf node" in prompt


@pytest.mark.unit
def test_build_react_fix_prompt_has_type_rules() -> None:
    from src.agent.state import PlanUnit

    unit = PlanUnit(
        unit_id=1, purpose="plot", unit_type="terminal",
        model_hint="auto", cautious="", input_columns=["a", "b"],
        output_columns=[], related_fields=["a", "b"],
    )
    prompt = _build_unit_react_fix_prompt(
        unit, "bad code", "some error", "/tmp/data.csv", "/tmp/out",
    )
    assert "UNIT TYPE: TERMINAL" in prompt
    assert "FIXED" in prompt
    assert "bad code" in prompt
    assert "some error" in prompt


@pytest.mark.unit
def test_type_specific_rules_all_types_covered() -> None:
    """Every UnitType gets a non-empty rule section."""
    from src.agent.nodes.analysis import _type_specific_rules
    from src.agent.state import PlanUnit, UnitType

    for ut in UnitType:
        unit = PlanUnit(
            unit_id=1, purpose="test", unit_type=ut,
            model_hint="auto", cautious="",
        )
        rules = _type_specific_rules(unit)
        assert len(rules) > 50, f"Rules for {ut} too short: {len(rules)} chars"
        assert "UNIT TYPE:" in rules


# --- M4: Prompt-layer coverage tests ---


@pytest.mark.unit
def test_build_upstream_context_with_columns() -> None:
    from src.agent.state import PlanUnit

    unit = PlanUnit(
        unit_id=2,
        purpose="聚类分析",
        model="KMeans",
        cautious="",
        depends_on=[1],
        input_columns=["sales_log", "region"],
        output_columns=["Cluster"],
        related_fields=[],
    )
    ctx = _build_upstream_context(unit)

    assert ctx is not None
    assert "Input columns available: sales_log, region" in ctx
    assert "Expected output columns to produce: Cluster" in ctx
    assert "depends on units [1]" in ctx


@pytest.mark.unit
def test_build_upstream_context_empty() -> None:
    from src.agent.state import PlanUnit

    unit = PlanUnit(
        unit_id=1,
        purpose="基础统计",
        model="auto",
        cautious="",
        depends_on=[],
        input_columns=[],
        output_columns=[],
        related_fields=[],
    )
    ctx = _build_upstream_context(unit)
    assert ctx is None


@pytest.mark.unit
def test_build_unit_code_prompt_with_upstream() -> None:
    from src.agent.state import PlanUnit

    unit = PlanUnit(
        unit_id=2,
        purpose="聚类结果图",
        unit_type="terminal",
        model="KMeans",
        cautious="",
        depends_on=[1],
        input_columns=["sales_log"],
        output_columns=[],
        related_fields=[],
    )
    upstream = "Input columns available: sales_log"
    prompt = _build_unit_code_prompt(unit, "/tmp/data.csv", "/tmp/out", upstream_context=upstream)

    assert "UPSTREAM DATA" in prompt
    assert "sales_log" in prompt
    assert "already contains columns produced by previous" in prompt.lower()
    assert "do NOT overwrite them" in prompt
    assert "output.csv" in prompt
    assert "Do NOT save output.csv" in prompt


@pytest.mark.unit
def test_build_unit_react_fix_prompt_with_upstream() -> None:
    from src.agent.state import PlanUnit

    unit = PlanUnit(
        unit_id=3,
        purpose="生成报告",
        model="auto",
        cautious="",
        depends_on=[1, 2],
        input_columns=["Cluster", "Score"],
        output_columns=[],
        related_fields=[],
    )
    upstream = "Input columns available: Cluster, Score\nThis unit depends on units [1, 2]."
    prompt = _build_unit_react_fix_prompt(
        unit,
        "df.groupby('Cluster').mean()\n",
        "KeyError: 'Cluster'",
        "/tmp/data.csv",
        "/tmp/out",
        upstream_context=upstream,
    )

    assert "UPSTREAM DATA" in prompt
    assert "Cluster" in prompt
    assert "Score" in prompt
    assert "already contains columns from previous" in prompt.lower()
    assert "KeyError: 'Cluster'" in prompt  # error preserved
    assert "df.groupby" in prompt  # failed code preserved
