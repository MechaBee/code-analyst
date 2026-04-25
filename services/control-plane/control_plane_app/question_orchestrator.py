from __future__ import annotations

from uuid import uuid4

from code_analyst_contracts import (
    QuestionRequest,
    QuestionResponse,
    RunEvent,
    RunEventType,
    SandboxExecutionRequest,
    SandboxSessionCreateRequest,
    Status,
    WorkspaceSnapshotRef,
)
from fastapi import HTTPException

from .sandbox_supervisor_client import (
    SandboxSupervisorClient,
    SandboxSupervisorClientError,
)
from .state_store import ConversationStateStore, RunStateStore, WorkspaceStateStore

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class QuestionOrchestrator:
    def __init__(
        self,
        sandbox_client: SandboxSupervisorClient,
        *,
        conversation_store: ConversationStateStore,
        run_store: RunStateStore,
        workspace_store: WorkspaceStateStore,
    ) -> None:
        self._sandbox_client = sandbox_client
        self._conversation_store = conversation_store
        self._run_store = run_store
        self._workspace_store = workspace_store

    async def execute_question(
        self,
        *,
        conversation_id: str,
        request: QuestionRequest,
    ) -> QuestionResponse:
        conversation = self._conversation_store.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        snapshot = self._resolve_snapshot(
            tenant_id=conversation.tenant_id,
            workspace_id=conversation.workspace_id,
            request=request,
        )

        run_id = new_id("run")
        self._run_store.create_run(
            run_id=run_id,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation_id,
            snapshot_id=snapshot.snapshot_id,
            message=request.message,
        )
        self._conversation_store.update_head(
            conversation_id,
            latest_run_id=run_id,
            latest_snapshot_id=snapshot.snapshot_id,
        )
        self._conversation_store.append_event(
            conversation_id=conversation_id,
            event_type="user.message.created",
            run_id=run_id,
            payload={
                "message": request.message,
                "snapshot_id": snapshot.snapshot_id,
            },
        )
        self._append_run_event(
            run_id=run_id,
            event_type=RunEventType.RUN_STARTED,
            payload={"conversation_id": conversation_id},
        )
        self._append_run_event(
            run_id=run_id,
            event_type=RunEventType.RUN_PROGRESS,
            payload={
                "message": "Resolved workspace snapshot",
                "snapshot_id": snapshot.snapshot_id,
                "workspace_id": snapshot.workspace_id,
            },
        )

        resume_sandbox_id = (
            conversation.active_sandbox_id if request.resume_sandbox else None
        )

        try:
            session = await self._sandbox_client.create_session(
                request=SandboxSessionCreateRequest(
                    workspace=snapshot,
                    resume_from_sandbox_id=resume_sandbox_id,
                    environment_profile="local",
                )
            )
            self._run_store.update_run(run_id, sandbox_id=session.sandbox_id)
            self._conversation_store.update_head(
                conversation_id,
                active_sandbox_id=session.sandbox_id,
            )
            self._append_run_event(
                run_id=run_id,
                event_type=RunEventType.RUN_PROGRESS,
                payload={
                    "message": "Created sandbox session",
                    "sandbox_id": session.sandbox_id,
                },
            )

            execution_response = await self._sandbox_client.execute_session(
                sandbox_id=session.sandbox_id,
                request=SandboxExecutionRequest(
                    sandbox_id=session.sandbox_id,
                    conversation_id=conversation_id,
                    run_id=run_id,
                    message=request.message,
                    policy={
                        "resume_sandbox": request.resume_sandbox,
                        "workspace_snapshot_id": snapshot.snapshot_id,
                    },
                ),
            )
        except SandboxSupervisorClientError as error:
            self._append_run_event(
                run_id=run_id,
                event_type=RunEventType.RUN_FAILED,
                payload={"message": str(error)},
            )
            self._run_store.update_run(run_id, status=Status.FAILED)
            raise HTTPException(status_code=502, detail=str(error)) from error

        for citation in execution_response.answer.citations:
            self._append_run_event(
                run_id=run_id,
                event_type=RunEventType.CITATION_CREATED,
                payload=citation.model_dump(mode="json"),
            )
        self._append_run_event(
            run_id=run_id,
            event_type=RunEventType.RUN_COMPLETED,
            payload=execution_response.answer.model_dump(mode="json"),
        )
        self._run_store.update_run(
            run_id,
            answer=execution_response.answer,
            sandbox_id=session.sandbox_id,
            status=Status.COMPLETED,
        )
        self._conversation_store.append_event(
            conversation_id=conversation_id,
            event_type="assistant.message.created",
            run_id=run_id,
            payload=execution_response.answer.model_dump(mode="json"),
        )
        return QuestionResponse(
            run_id=run_id,
            status=Status.COMPLETED,
            events_url=f"/v1/runs/{run_id}/events",
        )

    def _resolve_snapshot(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        request: QuestionRequest,
    ) -> WorkspaceSnapshotRef:
        if request.workspace_snapshot_id:
            snapshot = self._workspace_store.get_snapshot(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                snapshot_id=request.workspace_snapshot_id,
            )
            if snapshot is None:
                raise HTTPException(status_code=404, detail="Workspace snapshot not found")
            return snapshot

        snapshot = self._workspace_store.get_latest_snapshot(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        if snapshot is None:
            raise HTTPException(
                status_code=404,
                detail="No workspace snapshot is available for the conversation workspace.",
            )
        return snapshot

    def _append_run_event(
        self,
        *,
        run_id: str,
        event_type: RunEventType,
        payload: dict,
    ) -> None:
        self._run_store.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                type=event_type,
                payload=payload,
            ),
        )
