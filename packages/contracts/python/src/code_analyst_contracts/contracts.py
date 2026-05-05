from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


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


class ConversationUpdateRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None


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


class CitationPreviewLine(BaseModel):
    line_number: int
    content: str


class CitationPreviewResponse(BaseModel):
    snapshot_id: str
    path: str
    requested_start_line: int
    requested_end_line: int
    preview_start_line: int
    preview_end_line: int
    lines: list[CitationPreviewLine] = Field(default_factory=list)


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
    auth_kind: str = "public"  # "public" | "token" | kind-specific values later
    access_secret_ref: str | None = None
    credential_ref: str | None = None  # legacy compatibility for "public" | "env:VAR_NAME"

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_credential_ref(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        if "auth_kind" in value:
            return value

        legacy_credential_ref = str(value.get("credential_ref") or "").strip()
        if legacy_credential_ref in {"", "public", "none"}:
            return {
                **value,
                "auth_kind": "public",
                "access_secret_ref": value.get("access_secret_ref"),
            }
        return {
            **value,
            "auth_kind": "token",
            "access_secret_ref": value.get("access_secret_ref"),
        }


class RepositoryAdapterCreateRequest(BaseModel):
    kind: str  # "github" | "gitlab" (future)
    auth_kind: str = "public"
    access_secret: dict[str, Any] | None = None
    credential_ref: str | None = None  # legacy compatibility for "public" | "env:VAR_NAME"

    @model_validator(mode="after")
    def validate_secret_shape(self) -> "RepositoryAdapterCreateRequest":
        auth_kind = self.auth_kind.strip() or "public"
        credential_ref = (self.credential_ref or "").strip() or None

        if (
            auth_kind == "public"
            and credential_ref is not None
            and credential_ref not in {"public", "none"}
        ):
            auth_kind = "token"

        self.auth_kind = auth_kind
        self.credential_ref = credential_ref

        if auth_kind == "public":
            if self.access_secret is not None:
                raise ValueError("Public repositories cannot include an access_secret.")
            return self

        if self.access_secret is None and credential_ref is None:
            raise ValueError(
                "Non-public repositories require either an access_secret or a legacy credential_ref."
            )
        return self


class RepositoryAdapterUpdateRequest(BaseModel):
    auth_kind: str | None = None
    access_secret: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_secret_shape(self) -> "RepositoryAdapterUpdateRequest":
        auth_kind = self.auth_kind.strip().lower() if self.auth_kind is not None else None
        self.auth_kind = auth_kind or None

        if self.auth_kind == "public" and self.access_secret is not None:
            raise ValueError("Public repositories cannot include an access_secret.")
        return self


class RepositoryDefinition(BaseModel):
    tenant_id: str
    repo_def_id: str
    name: str | None = None
    endpoint: str  # e.g. https://github.com/acme/example.git
    adapter: RepositoryAdapter
    team_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    archived_at: datetime | None = None


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


class TeamSummary(BaseModel):
    tenant_id: str
    team_id: str
    name: str
    created_at: datetime
    member_count: int = 0


class AdminTeamListResponse(BaseModel):
    tenant_id: str
    teams: list[TeamSummary]


class TeamMemberRecord(BaseModel):
    tenant_id: str
    team_id: str
    user_email: str
    name: str | None = None
    is_admin: bool = False
    joined_at: datetime


class TeamDetailResponse(BaseModel):
    tenant_id: str
    team: Team
    members: list[TeamMemberRecord]
    repositories: list[RepositoryDefinition]


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


class AdminUserRecord(BaseModel):
    tenant_id: str
    email: str
    name: str | None = None
    is_admin: bool = False
    created_at: datetime
    has_account: bool = False


class PendingRegistrationInvite(BaseModel):
    invite_id: str
    tenant_id: str
    email: str
    name_hint: str | None = None
    team_ids: list[str] = Field(default_factory=list)
    is_admin: bool = False
    created_by: str | None = None
    created_at: datetime
    expires_at: datetime


class UserListResponse(BaseModel):
    tenant_id: str
    users: list[AdminUserRecord]
    pending_invites: list[PendingRegistrationInvite] = Field(default_factory=list)


class BootstrapAdminInvitationRequest(BaseModel):
    email: str
    name: str | None = None
    expires_in_hours: int | None = None
    bootstrap_secret: str


class RegistrationInviteCreateRequest(BaseModel):
    email: str
    name: str | None = None
    team_ids: list[str] = Field(default_factory=list)
    is_admin: bool = False
    expires_in_hours: int | None = None


class RegistrationInviteCreateResponse(BaseModel):
    tenant_id: str
    email: str
    invite_url: str
    expires_at: datetime


class RegistrationInvitePreviewResponse(BaseModel):
    tenant_id: str
    email: str
    name_hint: str | None = None
    team_ids: list[str] = Field(default_factory=list)
    is_admin: bool = False
    expires_at: datetime


class RegistrationConsumeRequest(BaseModel):
    token: str
    name: str | None = None


class SignInLinkCreateRequest(BaseModel):
    email: str
    expires_in_hours: int | None = None


class SignInLinkCreateResponse(BaseModel):
    tenant_id: str
    email: str
    sign_in_url: str
    expires_at: datetime


class SignInConsumeRequest(BaseModel):
    token: str


class LogoutResponse(BaseModel):
    status: str = "ok"


class RepositoryDefinitionCreateRequest(BaseModel):
    name: str | None = None
    endpoint: str
    adapter: RepositoryAdapterCreateRequest
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


class RepositoryDefinitionUpdateRequest(BaseModel):
    name: str | None = None
    endpoint: str | None = None
    team_ids: list[str] | None = None
    adapter: RepositoryAdapterUpdateRequest | None = None


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
    pinned_at: datetime | None = None
    deleted_at: datetime | None = None


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
