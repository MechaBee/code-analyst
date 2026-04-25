from __future__ import annotations

from dataclasses import dataclass

from code_analyst_contracts import (
    HealthResponse,
    SandboxDisposeRequest,
    SandboxDisposeResponse,
    SandboxExecutionRequest,
    SandboxExecutionResponse,
    SandboxSessionCreateRequest,
    SandboxSessionRef,
)
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool

from .analysis_adapter import build_analysis_adapter
from .config import settings
from .object_store import ObjectStore
from .workspace_materializer import (
    WorkspaceMaterializationError,
    WorkspaceMaterializer,
)

app = FastAPI(title="Code Analyst Sandbox Supervisor", version="0.1.0")


@dataclass(slots=True)
class SessionRecord:
    session: SandboxSessionRef
    session_dir: str
    workspace_root: str
    file_count: int
    top_level_entries: list[str]


class AppState:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}
        self.materializer = WorkspaceMaterializer(
            settings=settings,
            object_store=ObjectStore(settings),
        )
        self.analysis_adapter = build_analysis_adapter(settings)


app.state.state = AppState()


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(name=settings.app_name)


@app.post("/v1/sandboxes/sessions", response_model=SandboxSessionRef)
async def create_session(
    request: SandboxSessionCreateRequest,
) -> SandboxSessionRef:
    try:
        materialized = await run_in_threadpool(
            app.state.state.materializer.create_or_resume,
            request,
        )
    except WorkspaceMaterializationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="Sandbox session creation failed during workspace materialization.",
        ) from error

    record = SessionRecord(
        session=materialized.session,
        session_dir=str(materialized.session_dir),
        workspace_root=str(materialized.workspace_root),
        file_count=materialized.manifest.file_count,
        top_level_entries=materialized.manifest.top_level_entries,
    )
    app.state.state.sessions[materialized.session.sandbox_id] = record
    return materialized.session


@app.post(
    "/v1/sandboxes/{sandbox_id}/execute",
    response_model=SandboxExecutionResponse,
)
async def execute_session(
    sandbox_id: str,
    request: SandboxExecutionRequest,
) -> SandboxExecutionResponse:
    record = app.state.state.sessions.get(sandbox_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Sandbox session not found")

    try:
        answer = await app.state.state.analysis_adapter.analyze(
            workspace_root=record.workspace_root,
            snapshot_id=record.session.snapshot_id,
            question=request.message,
            top_level_entries=record.top_level_entries,
        )
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="Sandbox execution failed during analysis.",
        ) from error

    return SandboxExecutionResponse(
        sandbox_id=sandbox_id,
        run_id=request.run_id,
        answer=answer,
    )


@app.delete("/v1/sandboxes/{sandbox_id}", response_model=SandboxDisposeResponse)
async def dispose_session(
    sandbox_id: str,
    request: SandboxDisposeRequest,
) -> SandboxDisposeResponse:
    record = app.state.state.sessions.pop(sandbox_id, None)
    if record is None:
        raise HTTPException(status_code=404, detail="Sandbox session not found")
    await run_in_threadpool(
        app.state.state.materializer.dispose,
        record.session_dir,
    )
    return SandboxDisposeResponse(sandbox_id=sandbox_id)
