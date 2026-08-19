from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage


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

    def bind_tools(self, _schemas: list[dict[str, object]]) -> _FakeBoundModel:
        return self.bound


def test_project_history_create_and_rename_persist(api_client) -> None:
    created = api_client.post(
        "/api/sessions",
        json={"title": "  Revenue review  ", "user_requirement": "find trend"},
    )
    assert created.status_code == 200
    project_id = created.json()["session_id"]

    history = api_client.get("/api/sessions")
    assert history.status_code == 200
    project = next(
        item for item in history.json()["projects"] if item["project_id"] == project_id
    )
    assert project["title"] == "Revenue review"
    assert project["agent_chat_count"] == 1
    assert "upload_path" not in project

    renamed = api_client.patch(
        f"/api/sessions/{project_id}",
        json={"title": "Quarterly revenue"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Quarterly revenue"

    restored = api_client.get(f"/api/sessions/{project_id}")
    assert restored.status_code == 200
    assert restored.json()["title"] == "Quarterly revenue"
    assert restored.json()["project_id"] == project_id


def test_agent_threads_are_project_owned_and_durable(api_client, test_session) -> None:
    first = api_client.get(f"/api/sessions/{test_session}/agent-chats")
    assert first.status_code == 200
    default_thread = first.json()["threads"][0]

    created = api_client.post(
        f"/api/sessions/{test_session}/agent-chats",
        json={"title": "Second analysis"},
    )
    assert created.status_code == 200
    second_thread = created.json()
    assert second_thread["title"] == "Second analysis"
    assert second_thread["messages"] == []

    detail = api_client.get(
        f"/api/sessions/{test_session}/agent-chats/{default_thread['thread_id']}"
    )
    assert detail.status_code == 200
    assert detail.json()["messages"] == []

    other_project = api_client.post("/api/sessions", json={}).json()["session_id"]
    foreign = api_client.get(
        f"/api/sessions/{other_project}/agent-chats/{second_thread['thread_id']}"
    )
    assert foreign.status_code == 404

    store = api_client.app.state.sessions
    store._sessions.pop(test_session, None)
    restored = api_client.get(f"/api/sessions/{test_session}/agent-chats")
    assert restored.status_code == 200
    assert {item["thread_id"] for item in restored.json()["threads"]} == {
        default_thread["thread_id"],
        second_thread["thread_id"],
    }


def test_legacy_dialogue_history_migrates_once(api_client, test_session) -> None:
    store = api_client.app.state.sessions
    store.update(
        test_session,
        {
            "agent_threads": [],
            "dialogue_history": [
                {"role": "user", "content": "old question"},
                {"role": "tool", "content": "internal result"},
                {"role": "assistant", "content": "old answer"},
            ],
        },
    )

    response = api_client.get(f"/api/sessions/{test_session}/agent-chats")
    assert response.status_code == 200
    thread = response.json()["threads"][0]
    assert thread["title"] == "Imported chat"
    assert thread["message_count"] == 2

    state = store.get(test_session)
    assert state is not None
    assert state.dialogue_history == []
    assert [message.role for message in state.agent_threads[0].messages] == [
        "user",
        "assistant",
    ]

    store._sessions.pop(test_session, None)
    repeated = api_client.get(f"/api/sessions/{test_session}/agent-chats")
    assert repeated.status_code == 200
    assert repeated.json()["threads"][0]["message_count"] == 2


def test_copilot_uses_only_the_selected_thread(api_client, test_session) -> None:
    threads = api_client.get(f"/api/sessions/{test_session}/agent-chats").json()["threads"]
    first_id = threads[0]["thread_id"]
    second_id = api_client.post(
        f"/api/sessions/{test_session}/agent-chats", json={}
    ).json()["thread_id"]

    llm = _FakeLLM([AIMessage(content="first reply"), AIMessage(content="second reply")])
    api_client.app.state.copilot_llm_factory = lambda: llm

    first = api_client.post(
        f"/api/sessions/{test_session}/copilot",
        json={"thread_id": first_id, "message": "first question"},
    )
    second = api_client.post(
        f"/api/sessions/{test_session}/copilot",
        json={"thread_id": second_id, "message": "second question"},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    first_context = json.loads(llm.bound.messages[0][1].content)
    second_context = json.loads(llm.bound.messages[1][1].content)
    assert first_context["conversation"] == []
    assert second_context["conversation"] == []

    store = api_client.app.state.sessions
    state = store.get(test_session)
    assert state is not None
    by_id = {thread.thread_id: thread for thread in state.agent_threads}
    assert [message.content for message in by_id[first_id].messages] == [
        "first question",
        "first reply",
    ]
    assert [message.content for message in by_id[second_id].messages] == [
        "second question",
        "second reply",
    ]
    assert state.dialogue_history == []
