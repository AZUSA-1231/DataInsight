from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.preprocessing import (
    _build_clean_code_prompt,
    _build_clean_react_fix_prompt,
    _extract_code_block,
    _serialize_preprocessing_steps,
    preprocessing_node,
)
from src.agent.state import AgentState, ExecutionPlan
from src.sandbox.executor import SandboxResult


def _make_plan(
    preprocessing_steps: list[dict] | None = None,
) -> ExecutionPlan:
    return ExecutionPlan(
        feasibility_map=[],
        model_selections=[],
        preprocessing_steps=(
            preprocessing_steps
            if preprocessing_steps is not None
            else [
                {
                    "step": 1,
                    "action": "drop_null_rows",
                    "target_columns": ["region"],
                    "urgency": "高优先",
                    "reason": "2% nulls in region column",
                }
            ]
        ),
        analysis_steps=[],
        alignment_notes="Test plan.",
    )


@pytest.mark.unit
def test_serialize_preprocessing_steps() -> None:
    plan = _make_plan()
    text = _serialize_preprocessing_steps(plan)
    assert "drop_null_rows" in text
    assert "region" in text


@pytest.mark.unit
def test_serialize_preprocessing_steps_fallback() -> None:
    assert _serialize_preprocessing_steps("not a plan") == "[]"


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
def test_build_clean_code_prompt_structure() -> None:
    prompt = _build_clean_code_prompt(_make_plan(), "/tmp/data.csv", "/tmp/out")

    assert "data cleaning specialist" in prompt.lower()
    assert "drop_null_rows" in prompt
    assert "NO network calls" in prompt
    assert "try/except" in prompt or "try / except" in prompt
    assert "cleaned_shape" in prompt
    assert "cleaned_data.csv" in prompt
    assert "/tmp/data.csv" in prompt
    assert "/tmp/out" in prompt


@pytest.mark.unit
def test_build_clean_react_fix_prompt_includes_error() -> None:
    prompt = _build_clean_react_fix_prompt(
        _make_plan(),
        "df.dropna()\n",
        "KeyError: 'region'",
        "/tmp/data.csv",
        "/tmp/out",
    )

    assert "debugging specialist" in prompt.lower()
    assert "KeyError: 'region'" in prompt
    assert "df.dropna()" in prompt
    assert "drop_null_rows" in prompt
    assert "FIXED" in prompt


@pytest.mark.unit
def test_preprocessing_node_missing_execution_plan() -> None:
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Clean data",
    )

    new_state = preprocessing_node(state)

    assert "error" in new_state
    assert "execution_plan" in new_state["error"]
    assert new_state["preprocessing_result"]["retry_count"] == 3


@pytest.mark.unit
def test_preprocessing_node_no_steps_skips(set_llm_env: None) -> None:
    _ = set_llm_env
    plan = _make_plan(preprocessing_steps=[])
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Clean data",
        execution_plan=plan,
    )

    new_state = preprocessing_node(state)

    assert new_state.get("error") is None
    result = new_state["preprocessing_result"]
    assert result["skipped"] is True
    assert result["cleaned_data_path"] == "/tmp/test.csv"
    assert result["cleaning_actions"] == []


@pytest.mark.unit
def test_preprocessing_node_success_first_attempt(set_llm_env: None, temp_output_dir: str) -> None:
    _ = set_llm_env

    valid_script = (
        "import sys; print('"
        '{"cleaned_shape": {"rows": 98, "cols": 5},'
        ' "cleaning_actions": ["dropped nulls"],'
        ' "cleaned_data_path": "/tmp/out/cleaned_data.csv"}'
        "')"
    )
    sandbox_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 98, "cols": 5}, '
        '"cleaning_actions": ["dropped nulls"], '
        '"cleaned_data_path": "/tmp/out/cleaned_data.csv"}',
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
        user_requirement="Clean sales data",
        execution_plan=_make_plan(),
    )

    with (
        patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.preprocessing.run_script", return_value=sandbox_result),
    ):
        new_state = preprocessing_node(state)

    assert new_state.get("error") is None
    assert "preprocessing_result" in new_state
    result = new_state["preprocessing_result"]
    assert result["retry_count"] == 0
    assert "parsed_output" in result
    assert result["parsed_output"]["cleaned_shape"]["rows"] == 98
    assert result["parsed_output"]["cleaning_actions"] == ["dropped nulls"]


@pytest.mark.unit
def test_preprocessing_node_sandbox_error_triggers_retry(
    set_llm_env: None, temp_output_dir: str
) -> None:
    _ = set_llm_env

    sandbox_result = SandboxResult(
        stdout="",
        stderr="KeyError: 'region'",
        exit_code=1,
        timed_out=False,
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "df.drop(columns=['region'])\n"
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Clean sales",
        execution_plan=_make_plan(),
    )

    with (
        patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.preprocessing.run_script", return_value=sandbox_result),
    ):
        new_state = preprocessing_node(state)

    assert "error" in new_state
    assert "KeyError" in new_state["error"]
    pre_result = new_state["preprocessing_result"]
    assert pre_result["retry_count"] == 1
    assert len(pre_result["attempts"]) == 1
    assert pre_result["attempts"][0]["error"] == "KeyError: 'region'"


@pytest.mark.unit
def test_preprocessing_node_react_retry_then_success(
    set_llm_env: None, temp_output_dir: str
) -> None:
    _ = set_llm_env

    fail_result = SandboxResult(
        stdout="", stderr="ValueError: cannot convert", exit_code=1, timed_out=False
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "pd.to_numeric(df['col'])\n"
    mock_llm.invoke.return_value = mock_response

    plan = _make_plan()
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Clean sales",
        execution_plan=plan,
    )

    with (
        patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.preprocessing.run_script", return_value=fail_result),
    ):
        state_dict = preprocessing_node(state)

    assert "error" in state_dict
    assert state_dict["preprocessing_result"]["retry_count"] == 1

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Clean sales",
        execution_plan=plan,
        preprocessing_result=state_dict["preprocessing_result"],
    )

    fix_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 95, "cols": 5}, '
        '"cleaning_actions": ["fixed types"], '
        '"cleaned_data_path": "/tmp/out/cleaned_data.csv"}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    mock_llm2 = MagicMock()
    mock_response2 = MagicMock()
    mock_response2.content = "pd.to_numeric(df['col'], errors='coerce')\n"
    mock_llm2.invoke.return_value = mock_response2

    with (
        patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_llm2),
        patch("src.agent.nodes.preprocessing.run_script", return_value=fix_result),
    ):
        state_dict2 = preprocessing_node(state)

    assert state_dict2.get("error") is None
    pre_result = state_dict2["preprocessing_result"]
    assert pre_result["parsed_output"]["cleaned_shape"]["rows"] == 95
    assert len(pre_result["attempts"]) == 1
    assert pre_result["retry_count"] == 1


@pytest.mark.unit
def test_preprocessing_node_timeout_handling(set_llm_env: None, temp_output_dir: str) -> None:
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
        user_requirement="Clean sales",
        execution_plan=_make_plan(),
    )

    with (
        patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.preprocessing.run_script", return_value=timeout_result),
    ):
        new_state = preprocessing_node(state)

    assert "error" in new_state
    assert "TIMEOUT" in new_state["error"]
    assert new_state["preprocessing_result"]["retry_count"] == 1


@pytest.mark.unit
def test_preprocessing_node_invalid_json_output(set_llm_env: None, temp_output_dir: str) -> None:
    _ = set_llm_env

    bad_result = SandboxResult(
        stdout="Cleaning done\nbut no JSON here!",
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
        user_requirement="Clean",
        execution_plan=_make_plan(),
    )

    with (
        patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.preprocessing.run_script", return_value=bad_result),
    ):
        new_state = preprocessing_node(state)

    assert "error" in new_state
    assert "invalid json" in new_state["error"].lower()
    assert new_state["preprocessing_result"]["retry_count"] == 1


@pytest.mark.unit
def test_preprocessing_node_llm_error(set_llm_env: None) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API rate limit")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Clean",
        execution_plan=_make_plan(),
    )

    with patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_llm):
        new_state = preprocessing_node(state)

    assert "error" in new_state
    assert "API rate limit" in new_state["error"]
