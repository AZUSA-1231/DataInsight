from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from src.agent.nodes.analysis import (
    _build_inprocess_prompt,
    _build_unit_code_prompt,
    _build_unit_react_fix_prompt,
    _build_upstream_context,
    _execute_inprocess_llm,
    _serialize_unit,
    analysis_node,
)
from src.agent.state import (
    AgentState,
    DeriveColumnUnit,
    FilterUnit,
    Plan,
    TerminalUnit,
)


def _terminal() -> TerminalUnit:
    return TerminalUnit(
        unit_id=1,
        purpose="inspect sales",
        input_snapshot="orders",
        input_columns=["orders.amount"],
    )


def test_serialize_v2_unit_preserves_operation_fields() -> None:
    text = _serialize_unit(_terminal())
    assert '"unit_type": "terminal"' in text
    assert "orders.amount" in text
    assert "input_columns" in text


def test_terminal_prompts_keep_sandbox_contract() -> None:
    unit = _terminal()
    prompt = _build_unit_code_prompt(unit, "data.parquet", "out")
    retry = _build_unit_react_fix_prompt(
        unit, "print('{}')", "KeyError: 'amount'", "data.parquet", "out"
    )
    for text in (prompt, retry):
        assert "Agg" in text
        assert "network" in text.lower()
        assert "charts" in text
        assert "statistics" in text
        assert "insights" in text
    assert "KeyError: 'amount'" in retry


def test_analysis_node_requires_a_plan() -> None:
    result = analysis_node(AgentState(user_requirement="Analyze data"))
    assert result["analysis_result"]["status"] == "failed"
    assert "plan" in result["error"]


def test_analysis_node_skips_empty_plan() -> None:
    result = analysis_node(
        AgentState(user_requirement="Analyze data", plan=Plan(units=[]))
    )
    assert result["analysis_result"]["status"] == "complete"
    assert result["analysis_result"]["skipped"] is True


def test_inprocess_transform_v2_unit(set_llm_env: None, tmp_path) -> None:
    _ = set_llm_env
    data_path = tmp_path / "data.csv"
    pd.DataFrame({"revenue": [10, 20], "cost": [3, 7]}).to_csv(
        data_path, index=False
    )
    unit = DeriveColumnUnit(
        unit_id=1,
        purpose="calculate margin",
        input_snapshot="orders",
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
    assert result["_result_df"]["margin"].tolist() == [7, 13]


def test_inprocess_filter_v2_unit(set_llm_env: None, tmp_path) -> None:
    _ = set_llm_env
    data_path = tmp_path / "data.csv"
    pd.DataFrame({"value": [1, 2, 3]}).to_csv(data_path, index=False)
    unit = FilterUnit(
        unit_id=1,
        purpose="keep high values",
        input_snapshot="orders",
        input_columns=["value"],
        output_snapshot="high",
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
    assert result["_result_df"]["value"].tolist() == [2, 3]


def test_inprocess_contract_failure_retries(set_llm_env: None, tmp_path) -> None:
    _ = set_llm_env
    data_path = tmp_path / "data.csv"
    pd.DataFrame({"value": [1, 2]}).to_csv(data_path, index=False)
    unit = DeriveColumnUnit(
        unit_id=1,
        purpose="double value",
        input_snapshot="orders",
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


def test_prompt_type_rules_and_upstream_context() -> None:
    derive = DeriveColumnUnit(
        unit_id=1,
        purpose="derive",
        input_snapshot="orders",
        input_columns=["amount"],
        output_columns=["total"],
    )
    filter_unit = FilterUnit(
        unit_id=2,
        purpose="filter",
        input_snapshot="orders",
        input_columns=["region"],
        output_snapshot="east",
    )
    derive_prompt = _build_inprocess_prompt(derive)
    filter_prompt = _build_inprocess_prompt(filter_unit)
    assert "Row count MUST NOT change" in derive_prompt
    assert "Column set MUST NOT change" in filter_prompt
    assert "Input columns available" in (_build_upstream_context(derive) or "")
