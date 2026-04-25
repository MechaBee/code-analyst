from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from code_analyst_contracts import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ConversationCreateRequest,
    ConversationCreateResponse,
    HealthResponse,
    QuestionRequest,
    QuestionResponse,
    WorkspaceImportRequest,
    WorkspaceImportResponse,
)
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from .config import settings
from .object_store import ObjectStore
from .question_orchestrator import QuestionOrchestrator
from .sandbox_supervisor_client import SandboxSupervisorClient
from .state_store import ConversationStateStore, RunStateStore, WorkspaceStateStore
from .workspace_imports import WorkspaceImportError, WorkspaceImportService

app = FastAPI(title="Code Analyst Control Plane", version="0.1.0")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class AppState:
    def __init__(self) -> None:
        self.object_store = ObjectStore(settings)
        self.workspace_store = WorkspaceStateStore(self.object_store)
        self.conversation_store = ConversationStateStore(self.object_store)
        self.run_store = RunStateStore(self.object_store)
        self.workspace_import_service = WorkspaceImportService(
            settings=settings,
            object_store=self.object_store,
        )
        self.question_orchestrator = QuestionOrchestrator(
            sandbox_client=SandboxSupervisorClient(settings.sandbox_supervisor_url),
            conversation_store=self.conversation_store,
            run_store=self.run_store,
            workspace_store=self.workspace_store,
        )


app.state.state = AppState()


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(name=settings.app_name)


@app.post("/v1/workspaces/imports/github", response_model=WorkspaceImportResponse)
async def create_workspace_import(
    request: WorkspaceImportRequest,
) -> WorkspaceImportResponse:
    try:
        artifacts = await run_in_threadpool(
            app.state.state.workspace_import_service.import_github_repo,
            request,
        )
    except WorkspaceImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="Workspace import failed due to an unexpected backend error.",
        ) from error

    await run_in_threadpool(
        app.state.state.workspace_store.register_snapshot,
        tenant_id=request.tenant_id,
        snapshot=artifacts.snapshot_ref,
    )
    return artifacts.response


@app.post("/v1/conversations", response_model=ConversationCreateResponse)
async def create_conversation(
    request: ConversationCreateRequest,
) -> ConversationCreateResponse:
    conversation_id = new_id("conv")
    await run_in_threadpool(
        app.state.state.conversation_store.create_conversation,
        conversation_id=conversation_id,
        request=request,
    )
    return ConversationCreateResponse(conversation_id=conversation_id)


@app.post(
    "/v1/conversations/{conversation_id}/questions",
    response_model=QuestionResponse,
)
async def ask_question(
    conversation_id: str,
    request: QuestionRequest,
) -> QuestionResponse:
    return await app.state.state.question_orchestrator.execute_question(
        conversation_id=conversation_id,
        request=request,
    )


@app.get("/v1/runs/{run_id}/events")
async def stream_run_events(run_id: str) -> StreamingResponse:
    run_events = await run_in_threadpool(app.state.state.run_store.list_events, run_id)
    if not run_events:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_stream() -> AsyncIterator[str]:
        for event in run_events:
            yield f"event: {event.type.value}\n"
            yield f"data: {event.model_dump_json()}\n\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post(
    "/v1/runs/{run_id}/approvals/{approval_id}",
    response_model=ApprovalDecisionResponse,
)
async def resolve_approval(
    run_id: str,
    approval_id: str,
    request: ApprovalDecisionRequest,
) -> ApprovalDecisionResponse:
    return ApprovalDecisionResponse(run_id=run_id, approval_id=approval_id)
