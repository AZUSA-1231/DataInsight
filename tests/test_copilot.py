from __future__ import annotations

import json
from collections.abc import Sequence

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from src.agent.copilot import (
    CopilotInvalidMessageError,
    CopilotToolBinding,
    CopilotTurnHandler,
    SkillSelection,
    build_turn_policy,
    parse_soft_command,
)
from src.agent.copilot_context import build_workspace_context
from src.agent.state import AgentState
from src.api.session import SessionStore


class _FakeBoundModel:
    def __init__(self, responses: Sequence[object]) -> None:
        self.responses = list(responses)
        self.messages: list[list[BaseMessage]] = []

    def invoke(self, messages: list[BaseMessage]) -> object:
        self.messages.append(list(messages))
        return self.responses.pop(0)


class _FakeLLM:
    def __init__(self, bound: _FakeBoundModel) -> None:
        self.bound = bound
        self.schemas: list[dict[str, object]] = []

    def bind_tools(self, schemas: list[dict[str, object]]) -> _FakeBoundModel:
        self.schemas = schemas
        return self.bound

    def invoke(self, messages: list[BaseMessage]) -> object:
        return self.bound.invoke(messages)


def _store(tmp_path) -> tuple[SessionStore, str]:
    store = SessionStore(tmp_path / "sessions")
    return store, store.create("initial requirement")


def _binding(name: str, handler) -> CopilotToolBinding:
    return CopilotToolBinding(
        name=name,
        schema={
            "type": "function",
            "function": {
                "name": name,
                "description": "test tool",
                "parameters": {"type": "object"},
            },
        },
        handler=handler,
    )


def test_soft_command_is_prompt_selection_only() -> None:
    assert parse_soft_command("/plan compare revenue by region").name == "plan"
    assert parse_soft_command("/plan compare revenue by region").arguments == (
        "compare revenue by region"
    )
    unknown = parse_soft_command("/unknown do something")
    assert unknown.name is None
    assert unknown.unknown_name == "unknown"


def test_run_and_rerun_skills_do_not_advertise_unbound_mutation_tools() -> None:
    run_policy = build_turn_policy(SkillSelection(name="run", arguments=""))
    rerun_policy = build_turn_policy(SkillSelection(name="rerun", arguments=""))

    assert run_policy.allowed_tool_names == {
        "inspect_column",
        "inspect_snapshot",
        "inspect_results",
    }
    assert rerun_policy.allowed_tool_names == run_policy.allowed_tool_names


def test_handler_rejects_message_removed_by_sanitization(tmp_path) -> None:
    store, session_id = _store(tmp_path)

    with pytest.raises(CopilotInvalidMessageError):
        CopilotTurnHandler(store, llm_factory=lambda: object()).handle(
            session_id, "``` ---"
        )


def test_normal_turn_persists_one_user_and_one_assistant(tmp_path) -> None:
    store, session_id = _store(tmp_path)
    bound = _FakeBoundModel([AIMessage(content="这是一个直接回答。")])
    llm = _FakeLLM(bound)

    result = CopilotTurnHandler(store, llm_factory=lambda: llm).handle(
        session_id, "请解释当前工作区"
    )

    assert result.status == "complete"
    assert result.message == "这是一个直接回答。"
    restored = SessionStore(tmp_path / "sessions").get(session_id)
    assert restored is not None
    assert restored.user_requirement == "initial requirement"
    assert restored.dialogue_history[-2:] == [
        {"role": "user", "content": "请解释当前工作区"},
        {"role": "assistant", "content": "这是一个直接回答。"},
    ]
    assert len(bound.messages) == 1
    assert "current_request" in str(bound.messages[0][1].content)


def test_tool_exchange_is_bounded_and_tool_messages_are_not_persisted(tmp_path) -> None:
    store, session_id = _store(tmp_path)
    bound = _FakeBoundModel(
        [
            AIMessage(
                content="先检查。",
                tool_calls=[
                    {
                        "name": "inspect_column",
                        "args": {"column_name": "orders.amount"},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="orders.amount 是数值列。"),
        ]
    )
    llm = _FakeLLM(bound)
    calls: list[dict[str, object]] = []

    def inspect(_state: AgentState, arguments: dict[str, object]) -> object:
        calls.append(arguments)
        return {"dtype": "float64", "private": "kept outside history"}

    result = CopilotTurnHandler(
        store,
        llm_factory=lambda: llm,
        tools=[_binding("inspect_column", inspect)],
    ).handle(session_id, "/inspect orders.amount")

    assert result.status == "complete"
    assert result.tool_rounds == 1
    assert calls == [{"column_name": "orders.amount"}]
    assert len(bound.messages) == 2
    assert any(isinstance(message, ToolMessage) for message in bound.messages[1])
    state = store.get(session_id)
    assert state is not None
    assert all(item["role"] != "tool" for item in state.dialogue_history)
    assert state.dialogue_history[-1]["content"] == "orders.amount 是数值列。"
    assert json.loads(bound.messages[0][1].content)["current_request"] == (
        "/inspect orders.amount"
    )


def test_tool_round_limit_stops_without_retry_loop(tmp_path) -> None:
    store, session_id = _store(tmp_path)
    bound = _FakeBoundModel(
        [
            AIMessage(
                content="检查一次。",
                tool_calls=[
                    {"name": "inspect_column", "args": {}, "id": "call_1"}
                ],
            ),
            AIMessage(
                content="还要再检查。",
                tool_calls=[
                    {"name": "inspect_column", "args": {}, "id": "call_2"}
                ],
            ),
        ]
    )
    llm = _FakeLLM(bound)
    result = CopilotTurnHandler(
        store,
        llm_factory=lambda: llm,
        tools=[_binding("inspect_column", lambda _state, _args: "ok")],
        max_tool_rounds=1,
        max_model_calls=3,
    ).handle(session_id, "检查一次")

    assert result.status == "incomplete"
    assert result.error == "maximum tool-call rounds reached"
    assert len(bound.messages) == 2
    assert len(result.tool_results) == 1


def test_context_does_not_expose_runtime_or_internal_values(tmp_path) -> None:
    store, session_id = _store(tmp_path)
    store.update(
        session_id,
        {
            "file_path": r"C:\secret\orders.csv",
            "unified_columns": ["orders.__di_row_id", "orders.amount"],
            "analysis_result": {
                "status": "complete",
                "unit_results": [
                    {
                        "unit_id": 1,
                        "status": "success",
                        "_result_df": object(),
                        "output_dir": r"C:\secret\output",
                    }
                ],
            },
        },
    )
    bound = _FakeBoundModel([AIMessage(content="收到。")])
    llm = _FakeLLM(bound)

    CopilotTurnHandler(store, llm_factory=lambda: llm).handle(session_id, "查看状态")
    content = str(bound.messages[0][1].content)
    assert "C:\\secret" not in content
    assert "_result_df" not in content
    assert "__di_row_id" not in content


def test_context_omits_unknown_objects_and_normalizes_non_finite_numbers(
    tmp_path,
) -> None:
    class _SecretValue:
        def __str__(self) -> str:
            return r"C:\secret\should-not-leak.txt"

    store, session_id = _store(tmp_path)
    state = store.get(session_id)
    assert state is not None
    state = state.model_copy(
        update={
            "analysis_result": {
                "status": "complete",
                "unit_results": [
                    {
                        "unit_id": 1,
                        "status": "success",
                        "statistics": {
                            "unknown": _SecretValue(),
                            "nan": float("nan"),
                            "positive_infinity": float("inf"),
                            "negative_infinity": float("-inf"),
                        },
                    }
                ],
            }
        }
    )

    context = build_workspace_context(state)
    serialized = json.dumps(context, ensure_ascii=False, allow_nan=False)

    assert r"C:\secret" not in serialized
    statistics = context["execution"]["unit_results"][0]["statistics"]
    assert statistics == {
        "unknown": "[unsupported value omitted]",
        "nan": None,
        "positive_infinity": None,
        "negative_infinity": None,
    }


def test_history_append_reloads_state_after_model_call(tmp_path) -> None:
    store, session_id = _store(tmp_path)

    class _HistoryMutatingModel:
        def invoke(self, _messages: list[BaseMessage]) -> AIMessage:
            store.update(
                session_id,
                {
                    "dialogue_history": [
                        {"role": "user", "content": "another request"},
                        {"role": "assistant", "content": "another response"},
                    ]
                },
            )
            return AIMessage(content="current response")

    result = CopilotTurnHandler(
        store,
        llm_factory=_HistoryMutatingModel,
    ).handle(session_id, "current request")

    assert result.status == "complete"
    state = store.get(session_id)
    assert state is not None
    assert state.dialogue_history == [
        {"role": "user", "content": "another request"},
        {"role": "assistant", "content": "another response"},
        {"role": "user", "content": "current request"},
        {"role": "assistant", "content": "current response"},
    ]


def test_provider_and_tool_errors_do_not_expose_exception_details(tmp_path) -> None:
    secret = r"C:\secret\provider-config.txt"
    store, session_id = _store(tmp_path)

    class _FailingModel:
        def invoke(self, _messages: list[BaseMessage]) -> object:
            raise RuntimeError(secret)

    provider_result = CopilotTurnHandler(
        store,
        llm_factory=_FailingModel,
    ).handle(session_id, "hello")

    assert provider_result.status == "error"
    assert provider_result.error == "copilot_call_failed"
    assert secret not in provider_result.model_dump_json()

    bound = _FakeBoundModel(
        [
            AIMessage(
                content="checking",
                tool_calls=[{"name": "inspect_column", "args": {}, "id": "call_1"}],
            )
        ]
    )

    def fail_tool(_state: AgentState, _arguments: dict[str, object]) -> object:
        raise RuntimeError(secret)

    tool_result = CopilotTurnHandler(
        store,
        llm_factory=lambda: _FakeLLM(bound),
        tools=[_binding("inspect_column", fail_tool)],
    ).handle(session_id, "/inspect amount")

    assert tool_result.status == "error"
    assert tool_result.error == "tool_call_failed"
    assert secret not in tool_result.model_dump_json()
