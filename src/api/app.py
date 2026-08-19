from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import (
    agent_chats,
    copilot,
    dashboard,
    data,
    dialogue,
    execution,
    report,
    workspace,
    workspace_layout,
)
from src.api.schemas import (
    ProjectRenameRequest,
    ProjectsResponse,
    ProjectSummaryResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionStateResponse,
)
from src.api.session import IncompatibleSessionError, SessionStore, build_project_summary


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.sessions = SessionStore()
    Path("data/uploads").mkdir(parents=True, exist_ok=True)
    Path("data/output").mkdir(parents=True, exist_ok=True)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="DataInsight API",
        version="0.1.0",
        description="Frontend API for DataInsight analysis agent",
        lifespan=lifespan,
    )

    @app.exception_handler(IncompatibleSessionError)
    async def incompatible_session_handler(
        request: Request, exc: IncompatibleSessionError
    ) -> JSONResponse:
        """Return one stable response for every route touching an old Session."""
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "INCOMPATIBLE_SESSION_SCHEMA",
                    "message": str(exc),
                }
            },
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/sessions", response_model=ProjectsResponse, tags=["sessions"])
    async def list_projects(request: Request) -> ProjectsResponse:
        store: SessionStore = request.app.state.sessions
        summaries = store.list_summaries()
        return ProjectsResponse(
            projects=[ProjectSummaryResponse(**summary) for summary in summaries]
        )

    @app.post("/api/sessions", response_model=SessionCreateResponse, tags=["sessions"])
    async def create_session(
        body: SessionCreateRequest, request: Request
    ) -> SessionCreateResponse:
        store: SessionStore = request.app.state.sessions
        try:
            sid = store.create(user_requirement=body.user_requirement, title=body.title)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return SessionCreateResponse(session_id=sid)

    @app.get(
        "/api/sessions/{session_id}",
        response_model=SessionStateResponse,
        tags=["sessions"],
    )
    async def get_session(
        session_id: str, request: Request
    ) -> SessionStateResponse:
        store: SessionStore = request.app.state.sessions
        try:
            state = store.get(session_id)
        except IncompatibleSessionError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "INCOMPATIBLE_SESSION_SCHEMA", "message": str(exc)},
            ) from exc
        if state is None:
            raise HTTPException(404, "Session not found")
        summary = build_project_summary(session_id, state)
        return SessionStateResponse(
            session_id=session_id,
            project_id=session_id,
            schema_version=state.schema_version,
            title=str(summary["title"]),
            created_at=state.created_at,
            has_data=bool(state.data_sources) or state.data_profile is not None,
            has_intent=state.analysis_intent is not None,
            has_plan=state.plan is not None,
            has_results=state.analysis_result is not None,
            has_report=state.final_report is not None,
            agent_chat_count=summary["agent_chat_count"],
            status=summary["status"],
            error=state.error,
            persisted_at=state.persisted_at,
        )

    @app.patch(
        "/api/sessions/{session_id}",
        response_model=ProjectSummaryResponse,
        tags=["sessions"],
    )
    async def rename_project(
        session_id: str,
        body: ProjectRenameRequest,
        request: Request,
    ) -> ProjectSummaryResponse:
        store: SessionStore = request.app.state.sessions
        if store.get(session_id) is None:
            raise HTTPException(404, "Project not found")
        try:
            state = store.rename(session_id, body.title)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ProjectSummaryResponse(**build_project_summary(session_id, state))

    @app.delete("/api/sessions/{session_id}", tags=["sessions"])
    async def delete_session(
        session_id: str, request: Request
    ) -> dict[str, str]:
        store: SessionStore = request.app.state.sessions
        if not store.delete(session_id):
            raise HTTPException(404, "Session not found")
        return {"message": f"Session {session_id} deleted"}

    @app.get("/projects/{project_id}", include_in_schema=False)
    async def serve_project_route(project_id: str) -> FileResponse:
        """Serve the SPA entry for a direct reload of a Project URL."""

        del project_id  # The React client resolves ownership through the API.
        index_path = Path("static/index.html")
        if not index_path.is_file():
            raise HTTPException(status_code=503, detail="Frontend build is unavailable")
        return FileResponse(index_path)

    app.include_router(agent_chats.router)
    app.include_router(data.router)
    app.include_router(workspace.router)
    app.include_router(workspace_layout.router)
    app.include_router(copilot.router)
    app.include_router(dialogue.router)
    app.include_router(execution.router)
    app.include_router(dashboard.router)
    app.include_router(report.router)

    # Mount static frontend AFTER all API routes (order matters — otherwise static shadows API)
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

    return app


app = create_app()
