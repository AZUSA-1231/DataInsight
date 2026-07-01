from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.analysis import (
    _build_analysis_code_prompt,
    _build_analysis_react_fix_prompt,
    _extract_code_block,
    _serialize_analysis_steps,
    analysis_node,
)
from src.agent.state import AgentState
from src.sandbox.executor import SandboxResult


@pytest.mark.unit
def test_serialize_analysis_steps(make_execution_plan: object) -> None:
    plan = make_execution_plan()
    text = _serialize_analysis_steps(plan)
    assert "compute_correlation" in text
    assert "sales" in text


@pytest.mark.unit
def test_serialize_analysis_steps_fallback() -> None:
    assert _serialize_analysis_steps("not a plan") == "[]"


@pytest.mark.unit
def test_extract_code_block_no_fence() -> None:
    code = "print('hello')\n"
    assert _extract_code_block(code) == code.strip()


@pytest.mark.unit
def test_extract_code_block_with_fence() -> None:
    text = "Some text\n```python\nprint('hello')\n```\nMore text"
    assert _extract_code_block(text) == "print('hello')"


@pytest.mark.unit
def test_extract_code_block_no_language_tag() -> None:
    text = "```\nprint('hello')\n```"
    assert _extract_code_block(text) == "print('hello')"


@pytest.mark.unit
def test_build_analysis_code_prompt_structure(make_execution_plan: object) -> None:
    prompt = _build_analysis_code_prompt(make_execution_plan(), "/tmp/data.csv", "/tmp/out")

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
    assert "compute_correlation" in prompt


@pytest.mark.unit
def test_build_analysis_react_fix_prompt_includes_error(make_execution_plan: object) -> None:
    prompt = _build_analysis_react_fix_prompt(
        make_execution_plan(),
        "df.corr()\n",
        "KeyError: 'sales'",
        "/tmp/data.csv",
        "/tmp/out",
    )

    assert "debugging specialist" in prompt.lower()
    assert "KeyError: 'sales'" in prompt
    assert "df.corr()" in prompt
    assert "FIXED" in prompt
    assert "compute_correlation" in prompt


@pytest.mark.unit
def test_analysis_node_missing_execution_plan() -> None:
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze data",
    )

    new_state = analysis_node(state)

    assert "error" in new_state
    assert "execution_plan" in new_state["error"]
    assert new_state["analysis_result"]["retry_count"] == 3


@pytest.mark.unit
def test_analysis_node_no_analysis_steps_skips(
    set_llm_env: None, make_execution_plan: object
) -> None:
    _ = set_llm_env
    plan = make_execution_plan(analysis_steps=[])
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        execution_plan=plan,
    )

    new_state = analysis_node(state)

    assert new_state.get("error") is None
    result = new_state["analysis_result"]
    assert result["skipped"] is True
    assert result["charts"] == []
    assert result["statistics"] == {}
    assert result["insights"] == []


@pytest.mark.unit
def test_analysis_node_success_first_attempt(
    set_llm_env: None, temp_output_dir: str, make_execution_plan: object
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
        execution_plan=make_execution_plan(),
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", return_value=sandbox_result),
    ):
        new_state = analysis_node(state)

    assert new_state.get("error") is None
    assert "analysis_result" in new_state
    result = new_state["analysis_result"]
    assert result["retry_count"] == 0
    assert "parsed_output" in result
    assert result["parsed_output"]["charts"] == ["out/chart1.png"]
    assert result["parsed_output"]["statistics"]["correlations"]["sales_revenue"] == 0.85
    assert result["parsed_output"]["insights"] == ["Sales correlates with revenue"]


@pytest.mark.unit
def test_analysis_node_sandbox_error_triggers_retry(
    set_llm_env: None, temp_output_dir: str, make_execution_plan: object
) -> None:
    _ = set_llm_env

    sandbox_result = SandboxResult(
        stdout="",
        stderr="KeyError: 'sales'",
        exit_code=1,
        timed_out=False,
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "df[['sales', 'revenue']].corr()\n"
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        execution_plan=make_execution_plan(),
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", return_value=sandbox_result),
    ):
        new_state = analysis_node(state)

    assert "error" in new_state
    assert "KeyError" in new_state["error"]
    an_result = new_state["analysis_result"]
    assert an_result["retry_count"] == 1
    assert len(an_result["attempts"]) == 1
    assert an_result["attempts"][0]["error"] == "KeyError: 'sales'"


@pytest.mark.unit
def test_analysis_node_react_retry_then_success(
    set_llm_env: None, temp_output_dir: str, make_execution_plan: object
) -> None:
    _ = set_llm_env

    fail_result = SandboxResult(
        stdout="", stderr="ValueError: cannot compute", exit_code=1, timed_out=False
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "df.corr()\n"
    mock_llm.invoke.return_value = mock_response

    plan = make_execution_plan()
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        execution_plan=plan,
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", return_value=fail_result),
    ):
        state_dict = analysis_node(state)

    assert "error" in state_dict
    assert state_dict["analysis_result"]["retry_count"] == 1

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        execution_plan=plan,
        analysis_result=state_dict["analysis_result"],
    )

    fix_result = SandboxResult(
        stdout='{"charts": ["out/chart1.png"], '
        '"statistics": {"correlations": {"sales_revenue": 0.92}}, '
        '"insights": ["Strong positive correlation"]}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    mock_llm2 = MagicMock()
    mock_response2 = MagicMock()
    mock_response2.content = "df[['sales', 'revenue']].corr()\n"
    mock_llm2.invoke.return_value = mock_response2

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm2),
        patch("src.agent.nodes.analysis.run_script", return_value=fix_result),
    ):
        state_dict2 = analysis_node(state)

    assert state_dict2.get("error") is None
    an_result = state_dict2["analysis_result"]
    assert an_result["parsed_output"]["statistics"]["correlations"]["sales_revenue"] == 0.92
    assert len(an_result["attempts"]) == 1
    assert an_result["retry_count"] == 1


@pytest.mark.unit
def test_analysis_node_timeout_handling(
    set_llm_env: None, temp_output_dir: str, make_execution_plan: object
) -> None:
    _ = set_llm_env

    timeout_result = SandboxResult(
        stdout="partial...",
        stderr="",
        exit_code=-1,
        timed_out=True,
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "while True: pass\n"
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        execution_plan=make_execution_plan(),
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", return_value=timeout_result),
    ):
        new_state = analysis_node(state)

    assert "error" in new_state
    assert "TIMEOUT" in new_state["error"]
    assert new_state["analysis_result"]["retry_count"] == 1


@pytest.mark.unit
def test_analysis_node_invalid_json_output(
    set_llm_env: None, temp_output_dir: str, make_execution_plan: object
) -> None:
    _ = set_llm_env

    bad_result = SandboxResult(
        stdout="Analysis done\nbut no JSON here!",
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "print('no json')\n"
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        execution_plan=make_execution_plan(),
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", return_value=bad_result),
    ):
        new_state = analysis_node(state)

    assert "error" in new_state
    assert "invalid json" in new_state["error"].lower()
    assert new_state["analysis_result"]["retry_count"] == 1


@pytest.mark.unit
def test_analysis_node_preserves_state(
    set_llm_env: None,
    temp_output_dir: str,
    sample_data_profile: None,
    sample_analysis_intent: None,
    make_execution_plan: object,
) -> None:
    _ = set_llm_env

    valid_script = 'import sys; print(\'{"charts": [], "statistics": {}, "insights": ["test"]}\')'
    sandbox_result = SandboxResult(
        stdout='{"charts": [], "statistics": {}, "insights": ["test"]}',
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
        user_requirement="Analyze",
        data_profile=sample_data_profile,
        analysis_intent=sample_analysis_intent,
        execution_plan=make_execution_plan(),
    )

    with (
        patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.analysis.run_script", return_value=sandbox_result),
    ):
        new_state = analysis_node(state)

    assert new_state.get("error") is None
    assert new_state["analysis_result"]["parsed_output"]["insights"] == ["test"]


@pytest.mark.unit
def test_analysis_node_llm_error(set_llm_env: None, make_execution_plan: object) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API rate limit")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        execution_plan=make_execution_plan(),
    )

    with patch("src.agent.nodes.analysis.get_llm", return_value=mock_llm):
        new_state = analysis_node(state)

    assert "error" in new_state
    assert "API rate limit" in new_state["error"]


@pytest.mark.unit
def test_analysis_node_uses_cleaned_data_path(
    set_llm_env: None, temp_output_dir: str, make_execution_plan: object
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
    mock_response = MagicMock()
    mock_response.content = valid_script
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/original.csv",
        user_requirement="Analyze",
        execution_plan=make_execution_plan(),
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
