from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agent.nodes.preprocessing import (
    _build_clean_code_prompt,
    _build_clean_react_fix_prompt,
    _serialize_cleaning_unit,
    preprocessing_node,
)
from src.agent.state import AgentState
from src.sandbox.executor import SandboxResult


@pytest.mark.unit
def test_serialize_cleaning_unit(sample_plan: object) -> None:
    text = _serialize_cleaning_unit(sample_plan.cleaning)
    assert "处理缺失值" in text
    assert "0值" in text
    assert "related_fields" in text


@pytest.mark.unit
def test_build_clean_code_prompt_structure(sample_plan: object) -> None:
    prompt = _build_clean_code_prompt(sample_plan.cleaning, "/tmp/data.csv", "/tmp/out")

    assert "data cleaning specialist" in prompt.lower()
    assert "处理缺失值" in prompt
    assert "NO network calls" in prompt
    assert "try/except" in prompt or "try / except" in prompt
    assert "cleaned_shape" in prompt
    assert "cleaned_data.csv" in prompt
    assert "/tmp/data.csv" in prompt
    assert "/tmp/out" in prompt


@pytest.mark.unit
def test_build_clean_react_fix_prompt_includes_error(sample_plan: object) -> None:
    prompt = _build_clean_react_fix_prompt(
        sample_plan.cleaning,
        "df.dropna()\n",
        "KeyError: 'region'",
        "/tmp/data.csv",
        "/tmp/out",
    )

    assert "debugging specialist" in prompt.lower()
    assert "KeyError: 'region'" in prompt
    assert "df.dropna()" in prompt
    assert "FIXED" in prompt
    assert "处理缺失值" in prompt


@pytest.mark.unit
def test_preprocessing_node_missing_plan() -> None:
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Clean data",
    )

    new_state = preprocessing_node(state)

    assert "error" in new_state
    assert "plan" in new_state["error"]
    assert new_state["preprocessing_result"]["retry_count"] == 3


@pytest.mark.unit
def test_preprocessing_node_success_first_attempt(
    set_llm_env: None, temp_output_dir: str, sample_plan: object
) -> None:
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
        plan=sample_plan,
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
    set_llm_env: None, temp_output_dir: str, sample_plan: object
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
        plan=sample_plan,
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
    set_llm_env: None, temp_output_dir: str, sample_plan: object
) -> None:
    _ = set_llm_env

    fail_result = SandboxResult(
        stdout="", stderr="ValueError: cannot convert", exit_code=1, timed_out=False
    )

    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "pd.to_numeric(df['col'])\n"
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Clean sales",
        plan=sample_plan,
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
        plan=sample_plan,
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
def test_preprocessing_node_timeout_handling(
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
    mock_response = MagicMock()
    mock_response.content = "while True: pass\n"
    mock_llm.invoke.return_value = mock_response

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Clean sales",
        plan=sample_plan,
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
def test_preprocessing_node_invalid_json_output(
    set_llm_env: None, temp_output_dir: str, sample_plan: object
) -> None:
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
        plan=sample_plan,
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
def test_preprocessing_node_llm_error(set_llm_env: None, sample_plan: object) -> None:
    _ = set_llm_env

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API rate limit")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Clean",
        plan=sample_plan,
    )

    with patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_llm):
        new_state = preprocessing_node(state)

    assert "error" in new_state
    assert "API rate limit" in new_state["error"]


# --- M4: Timeout Configuration Tests ---


@pytest.mark.unit
def test_preprocessing_node_uses_configured_timeout(
    set_llm_env: None, temp_output_dir: str, sample_plan: object, monkeypatch: object
) -> None:
    _ = set_llm_env

    monkeypatch.setenv("DATAINSIGHT_TIMEOUT_CLEANING", "180")
    # Force reload of the module-level constant by re-importing the module
    import importlib

    import src.agent.nodes.preprocessing as pp_mod
    importlib.reload(pp_mod)

    sandbox_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 98, "cols": 5}, '
        '"cleaning_actions": ["ok"], '
        '"cleaned_data_path": "/tmp/out/cleaned_data.csv"}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="print('{}')\n")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Clean",
        plan=sample_plan,
    )

    with (
        patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.preprocessing.run_script", return_value=sandbox_result) as mock_run,
    ):
        new_state = pp_mod.preprocessing_node(state)

    assert new_state.get("error") is None
    assert mock_run.call_args[1]["timeout_seconds"] == 180


@pytest.mark.unit
def test_preprocessing_node_timeout_env_fallback(
    set_llm_env: None, temp_output_dir: str, sample_plan: object, monkeypatch: object
) -> None:
    _ = set_llm_env

    monkeypatch.setenv("DATAINSIGHT_TIMEOUT_CLEANING", "not-a-number")
    import importlib

    import src.agent.nodes.preprocessing as pp_mod
    importlib.reload(pp_mod)

    sandbox_result = SandboxResult(
        stdout='{"cleaned_shape": {"rows": 98, "cols": 5}, '
        '"cleaning_actions": ["ok"], '
        '"cleaned_data_path": "/tmp/out/cleaned_data.csv"}',
        stderr="",
        exit_code=0,
        timed_out=False,
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="print('{}')\n")

    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Clean",
        plan=sample_plan,
    )

    with (
        patch("src.agent.nodes.preprocessing.get_llm", return_value=mock_llm),
        patch("src.agent.nodes.preprocessing.run_script", return_value=sandbox_result) as mock_run,
    ):
        new_state = pp_mod.preprocessing_node(state)

    assert new_state.get("error") is None
    # Should fall back to DEFAULT_TIMEOUT (120)
    from src.sandbox.executor import DEFAULT_TIMEOUT
    assert mock_run.call_args[1]["timeout_seconds"] == DEFAULT_TIMEOUT
