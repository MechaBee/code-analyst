from __future__ import annotations

import logging
from uuid import uuid4

from code_analyst_contracts import (
    ApprovalDecisionResponse,
    ApprovalState,
    Checkout,
    QuestionRequest,
    QuestionResponse,
    RunEvent,
    RunEventType,
    SandboxDisposeRequest,
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
from .state_store import (
    ApprovalStateStore,
    ConversationHead,
    ConversationStateStore,
    RunState,
    RunStateStore,
    WorkspaceStateStore,
)


# Avoid circular import at import time; app_state_store is injected via __init__


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


logger = logging.getLogger(__name__)


class QuestionOrchestrator:
    def __init__(
        self,
        sandbox_client: SandboxSupervisorClient,
        *,
        conversation_store: ConversationStateStore,
        run_store: RunStateStore,
        workspace_store: WorkspaceStateStore,
        approval_store: ApprovalStateStore,
        app_state_store: "AppStateStore",
    ) -> None:
        self._sandbox_client = sandbox_client
        self._conversation_store = conversation_store
        self._run_store = run_store
        self._workspace_store = workspace_store
        self._approval_store = approval_store
        self._app_state_store = app_state_store

    async def execute_question(
        self,
        *,
        conversation_id: str,
        request: QuestionRequest,
    ) -> QuestionResponse:
        conversation, snapshot, run_id = self._setup_run(
            conversation_id=conversation_id,
            request=request,
        )

        if request.approval_policy == "required":
            return self._require_approval(
                run_id=run_id,
                conversation_id=conversation_id,
                snapshot=snapshot,
                request=request,
            )

        await self._execute_run_body(
            run_id=run_id,
            conversation=conversation,
            snapshot=snapshot,
            request=request,
        )

        run_state = self._run_store.get_run(run_id)
        assert run_state is not None
        return QuestionResponse(
            run_id=run_id,
            status=run_state.status,
            events_url=f"/v1/runs/{run_id}/events",
        )

    async def resume_run_after_approval(
        self,
        *,
        run_id: str,
        decision: str,
        reason: str | None = None,
    ) -> ApprovalDecisionResponse:
        run_state = self._run_store.get_run(run_id)
        if run_state is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if run_state.status != Status.PENDING_APPROVAL:
            raise HTTPException(
                status_code=409,
                detail=f"Run status is {run_state.status.value}, not pending approval.",
            )
        if run_state.pending_approval_id is None:
            raise HTTPException(
                status_code=500,
                detail="Run is pending approval but has no approval ID.",
            )

        self._approval_store.resolve_approval(
            run_state.pending_approval_id,
            decision=decision,
            reason=reason,
        )

        if decision != "approve":
            self._append_run_event(
                run_id=run_id,
                event_type=RunEventType.RUN_FAILED,
                payload={
                    "message": f"Approval denied: {reason or 'No reason provided'}",
                    "decision": decision,
                },
            )
            self._run_store.update_run(
                run_id,
                status=Status.FAILED,
                pending_approval_id=None,
            )
            return ApprovalDecisionResponse(
                run_id=run_id,
                approval_id=run_state.pending_approval_id,
                status=Status.FAILED,
            )

        conversation = self._conversation_store.get_conversation(
            run_state.conversation_id
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        snapshot = self._resolve_snapshot(
            conversation=conversation,
            request=QuestionRequest(
                message=run_state.message,
                resume_sandbox=run_state.resume_sandbox,
            ),
        )
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Workspace snapshot not found")

        await self._execute_run_body(
            run_id=run_id,
            conversation=conversation,
            snapshot=snapshot,
            request=QuestionRequest(
                message=run_state.message,
                resume_sandbox=run_state.resume_sandbox,
            ),
        )

        updated_run = self._run_store.get_run(run_id)
        assert updated_run is not None
        return ApprovalDecisionResponse(
            run_id=run_id,
            approval_id=run_state.pending_approval_id,
            status=updated_run.status,
        )

    def _setup_run(
        self,
        *,
        conversation_id: str,
        request: QuestionRequest,
    ) -> tuple[ConversationHead, WorkspaceSnapshotRef, str]:
        conversation = self._conversation_store.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        snapshot = self._resolve_snapshot(
            conversation=conversation,
            request=request,
        )

        run_id = new_id("run")
        self._run_store.create_run(
            run_id=run_id,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation_id,
            snapshot_id=snapshot.snapshot_id,
            message=request.message,
            resume_sandbox=request.resume_sandbox,
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
        return conversation, snapshot, run_id

    def _require_approval(
        self,
        *,
        run_id: str,
        conversation_id: str,
        snapshot: WorkspaceSnapshotRef,
        request: QuestionRequest,
    ) -> QuestionResponse:
        approval_id = new_id("apr")
        self._approval_store.create_approval(
            approval_id=approval_id,
            run_id=run_id,
        )
        self._run_store.update_run(
            run_id,
            status=Status.PENDING_APPROVAL,
            pending_approval_id=approval_id,
        )
        self._append_run_event(
            run_id=run_id,
            event_type=RunEventType.APPROVAL_REQUIRED,
            payload={
                "approval_id": approval_id,
                "message": request.message,
                "snapshot_id": snapshot.snapshot_id,
            },
        )
        return QuestionResponse(
            run_id=run_id,
            status=Status.PENDING_APPROVAL,
            events_url=f"/v1/runs/{run_id}/events",
        )

    async def _execute_run_body(
        self,
        *,
        run_id: str,
        conversation: ConversationHead,
        snapshot: WorkspaceSnapshotRef,
        request: QuestionRequest,
    ) -> None:
        resume_sandbox_id = (
            conversation.active_sandbox_id if request.resume_sandbox else None
        )

        session = None
        stage = "create_session"
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
                conversation.conversation_id,
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

            stage = "execute_session"
            execution_response = await self._sandbox_client.execute_session(
                sandbox_id=session.sandbox_id,
                request=SandboxExecutionRequest(
                    sandbox_id=session.sandbox_id,
                    conversation_id=conversation.conversation_id,
                    run_id=run_id,
                    message=request.message,
                    policy={
                        "resume_sandbox": request.resume_sandbox,
                        "workspace_snapshot_id": snapshot.snapshot_id,
                    },
                ),
            )
        except SandboxSupervisorClientError as error:
            logger.exception(
                "Sandbox interaction failed: run_id=%s conversation_id=%s snapshot_id=%s sandbox_id=%s stage=%s",
                run_id,
                conversation.conversation_id,
                snapshot.snapshot_id,
                session.sandbox_id if session is not None else None,
                stage,
            )
            self._append_run_event(
                run_id=run_id,
                event_type=RunEventType.RUN_FAILED,
                payload={"message": str(error)},
            )
            self._run_store.update_run(run_id, status=Status.FAILED)
            raise HTTPException(status_code=502, detail=str(error)) from error
        finally:
            if session is not None and not request.resume_sandbox:
                try:
                    await self._sandbox_client.dispose_session(
                        sandbox_id=session.sandbox_id,
                        request=SandboxDisposeRequest(persist_session_state=False),
                    )
                except SandboxSupervisorClientError:
                    pass

        try:
            stage = "persist_answer"
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
                pending_approval_id=None,
            )
            self._conversation_store.append_event(
                conversation_id=conversation.conversation_id,
                event_type="assistant.message.created",
                run_id=run_id,
                payload=execution_response.answer.model_dump(mode="json"),
            )
        except Exception as error:
            logger.exception(
                "Question run post-processing failed: run_id=%s conversation_id=%s snapshot_id=%s sandbox_id=%s stage=%s citation_count=%s followup_count=%s",
                run_id,
                conversation.conversation_id,
                snapshot.snapshot_id,
                session.sandbox_id if session is not None else None,
                stage,
                len(execution_response.answer.citations),
                len(execution_response.answer.followups),
            )
            try:
                self._append_run_event(
                    run_id=run_id,
                    event_type=RunEventType.RUN_FAILED,
                    payload={"message": f"Post-processing failed: {error}"},
                )
            except Exception:
                logger.exception(
                    "Failed to record run failure event: run_id=%s conversation_id=%s",
                    run_id,
                    conversation.conversation_id,
                )
            try:
                self._run_store.update_run(run_id, status=Status.FAILED)
            except Exception:
                logger.exception(
                    "Failed to mark run as failed after post-processing error: run_id=%s conversation_id=%s",
                    run_id,
                    conversation.conversation_id,
                )
            raise

    def _resolve_snapshot(
        self,
        *,
        conversation: ConversationHead,
        request: QuestionRequest,
    ) -> WorkspaceSnapshotRef:
        if conversation.checkout_id:
            checkout = self._app_state_store.get_checkout(
                conversation.tenant_id, conversation.checkout_id
            )
            if checkout is None:
                raise HTTPException(
                    status_code=404,
                    detail="Checkout not found for conversation",
                )
            snapshot_id = request.workspace_snapshot_id or checkout.snapshot_id
            snapshot = self._workspace_store.get_snapshot(
                tenant_id=conversation.tenant_id,
                workspace_id=checkout.workspace_id,
                snapshot_id=snapshot_id,
            )
            if snapshot is None:
                raise HTTPException(status_code=404, detail="Workspace snapshot not found")
            return snapshot

        if request.workspace_snapshot_id:
            snapshot = self._workspace_store.get_snapshot(
                tenant_id=conversation.tenant_id,
                workspace_id=conversation.workspace_id,
                snapshot_id=request.workspace_snapshot_id,
            )
            if snapshot is None:
                raise HTTPException(status_code=404, detail="Workspace snapshot not found")
            return snapshot

        snapshot = self._workspace_store.get_latest_snapshot(
            tenant_id=conversation.tenant_id,
            workspace_id=conversation.workspace_id,
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
