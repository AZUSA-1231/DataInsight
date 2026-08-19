"""Project-owned Agent Thread resources."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, HTTPException, Request

from src.agent.state import AgentChatThread
from src.api.schemas import (
    AgentChatMessageResponse,
    AgentThreadCreateRequest,
    AgentThreadResponse,
    AgentThreadsResponse,
    AgentThreadSummaryResponse,
)
from src.api.session import SessionStore

router = APIRouter(
    prefix="/api/sessions/{project_id}/agent-chats",
    tags=["agent-chats"],
)


def _get_store(request: Request) -> SessionStore:
    return cast(SessionStore, request.app.state.sessions)


def _require_project(store: SessionStore, project_id: str) -> None:
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")


def _thread_summary(thread: AgentChatThread) -> AgentThreadSummaryResponse:
    preview = thread.messages[-1].content[:160] if thread.messages else None
    return AgentThreadSummaryResponse(
        thread_id=thread.thread_id,
        title=thread.title,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        message_count=len(thread.messages),
        preview=preview,
    )


def _thread_response(thread: AgentChatThread) -> AgentThreadResponse:
    summary = _thread_summary(thread)
    return AgentThreadResponse(
        **summary.model_dump(),
        messages=[AgentChatMessageResponse.from_message(message) for message in thread.messages],
    )


@router.get("", response_model=AgentThreadsResponse)
async def list_agent_chats(
    project_id: str,
    request: Request,
) -> AgentThreadsResponse:
    store = _get_store(request)
    _require_project(store, project_id)
    threads = store.list_agent_threads(project_id)
    return AgentThreadsResponse(threads=[_thread_summary(thread) for thread in threads])


@router.post("", response_model=AgentThreadResponse)
async def create_agent_chat(
    project_id: str,
    body: AgentThreadCreateRequest,
    request: Request,
) -> AgentThreadResponse:
    store = _get_store(request)
    _require_project(store, project_id)
    try:
        thread = store.create_agent_thread(project_id, title=body.title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _thread_response(thread)


@router.get("/{thread_id}", response_model=AgentThreadResponse)
async def get_agent_chat(
    project_id: str,
    thread_id: str,
    request: Request,
) -> AgentThreadResponse:
    store = _get_store(request)
    _require_project(store, project_id)
    thread = store.get_agent_thread(project_id, thread_id)
    if thread is None:
        # This intentionally does not reveal whether the ID belongs to a
        # different Project.
        raise HTTPException(status_code=404, detail="Agent Thread not found")
    return _thread_response(thread)
