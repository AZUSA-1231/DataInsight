from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.analysis import (
    _build_unit_code_prompt,
    _build_unit_react_fix_prompt,
    _serialize_unit,
    analysis_node,
)
from src.agent.state import AgentState
from src.sandbox.executor import SandboxResult


@pytest.mark.unit
def test_serialize_unit(sample_plan: object) -> None:
    unit = sample_plan.units[0]
    text = _serialize_unit(unit)
    assert "按区域分析销售趋势" in text
    assert "线性回归" in text
    assert "related_fields" in text


@pytest.mark.unit
def test_build_unit_code_prompt_structure(sample_plan: object) -> None:
    unit = sample_plan.units[0]
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
    assert "按区域分析销售趋势" in prompt


@pytest.mark.unit
def test_build_unit_react_fix_prompt_includes_error(sample_plan: object) -> None:
    unit = sample_plan.units[0]
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
    assert "按区域分析销售趋势" in prompt


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


@pytest.mark.unit
def test_analysis_node_single_unit_success(
    set_llm_env: None, temp_output_dir: str, sample_plan: object
) -> None:
    _ = set_llm_env

    valid_script = (
        "import sys; print('"
        '{"charts": ["out/chart1.png"],'
        ' "statistics": {"correlations": {"sales_revenue": 0.85}},'
        ' "insights": ["Sales correlates with revenue"]}'
        "')"
    )
    sandbox_result = SandboxResult(
        stdout='{"charts": ["out/chart1.png"], '
        '"statistics": {"correlations": {"sales_revenue": 0.85}}, '
        '"insights": ["Sales correlates with revenue"]}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = valid_script
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales data",
        plan=sample_plan,
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", return_value=sandbox_result),
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

    def _make_response():
        call_count[0] += 1
        uid = call_count[0]
        content = (
            'import sys; print(\''
            f'{{"charts": ["out/unit{uid}_chart.png"],'
            f' "statistics": {{"r{uid}": 0.{uid * 10}}},'
            f' "insights": ["Unit {uid} insight"]}}\''
            ')'
        )
        return content

    def _make_sandbox_result(stdout):
        return SandboxResult(stdout=stdout, stderr="", exit_code=0, timed_out=False)

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = lambda prompt: MagicMock(content=_make_response())

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="全面分析",
        plan=sample_plan_multi,
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch(
            "src.agent.nodes.analysis.run_script",
            side_effect=lambda script_path, args, **kwargs: _make_sandbox_result(
                '{"charts": ["out/chart.png"], "statistics": {}, "insights": ["ok"]}'
            ),
        ),
    ):
        new_state = analysis_node(state)

    assert new_state.get("error") is None
    result = new_state["analysis_result"]
    assert result["status"] == "complete"
    assert len(result["unit_results"]) == 3
    unit_ids = [ur["unit_id"] for ur in result["unit_results"]]
    assert unit_ids == [1, 2, 3]
    for ur in result["unit_results"]:
        assert ur["status"] == "success"


@pytest.mark.unit
def test_analysis_node_mixed_success(
    set_llm_env: None, temp_output_dir: str, sample_plan_multi: object
) -> None:
    _ = set_llm_env

    def _make_sandbox_result(script_path, args, **kwargs):
        # Unit 2 always fails (script_path contains "u2_")
        if "u2_" in str(script_path):
            return SandboxResult(
                stdout="", stderr="ValueError: bad data", exit_code=1, timed_out=False
            )
        return SandboxResult(
            stdout='{"charts": [], "statistics": {}, "insights": ["ok"]}',
            stderr="",
            exit_code=0,
            timed_out=False,
        )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="print('{}')\n")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="全面分析",
        plan=sample_plan_multi,
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", side_effect=_make_sandbox_result),
    ):
        new_state = analysis_node(state)

    assert "error" in new_state
    result = new_state["analysis_result"]
    assert result["status"] == "partial"
    assert len(result["unit_results"]) == 3
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

    def _make_sandbox_result(script_path, args, **kwargs):
        call_count[0] += 1
        if call_count[0] < 3:
            return SandboxResult(
                stdout="", stderr="ValueError: try again", exit_code=1, timed_out=False
            )
        return SandboxResult(
            stdout='{"charts": [], "statistics": {}, "insights": ["finally works"]}',
            stderr="",
            exit_code=0,
            timed_out=False,
        )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="print('{}')\n")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        plan=sample_plan,
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", side_effect=_make_sandbox_result),
    ):
        new_state = analysis_node(state)

    assert new_state.get("error") is None
    ur = new_state["analysis_result"]["unit_results"][0]
    assert ur["status"] == "success"
    assert ur["retry_count"] == 2
    assert ur["insights"] == ["finally works"]
    assert mock_llm.invoke.call_count == 3


@pytest.mark.unit
def test_analysis_node_all_fail(
    set_llm_env: None, temp_output_dir: str, sample_plan: object
) -> None:
    _ = set_llm_env

    sandbox_result = SandboxResult(
        stdout="", stderr="RuntimeError: crash", exit_code=1, timed_out=False
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="print('{}')\n")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        plan=sample_plan,
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", return_value=sandbox_result),
    ):
        new_state = analysis_node(state)

    assert "error" in new_state
    result = new_state["analysis_result"]
    assert result["status"] == "partial"
    ur = result["unit_results"][0]
    assert ur["status"] == "failed"
    assert ur["retry_count"] == 3


@pytest.mark.unit
def test_analysis_node_invalid_json_output(
    set_llm_env: None, temp_output_dir: str, sample_plan: object
) -> None:
    _ = set_llm_env

    bad_result = SandboxResult(
        stdout="Analysis done\nbut no JSON here!",
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="print('no json')\n")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        plan=sample_plan,
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", return_value=bad_result),
    ):
        new_state = analysis_node(state)

    assert "error" in new_state
    result = new_state["analysis_result"]
    assert result["status"] == "partial"
    ur = result["unit_results"][0]
    assert ur["status"] == "failed"


@pytest.mark.unit
def test_analysis_node_timeout_handling(
    set_llm_env: None, temp_output_dir: str, sample_plan: object
) -> None:
    _ = set_llm_env

    timeout_result = SandboxResult(
        stdout="partial...",
        stderr="",
        exit_code=-1,
        timed_out=True,
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="print('slow')\n")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        plan=sample_plan,
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", return_value=timeout_result),
    ):
        new_state = analysis_node(state)

    assert "error" in new_state
    result = new_state["analysis_result"]
    ur = result["unit_results"][0]
    assert ur["status"] == "failed"


@pytest.mark.unit
def test_analysis_node_uses_cleaned_data_path(
    set_llm_env: None, temp_output_dir: str, sample_plan: object
) -> None:
    _ = set_llm_env

    valid_script = (
        'import sys; print(\'{"charts": [], "statistics": {}, "insights": ["from cleaned"]}\')'
    )
    sandbox_result = SandboxResult(
        stdout='{"charts": [], "statistics": {}, "insights": ["from cleaned"]}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=valid_script)

    state = AgentState(
        file_path="/tmp/original.csv",
        user_requirement="Analyze",
        plan=sample_plan,
        preprocessing_result={
            "retry_count": 0,
            "attempts": [],
            "parsed_output": {
                "cleaned_shape": {"rows": 95, "cols": 3},
                "cleaning_actions": ["dropped nulls"],
                "cleaned_data_path": "/tmp/out/cleaned_data.csv",
            },
        },
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", return_value=sandbox_result) as mock_run,
    ):
        new_state = analysis_node(state)

    assert new_state.get("error") is None
    args, _ = mock_run.call_args
    assert args[1][0] == "/tmp/out/cleaned_data.csv"


@pytest.mark.unit
def test_analysis_node_llm_error(set_llm_env: None, sample_plan: object) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API rate limit")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        plan=sample_plan,
    )

    with patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm):
        new_state = analysis_node(state)

    assert "error" in new_state
    result = new_state["analysis_result"]
    ur = result["unit_results"][0]
    assert ur["status"] == "failed"


# --- M4: Timeout Configuration Tests ---


@pytest.mark.unit
def test_analysis_unit_uses_configured_timeout(
    set_llm_env: None, temp_output_dir: str, sample_plan: object, monkeypatch: object
) -> None:
    _ = set_llm_env

    monkeypatch.setenv("DATAINSIGHT_TIMEOUT_ANALYSIS", "90")
    import importlib

    import src.agent.nodes.analysis as an_mod
    importlib.reload(an_mod)

    sandbox_result = SandboxResult(
        stdout='{"charts": [], "statistics": {}, "insights": ["ok"]}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="print('{}')\n")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        plan=sample_plan,
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
    set_llm_env: None, temp_output_dir: str, sample_plan: object, monkeypatch: object
) -> None:
    _ = set_llm_env

    monkeypatch.setenv("DATAINSIGHT_TIMEOUT_ANALYSIS", "invalid")
    import importlib

    import src.agent.nodes.analysis as an_mod
    importlib.reload(an_mod)

    sandbox_result = SandboxResult(
        stdout='{"charts": [], "statistics": {}, "insights": ["ok"]}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="print('{}')\n")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        plan=sample_plan,
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", return_value=sandbox_result) as mock_run,
    ):
        new_state = an_mod.analysis_node(state)

    assert new_state.get("error") is None
    from src.sandbox.executor import DEFAULT_TIMEOUT
    assert mock_run.call_args[1]["timeout_seconds"] == DEFAULT_TIMEOUT
