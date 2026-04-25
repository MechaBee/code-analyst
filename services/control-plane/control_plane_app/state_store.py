from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from code_analyst_contracts import (
    AnswerEnvelope,
    ConversationCreateRequest,
    ConversationEvent,
    RunEvent,
    RunEventType,
    Status,
    WorkspaceSnapshotRef,
)
from pydantic import BaseModel, Field

from .object_store import ObjectStore, ObjectStoreKeyNotFound


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkspaceHead(BaseModel):
    tenant_id: str
    workspace_id: str
    latest_snapshot: WorkspaceSnapshotRef
    updated_at: datetime = Field(default_factory=utc_now)


class ConversationIndexEntry(BaseModel):
    conversation_id: str
    tenant_id: str


class RunIndexEntry(BaseModel):
    run_id: str
    tenant_id: str
    conversation_id: str


class ConversationHead(BaseModel):
    conversation_id: str
    tenant_id: str
    workspace_id: str
    title: str | None = None
    status: str = "OPEN"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_event_sequence: int = 0
    latest_run_id: str | None = None
    active_sandbox_id: str | None = None
    latest_snapshot_id: str | None = None


class RunState(BaseModel):
    run_id: str
    tenant_id: str
    conversation_id: str
    snapshot_id: str
    message: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    sandbox_id: str | None = None
    status: Status = Status.STARTED
    event_count: int = 0
    answer: AnswerEnvelope | None = None


class WorkspaceStateStore:
    def __init__(self, object_store: ObjectStore) -> None:
        self._object_store = object_store

    def register_snapshot(
        self,
        *,
        tenant_id: str,
        snapshot: WorkspaceSnapshotRef,
    ) -> None:
        self._object_store.upload_json(
            self._snapshot_ref_key(
                tenant_id=tenant_id,
                workspace_id=snapshot.workspace_id,
                snapshot_id=snapshot.snapshot_id,
            ),
            snapshot.model_dump(mode="json"),
        )
        head = WorkspaceHead(
            tenant_id=tenant_id,
            workspace_id=snapshot.workspace_id,
            latest_snapshot=snapshot,
        )
        self._object_store.upload_json(
            self._workspace_head_key(tenant_id=tenant_id, workspace_id=snapshot.workspace_id),
            head.model_dump(mode="json"),
        )

    def get_latest_snapshot(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
    ) -> WorkspaceSnapshotRef | None:
        try:
            payload = self._object_store.download_json(
                self._workspace_head_key(tenant_id=tenant_id, workspace_id=workspace_id)
            )
        except ObjectStoreKeyNotFound:
            return None
        return WorkspaceHead.model_validate(payload).latest_snapshot

    def get_snapshot(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        snapshot_id: str,
    ) -> WorkspaceSnapshotRef | None:
        try:
            payload = self._object_store.download_json(
                self._snapshot_ref_key(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    snapshot_id=snapshot_id,
                )
            )
        except ObjectStoreKeyNotFound:
            return None
        return WorkspaceSnapshotRef.model_validate(payload)

    def _workspace_head_key(self, *, tenant_id: str, workspace_id: str) -> str:
        return f"tenants/{tenant_id}/workspaces/{workspace_id}/head.json"

    def _snapshot_ref_key(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        snapshot_id: str,
    ) -> str:
        return (
            f"tenants/{tenant_id}/workspaces/{workspace_id}/snapshots/"
            f"{snapshot_id}/snapshot-ref.json"
        )


class ConversationStateStore:
    def __init__(self, object_store: ObjectStore) -> None:
        self._object_store = object_store

    def create_conversation(
        self,
        *,
        conversation_id: str,
        request: ConversationCreateRequest,
    ) -> ConversationHead:
        head = ConversationHead(
            conversation_id=conversation_id,
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            title=request.title,
        )
        self._write_head(head)
        self._object_store.upload_json(
            self._conversation_index_key(conversation_id),
            ConversationIndexEntry(
                conversation_id=conversation_id,
                tenant_id=request.tenant_id,
            ).model_dump(mode="json"),
        )
        return head

    def get_conversation(self, conversation_id: str) -> ConversationHead | None:
        index = self._get_conversation_index(conversation_id)
        if index is None:
            return None
        try:
            payload = self._object_store.download_json(
                self._conversation_head_key(
                    tenant_id=index.tenant_id,
                    conversation_id=conversation_id,
                )
            )
        except ObjectStoreKeyNotFound:
            return None
        return ConversationHead.model_validate(payload)

    def append_event(
        self,
        *,
        conversation_id: str,
        event_type: str,
        payload: dict[str, Any],
        run_id: str | None = None,
    ) -> ConversationEvent:
        head = self.get_conversation(conversation_id)
        if head is None:
            raise KeyError(f"Conversation {conversation_id} not found")

        sequence = head.last_event_sequence + 1
        event = ConversationEvent(
            event_id=f"evt_{conversation_id}_{sequence:06d}",
            conversation_id=conversation_id,
            run_id=run_id,
            sequence=sequence,
            type=event_type,
            payload=payload,
        )
        self._object_store.upload_json(
            self._conversation_event_key(
                tenant_id=head.tenant_id,
                conversation_id=conversation_id,
                sequence=sequence,
            ),
            event.model_dump(mode="json"),
        )
        updated_head = head.model_copy(
            update={
                "last_event_sequence": sequence,
                "updated_at": utc_now(),
            }
        )
        self._write_head(updated_head)
        return event

    def update_head(
        self,
        conversation_id: str,
        **updates: Any,
    ) -> ConversationHead:
        head = self.get_conversation(conversation_id)
        if head is None:
            raise KeyError(f"Conversation {conversation_id} not found")
        updated_head = head.model_copy(
            update={
                **updates,
                "updated_at": utc_now(),
            }
        )
        self._write_head(updated_head)
        return updated_head

    def list_events(self, conversation_id: str) -> list[ConversationEvent]:
        head = self.get_conversation(conversation_id)
        if head is None:
            return []
        prefix = (
            f"tenants/{head.tenant_id}/conversations/{conversation_id}/events/"
        )
        keys = sorted(self._object_store.list_keys(prefix))
        events: list[ConversationEvent] = []
        for key in keys:
            payload = self._object_store.download_json(key)
            events.append(ConversationEvent.model_validate(payload))
        return events

    def _get_conversation_index(
        self,
        conversation_id: str,
    ) -> ConversationIndexEntry | None:
        try:
            payload = self._object_store.download_json(
                self._conversation_index_key(conversation_id)
            )
        except ObjectStoreKeyNotFound:
            return None
        return ConversationIndexEntry.model_validate(payload)

    def _write_head(self, head: ConversationHead) -> None:
        self._object_store.upload_json(
            self._conversation_head_key(
                tenant_id=head.tenant_id,
                conversation_id=head.conversation_id,
            ),
            head.model_dump(mode="json"),
        )

    def _conversation_index_key(self, conversation_id: str) -> str:
        return f"indices/conversations/{conversation_id}.json"

    def _conversation_head_key(self, *, tenant_id: str, conversation_id: str) -> str:
        return f"tenants/{tenant_id}/conversations/{conversation_id}/head.json"

    def _conversation_event_key(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        sequence: int,
    ) -> str:
        return (
            f"tenants/{tenant_id}/conversations/{conversation_id}/events/"
            f"{sequence:06d}.json"
        )


class RunStateStore:
    def __init__(self, object_store: ObjectStore) -> None:
        self._object_store = object_store

    def create_run(
        self,
        *,
        run_id: str,
        tenant_id: str,
        conversation_id: str,
        snapshot_id: str,
        message: str,
    ) -> RunState:
        state = RunState(
            run_id=run_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            snapshot_id=snapshot_id,
            message=message,
        )
        self._write_state(state)
        self._object_store.upload_json(
            self._run_index_key(run_id),
            RunIndexEntry(
                run_id=run_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
            ).model_dump(mode="json"),
        )
        return state

    def get_run(self, run_id: str) -> RunState | None:
        index = self._get_run_index(run_id)
        if index is None:
            return None
        try:
            payload = self._object_store.download_json(
                self._run_state_key(tenant_id=index.tenant_id, run_id=run_id)
            )
        except ObjectStoreKeyNotFound:
            return None
        return RunState.model_validate(payload)

    def update_run(self, run_id: str, **updates: Any) -> RunState:
        state = self.get_run(run_id)
        if state is None:
            raise KeyError(f"Run {run_id} not found")
        updated_state = state.model_copy(
            update={
                **updates,
                "updated_at": utc_now(),
            }
        )
        self._write_state(updated_state)
        return updated_state

    def append_event(self, run_id: str, event: RunEvent) -> RunState:
        state = self.get_run(run_id)
        if state is None:
            raise KeyError(f"Run {run_id} not found")
        sequence = state.event_count + 1
        self._object_store.upload_json(
            self._run_event_key(
                tenant_id=state.tenant_id,
                run_id=run_id,
                sequence=sequence,
            ),
            event.model_dump(mode="json"),
        )
        status = state.status
        if event.type == RunEventType.RUN_COMPLETED:
            status = Status.COMPLETED
        elif event.type == RunEventType.RUN_FAILED:
            status = Status.FAILED
        elif event.type == RunEventType.RUN_PROGRESS and state.status == Status.STARTED:
            status = Status.RUNNING
        updated_state = state.model_copy(
            update={
                "event_count": sequence,
                "status": status,
                "updated_at": utc_now(),
            }
        )
        self._write_state(updated_state)
        return updated_state

    def list_events(self, run_id: str) -> list[RunEvent]:
        state = self.get_run(run_id)
        if state is None:
            return []
        prefix = f"tenants/{state.tenant_id}/runs/{run_id}/events/"
        keys = sorted(self._object_store.list_keys(prefix))
        events: list[RunEvent] = []
        for key in keys:
            payload = self._object_store.download_json(key)
            events.append(RunEvent.model_validate(payload))
        return events

    def _get_run_index(self, run_id: str) -> RunIndexEntry | None:
        try:
            payload = self._object_store.download_json(self._run_index_key(run_id))
        except ObjectStoreKeyNotFound:
            return None
        return RunIndexEntry.model_validate(payload)

    def _write_state(self, state: RunState) -> None:
        self._object_store.upload_json(
            self._run_state_key(tenant_id=state.tenant_id, run_id=state.run_id),
            state.model_dump(mode="json"),
        )

    def _run_index_key(self, run_id: str) -> str:
        return f"indices/runs/{run_id}.json"

    def _run_state_key(self, *, tenant_id: str, run_id: str) -> str:
        return f"tenants/{tenant_id}/runs/{run_id}/state.json"

    def _run_event_key(self, *, tenant_id: str, run_id: str, sequence: int) -> str:
        return f"tenants/{tenant_id}/runs/{run_id}/events/{sequence:06d}.json"
