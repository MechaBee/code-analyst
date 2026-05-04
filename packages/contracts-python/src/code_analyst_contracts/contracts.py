from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Status(str, Enum):
    READY = "READY"
    OPEN = "OPEN"
    STARTED = "STARTED"
    RUNNING = "RUNNING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    RESUMED = "RESUMED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DISPOSED = "DISPOSED"


class RunEventType(str, Enum):
    RUN_STARTED = "run.started"
    RUN_PROGRESS = "run.progress"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    CITATION_CREATED = "citation.created"
    APPROVAL_REQUIRED = "approval.required"
    ANSWER_DELTA = "answer.delta"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"


class HealthResponse(BaseModel):
    name: str
    status: str = "ok"
    timestamp: datetime = Field(default_factory=utc_now)


class WorkspaceImportRequest(BaseModel):
    tenant_id: str
    repo_url: str
    ref: str = "main"
    github_credential_ref: str


class WorkspaceImportResponse(BaseModel):
    workspace_id: str
    snapshot_id: str
    source_commit: str
    status: Status = Status.READY
    archive_object_key: str | None = None
    manifest_object_key: str | None = None
    metadata_object_key: str | None = None
    file_count: int | None = None
    total_size_bytes: int | None = None


class ConversationCreateRequest(BaseModel):
    tenant_id: str
    repo_def_id: str
    checkout_id: str | None = None
    workspace_id: str | None = None
    title: str | None = None


class ConversationCreateResponse(BaseModel):
    conversation_id: str
    status: Status = Status.OPEN


class QuestionRequest(BaseModel):
    message: str
    workspace_snapshot_id: str | None = None
    resume_sandbox: bool = True
    approval_policy: str = "auto"  # "auto" | "required"


class QuestionResponse(BaseModel):
    run_id: str
    status: Status = Status.STARTED
    events_url: str


class ApprovalDecisionRequest(BaseModel):
    decision: str
    reason: str | None = None


class ApprovalDecisionResponse(BaseModel):
    run_id: str
    approval_id: str
    status: Status = Status.RESUMED


class ApprovalState(BaseModel):
    approval_id: str
    run_id: str
    decision: str | None = None
    reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None


class WorkspaceSnapshotRef(BaseModel):
    workspace_id: str
    snapshot_id: str
    repo_url: str
    ref: str
    commit_sha: str
    archive_object_key: str
    manifest_object_key: str
    metadata_object_key: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class SnapshotFileEntry(BaseModel):
    path: str
    size_bytes: int
    sha256: str


class SnapshotManifest(BaseModel):
    tenant_id: str
    workspace_id: str
    snapshot_id: str
    repo_url: str
    ref: str
    commit_sha: str
    archive_object_key: str
    manifest_object_key: str
    metadata_object_key: str
    created_at: datetime = Field(default_factory=utc_now)
    root_prefix: str = "workspace"
    file_count: int
    total_size_bytes: int
    top_level_entries: list[str] = Field(default_factory=list)
    files: list[SnapshotFileEntry] = Field(default_factory=list)


class SandboxSessionCreateRequest(BaseModel):
    workspace: WorkspaceSnapshotRef
    runtime_image: str | None = None
    resume_from_sandbox_id: str | None = None
    environment_profile: str = "local"


class SandboxSessionRef(BaseModel):
    sandbox_id: str
    provider: str = "docker"
    runtime_image: str
    status: Status = Status.RUNNING
    snapshot_id: str
    session_state_key: str


class SandboxExecutionRequest(BaseModel):
    sandbox_id: str
    conversation_id: str
    run_id: str
    message: str
    policy: dict[str, Any] = Field(default_factory=dict)


class EvidenceRef(BaseModel):
    snapshot_id: str
    path: str
    start_line: int
    end_line: int
    excerpt_hash: str


class ArtifactRef(BaseModel):
    artifact_id: str
    object_key: str
    content_type: str


class AnswerEnvelope(BaseModel):
    answer_markdown: str
    citations: list[EvidenceRef] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)


class SandboxExecutionResponse(BaseModel):
    sandbox_id: str
    run_id: str
    status: Status = Status.COMPLETED
    answer: AnswerEnvelope


class SandboxDisposeRequest(BaseModel):
    persist_session_state: bool = True


class SandboxDisposeResponse(BaseModel):
    sandbox_id: str
    status: Status = Status.DISPOSED


# ---------------------------------------------------------------------------
# Phase 1: Identity, Team, and Repository Definition models
# ---------------------------------------------------------------------------

class RepositoryAdapter(BaseModel):
    kind: str  # "github" | "gitlab" (future)
    credential_ref: str  # "public" | "env:VAR_NAME"


class RepositoryDefinition(BaseModel):
    tenant_id: str
    repo_def_id: str
    name: str | None = None
    endpoint: str  # e.g. https://github.com/acme/example.git
    adapter: RepositoryAdapter
    team_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class User(BaseModel):
    tenant_id: str
    email: str  # globally unique within tenant, acts as user id
    name: str | None = None
    is_admin: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class Team(BaseModel):
    tenant_id: str
    team_id: str
    name: str
    created_at: datetime = Field(default_factory=utc_now)


class TeamMembership(BaseModel):
    tenant_id: str
    team_id: str
    user_email: str
    joined_at: datetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Request / Response helpers for new endpoints
# ---------------------------------------------------------------------------

class TeamCreateRequest(BaseModel):
    name: str


class TeamCreateResponse(BaseModel):
    team_id: str
    tenant_id: str
    name: str
    created_at: datetime


class TeamListResponse(BaseModel):
    tenant_id: str
    teams: list[Team]


class TeamMemberAddRequest(BaseModel):
    user_email: str


class TeamMemberAddResponse(BaseModel):
    team_id: str
    user_email: str
    joined_at: datetime


class TeamMemberRemoveResponse(BaseModel):
    team_id: str
    user_email: str


class UserCreateRequest(BaseModel):
    email: str
    name: str | None = None
    is_admin: bool = False


class UserCreateResponse(BaseModel):
    tenant_id: str
    email: str
    name: str | None = None
    is_admin: bool = False
    created_at: datetime


class UserMeResponse(BaseModel):
    tenant_id: str
    email: str
    name: str | None = None
    is_admin: bool = False


class RepositoryDefinitionCreateRequest(BaseModel):
    name: str | None = None
    endpoint: str
    adapter: RepositoryAdapter
    team_ids: list[str] = Field(default_factory=list)


class RepositoryDefinitionCreateResponse(BaseModel):
    tenant_id: str
    repo_def_id: str
    name: str | None = None
    endpoint: str
    adapter: RepositoryAdapter
    team_ids: list[str]
    created_at: datetime


class RepositoryDefinitionListResponse(BaseModel):
    tenant_id: str
    repo_definitions: list[RepositoryDefinition]


class RepositoryDefinitionUpdateTeamsRequest(BaseModel):
    team_ids: list[str]


class RepositoryDefinitionUpdateTeamsResponse(BaseModel):
    tenant_id: str
    repo_def_id: str
    team_ids: list[str]


# ---------------------------------------------------------------------------
# Phase 2: Checkout entity
# ---------------------------------------------------------------------------

class Checkout(BaseModel):
    tenant_id: str
    checkout_id: str
    repo_def_id: str
    branch: str
    commit_sha: str
    run_timestamp: datetime = Field(default_factory=utc_now)
    workspace_id: str
    snapshot_id: str
    archived: bool = False


class CheckoutCreateRequest(BaseModel):
    repo_def_id: str
    ref: str = "main"


class CheckoutCreateResponse(BaseModel):
    tenant_id: str
    checkout_id: str
    repo_def_id: str
    branch: str
    commit_sha: str
    run_timestamp: datetime
    workspace_id: str
    snapshot_id: str


class CheckoutListResponse(BaseModel):
    tenant_id: str
    checkouts: list[Checkout]


class ConversationHead(BaseModel):
    conversation_id: str
    tenant_id: str
    workspace_id: str
    repo_def_id: str | None = None
    checkout_id: str | None = None
    principal_email: str
    title: str | None = None
    status: str = "OPEN"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_event_sequence: int = 0
    latest_run_id: str | None = None
    active_sandbox_id: str | None = None
    latest_snapshot_id: str | None = None


class ConversationListResponse(BaseModel):
    tenant_id: str
    conversations: list[ConversationHead]


class ConversationEvent(BaseModel):
    event_id: str
    conversation_id: str
    run_id: str | None = None
    sequence: int
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)


class RunEvent(BaseModel):
    run_id: str
    type: RunEventType
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)
