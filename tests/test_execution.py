from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.execution import (
    _build_code_gen_prompt,
    _build_react_fix_prompt,
    _extract_code_block,
    execution_node,
)
from src.agent.state import AgentState
from src.sandbox.executor import SandboxResult


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
def test_build_code_gen_prompt_structure() -> None:
    prompt = _build_code_gen_prompt(
        "## 分析执行计划\nClean data, run EDA.", "/tmp/data.csv", "/tmp/out"
    )

    assert "senior data engineer" in prompt.lower()
    assert "Agg" in prompt
    assert "font.sans-serif" in prompt
    assert "NO network calls" in prompt
    assert "try/except" in prompt or "try / except" in prompt
    assert "cleaned_shape" in prompt
    assert "## 分析执行计划" in prompt
    assert "/tmp/data.csv" in prompt
    assert "/tmp/out" in prompt


@pytest.mark.unit
def test_build_react_fix_prompt_includes_error() -> None:
    prompt = _build_react_fix_prompt(
        "Execution plan here.",
        "print(df.col)\n",
        "NameError: name 'df' is not defined",
        "/tmp/data.csv",
        "/tmp/out",
    )

    assert "debugging specialist" in prompt.lower()
    assert "NameError: name 'df' is not defined" in prompt
    assert "print(df.col)" in prompt
    assert "Execution plan here." in prompt
    assert "FIXED" in prompt


@pytest.mark.unit
def test_execution_node_missing_execution_plan() -> None:
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
    )

    new_state = execution_node(state)

    assert "error" in new_state
    assert "execution_plan" in new_state["error"]
    assert new_state["execution_result"]["retry_count"] == 3


@pytest.mark.unit
def test_execution_node_success_first_attempt(set_llm_env: None, temp_output_dir: str) -> None:
    _ = set_llm_env

    valid_script = 'import sys; print(\'{"cleaned_shape": {"rows": 100, "cols": 5}}\')'
    sandbox_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 100, "cols": 5}}',
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
        user_requirement="Analyze sales",
        execution_plan="## 分析执行计划\nClean data.",
    )

    with (
        patch("src.agent.nodes.execution.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.execution.run_script", return_value=sandbox_result),
    ):
        new_state = execution_node(state)

    assert new_state.get("error") is None
    assert "execution_result" in new_state
    result = new_state["execution_result"]
    assert result["retry_count"] == 0
    assert "parsed_output" in result
    assert result["parsed_output"]["cleaned_shape"]["rows"] == 100


@pytest.mark.unit
def test_execution_node_sandbox_error_triggers_retry(
    set_llm_env: None, temp_output_dir: str
) -> None:
    _ = set_llm_env

    sandbox_result = SandboxResult(
        stdout="",
        stderr="NameError: name 'df' is not defined",
        exit_code=1,
        timed_out=False,
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "print(df.column)\n"
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        execution_plan="## 分析执行计划\nUse column 'sales'.",
    )

    with (
        patch("src.agent.nodes.execution.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.execution.run_script", return_value=sandbox_result),
    ):
        new_state = execution_node(state)

    assert "error" in new_state
    assert "NameError" in new_state["error"]
    exec_result = new_state["execution_result"]
    assert exec_result["retry_count"] == 1
    assert len(exec_result["attempts"]) == 1
    assert exec_result["attempts"][0]["error"] == "NameError: name 'df' is not defined"


@pytest.mark.unit
def test_execution_node_react_retry_then_success(set_llm_env: None, temp_output_dir: str) -> None:
    """Simulate what the graph does: first call fails, second call (ReAct) succeeds."""
    _ = set_llm_env

    # --- First attempt: fails ---
    fail_result = SandboxResult(
        stdout="", stderr="KeyError: 'sales_col'", exit_code=1, timed_out=False
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "print(df['sales_col'])\n"
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        execution_plan="## 分析执行计划\nUse 'revenue' column.",
    )

    with (
        patch("src.agent.nodes.execution.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.execution.run_script", return_value=fail_result),
    ):
        state_dict = execution_node(state)

    assert "error" in state_dict
    assert state_dict["execution_result"]["retry_count"] == 1

    # Reconstruct state for second attempt
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze sales",
        execution_plan="## 分析执行计划\nUse 'revenue' column.",
        execution_result=state_dict["execution_result"],
    )

    # --- Second attempt: ReAct fix succeeds ---
    fix_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 50, "cols": 3}}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    mock_llm2 = MagicMock()
    mock_response2 = MagicMock()
    mock_response2.content = "print(df['revenue'])\n"
    mock_llm2.invoke.return_value = mock_response2

    with (
        patch("src.agent.nodes.execution.get_llm", return_value=mock_llm2),
        patch("src.agent.nodes.execution.run_script", return_value=fix_result),
    ):
        state_dict2 = execution_node(state)

    assert state_dict2.get("error") is None
    exec_result = state_dict2["execution_result"]
    assert exec_result["parsed_output"]["cleaned_shape"]["rows"] == 50
    assert len(exec_result["attempts"]) == 1  # prior failure recorded
    assert exec_result["retry_count"] == 1


@pytest.mark.unit
def test_execution_node_timeout_handling(set_llm_env: None, temp_output_dir: str) -> None:
    _ = set_llm_env

    timeout_result = SandboxResult(
        stdout="partial output...",
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
        user_requirement="Analyze sales",
        execution_plan="Plan here.",
    )

    with (
        patch("src.agent.nodes.execution.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.execution.run_script", return_value=timeout_result),
    ):
        new_state = execution_node(state)

    assert "error" in new_state
    assert "TIMEOUT" in new_state["error"]
    assert new_state["execution_result"]["retry_count"] == 1


@pytest.mark.unit
def test_execution_node_invalid_json_output(set_llm_env: None, temp_output_dir: str) -> None:
    _ = set_llm_env

    bad_result = SandboxResult(
        stdout="Here is some analysis text\nbut no valid JSON!",
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "print('not json')\n"
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        execution_plan="Plan.",
    )

    with (
        patch("src.agent.nodes.execution.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.execution.run_script", return_value=bad_result),
    ):
        new_state = execution_node(state)

    assert "error" in new_state
    assert "invalid json" in new_state["error"].lower()
    assert new_state["execution_result"]["retry_count"] == 1


@pytest.mark.unit
def test_execution_node_preserves_state(
    set_llm_env: None,
    temp_output_dir: str,
    sample_data_profile: object,
) -> None:
    _ = set_llm_env

    success_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 10, "cols": 2}}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "print('{}')\n"
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Why did sales drop?",
        data_profile=sample_data_profile,
        cleaning_insights="## 数据清洗建议\nExisting insights.",
        business_plan="## 业务分析蓝图\nExisting plan.",
        execution_plan="## 分析执行计划\nExecute this.",
    )

    with (
        patch("src.agent.nodes.execution.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.execution.run_script", return_value=success_result),
    ):
        new_state = execution_node(state)

    assert "execution_result" in new_state
    assert new_state["execution_result"]["parsed_output"]["cleaned_shape"]["rows"] == 10


@pytest.mark.unit
def test_execution_node_llm_error(set_llm_env: None) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API rate limit")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Analyze",
        execution_plan="Plan.",
    )

    with patch("src.agent.nodes.execution.get_llm", return_value=mock_llm):
        new_state = execution_node(state)

    assert "error" in new_state
    assert "API rate limit" in new_state["error"]
