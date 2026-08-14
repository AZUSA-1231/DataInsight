from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


class _FakeBoundModel:
    def __init__(self, responses: Sequence[object]) -> None:
        self.responses = list(responses)
        self.messages: list[list[BaseMessage]] = []

    def invoke(self, messages: list[BaseMessage]) -> object:
        self.messages.append(list(messages))
        return self.responses.pop(0)


class _FakeLLM:
    def __init__(self, responses: Sequence[object]) -> None:
        self.bound = _FakeBoundModel(responses)
        self.schemas: list[dict[str, object]] = []

    def bind_tools(self, schemas: list[dict[str, object]]) -> _FakeBoundModel:
        self.schemas = schemas
        return self.bound


def test_copilot_endpoint_uses_bounded_handler_and_persists_history(
    api_client,
    test_session,
) -> None:
    llm = _FakeLLM([AIMessage(content="这是 Copilot 的回答。")])
    api_client.app.state.copilot_llm_factory = lambda: llm

    response = api_client.post(
        f"/api/sessions/{test_session}/copilot",
        json={"message": "请解释当前工作区"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["message"] == "这是 Copilot 的回答。"
    assert {schema["function"]["name"] for schema in llm.schemas} == {
        "inspect_column",
        "inspect_snapshot",
        "inspect_results",
        "plan_edit",
    }
    state = api_client.app.state.sessions.get(test_session)
    assert state is not None
    assert state.dialogue_history[-2:] == [
        {"role": "user", "content": "请解释当前工作区"},
        {"role": "assistant", "content": "这是 Copilot 的回答。"},
    ]


def test_copilot_endpoint_supports_soft_inspect_with_tool_result(
    api_client,
    test_session,
) -> None:
    llm = _FakeLLM(
        [
            AIMessage(
                content="我先检查一下。",
                tool_calls=[
                    {
                        "name": "inspect_results",
                        "args": {},
                        "id": "call_results",
                    }
                ],
            ),
            AIMessage(content="当前还没有执行结果。"),
        ]
    )
    api_client.app.state.copilot_llm_factory = lambda: llm

    response = api_client.post(
        f"/api/sessions/{test_session}/copilot",
        json={"message": "/inspect 当前执行结果"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["skill"] == "inspect"
    assert body["tool_rounds"] == 1
    assert body["tool_results"][0]["name"] == "inspect_results"
    assert len(llm.schemas) == 3
    assert all(isinstance(message, ToolMessage) for message in llm.bound.messages[1][3:])


def test_copilot_endpoint_returns_404_for_missing_session(api_client) -> None:
    response = api_client.post(
        "/api/sessions/00000000000000000000000000000000/copilot",
        json={"message": "hello"},
    )
    assert response.status_code == 404


def test_copilot_endpoint_rejects_empty_message(api_client, test_session) -> None:
    response = api_client.post(
        f"/api/sessions/{test_session}/copilot",
        json={"message": ""},
    )
    assert response.status_code == 422


def test_copilot_endpoint_rejects_whitespace_only_message(
    api_client,
    test_session,
) -> None:
    response = api_client.post(
        f"/api/sessions/{test_session}/copilot",
        json={"message": "   \t\n"},
    )
    assert response.status_code == 422


def test_copilot_endpoint_rejects_message_removed_by_sanitization(
    api_client,
    test_session,
) -> None:
    response = api_client.post(
        f"/api/sessions/{test_session}/copilot",
        json={"message": "``` ---"},
    )
    assert response.status_code == 422
