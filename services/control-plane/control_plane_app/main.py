from __future__ import annotations

import asyncio
import io
import logging
import posixpath
import tarfile
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from uuid import uuid4

from code_analyst_contracts import (
    AdminUserRecord,
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    AdminTeamListResponse,
    BootstrapAdminInvitationRequest,
    CitationPreviewLine,
    CitationPreviewResponse,
    Checkout,
    CheckoutCreateRequest,
    CheckoutCreateResponse,
    CheckoutListResponse,
    ConversationCreateRequest,
    ConversationCreateResponse,
    ConversationEvent,
    ConversationHead,
    ConversationListResponse,
    ConversationUpdateRequest,
    HealthResponse,
    LogoutResponse,
    RegistrationConsumeRequest,
    RegistrationInviteCreateRequest,
    RegistrationInviteCreateResponse,
    RegistrationInvitePreviewResponse,
    QuestionRequest,
    QuestionResponse,
    RepositoryDefinition,
    RepositoryDefinitionCreateRequest,
    RepositoryDefinitionCreateResponse,
    RepositoryDefinitionListResponse,
    RepositoryDefinitionUpdateRequest,
    RepositoryDefinitionUpdateTeamsRequest,
    RepositoryDefinitionUpdateTeamsResponse,
    SnapshotManifest,
    SignInConsumeRequest,
    SignInLinkCreateRequest,
    SignInLinkCreateResponse,
    RepositoryAdapter,
    RepositoryAdapterUpdateRequest,
    Team,
    TeamCreateRequest,
    TeamCreateResponse,
    TeamDetailResponse,
    TeamListResponse,
    TeamMemberAddRequest,
    TeamMemberAddResponse,
    TeamMemberRecord,
    TeamMemberRemoveResponse,
    TeamMembership,
    TeamSummary,
    User,
    UserCreateRequest,
    UserCreateResponse,
    UserListResponse,
    UserMeResponse,
    WorkspaceImportRequest,
    WorkspaceImportResponse,
)
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
import zstandard

from .app_state_store import AppStateStore
from .auth import (
    AuthConflictError,
    AuthError,
    AuthForbiddenError,
    AuthNotFoundError,
    AuthService,
    AuthTokenExpiredError,
    AuthTokenUsedError,
    build_auth_store,
    build_request_auth_backend,
    normalize_email,
)
from .config import Settings, settings
from .object_store import ObjectStore
from .question_orchestrator import QuestionOrchestrator
from .repository_checkout import build_repository_checkout_service
from .sandbox_supervisor_client import SandboxSupervisorClient
from .secret_store import SecretStoreError, build_secret_store
from .state_store import (
    ApprovalStateStore,
    ConversationStateStore,
    RunStateStore,
    WorkspaceStateStore,
)
from .workspace_imports import WorkspaceImportError, WorkspaceImportService

app = FastAPI(title="Code Analyst Control Plane", version="0.1.0")
logger = logging.getLogger(__name__)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class AppState:
    def __init__(self, app_settings: Settings = settings) -> None:
        self.settings = app_settings
        self.object_store = ObjectStore(app_settings)
        self.workspace_store = WorkspaceStateStore(self.object_store)
        self.conversation_store = ConversationStateStore(self.object_store)
        self.run_store = RunStateStore(self.object_store)
        self.approval_store = ApprovalStateStore(self.object_store)
        self.app_state_store = AppStateStore(self.object_store)
        self.auth_store = build_auth_store(app_settings)
        self.auth_service = AuthService(
            settings=app_settings,
            store=self.auth_store,
            app_state_store=self.app_state_store,
        )
        self.request_auth_backend = build_request_auth_backend(
            app_settings,
            auth_service=self.auth_service,
        )
        self.secret_store = build_secret_store(app_settings)
        self.repository_checkout_service = build_repository_checkout_service(
            app_settings,
            secret_store=self.secret_store,
        )
        self.workspace_import_service = WorkspaceImportService(
            settings=app_settings,
            object_store=self.object_store,
            repository_checkout_service=self.repository_checkout_service,
        )
        self.question_orchestrator = QuestionOrchestrator(
            sandbox_client=SandboxSupervisorClient(
                app_settings.sandbox_supervisor_url,
                timeout_seconds=app_settings.sandbox_supervisor_timeout_seconds,
            ),
            conversation_store=self.conversation_store,
            run_store=self.run_store,
            workspace_store=self.workspace_store,
            approval_store=self.approval_store,
            app_state_store=self.app_state_store,
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
    request: Request,
    body: ConversationCreateRequest,
) -> ConversationCreateResponse:
    principal = await ensure_user(request)
    tenant_id = principal.tenant_id

    # Validate repo_def exists and principal has access
    repo_def = app.state.state.app_state_store.get_repo_definition(
        tenant_id, body.repo_def_id
    )
    if repo_def is None:
        raise HTTPException(status_code=404, detail="Repository definition not found.")
    ensure_repo_access(principal, repo_def)
    ensure_repo_is_active(repo_def)

    # Resolve workspace_id from checkout or request
    workspace_id: str | None = None
    snapshot_id: str | None = None
    if body.checkout_id:
        checkout = app.state.state.app_state_store.get_checkout(
            tenant_id, body.checkout_id
        )
        if checkout is None:
            raise HTTPException(status_code=404, detail="Checkout not found.")
        if checkout.repo_def_id != body.repo_def_id:
            raise HTTPException(
                status_code=400,
                detail="Checkout does not belong to the specified repository.",
            )
        workspace_id = checkout.workspace_id
        snapshot_id = checkout.snapshot_id
    elif body.workspace_id:
        workspace_id = body.workspace_id
    else:
        raise HTTPException(
            status_code=400,
            detail="Either checkout_id or workspace_id must be provided.",
        )

    conversation_id = new_id("conv")
    head = await run_in_threadpool(
        app.state.state.conversation_store.create_conversation,
        conversation_id=conversation_id,
        request=body,
        principal_email=principal.email,
        workspace_id=workspace_id,
    )
    if snapshot_id:
        await run_in_threadpool(
            app.state.state.conversation_store.update_head,
            conversation_id,
            latest_snapshot_id=snapshot_id,
        )
    return ConversationCreateResponse(conversation_id=conversation_id)


@app.get("/v1/conversations", response_model=ConversationListResponse)
async def list_conversations(
    request: Request,
    repo_def_id: str | None = None,
    checkout_id: str | None = None,
) -> ConversationListResponse:
    principal = await ensure_user(request)
    conversations = await run_in_threadpool(
        app.state.state.conversation_store.list_conversations,
        tenant_id=principal.tenant_id,
        principal_email=principal.email,
        repo_def_id=repo_def_id,
        checkout_id=checkout_id,
    )
    return ConversationListResponse(
        tenant_id=principal.tenant_id,
        conversations=conversations,
    )


@app.get("/v1/conversations/{conversation_id}", response_model=ConversationHead)
async def get_conversation(
    request: Request,
    conversation_id: str,
) -> ConversationHead:
    principal = await ensure_user(request)
    conversation = await run_in_threadpool(
        app.state.state.conversation_store.get_conversation,
        conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if conversation.principal_email != principal.email:
        raise HTTPException(status_code=403, detail="Access denied to this conversation.")
    return conversation


@app.patch("/v1/conversations/{conversation_id}", response_model=ConversationHead)
async def update_conversation(
    request: Request,
    conversation_id: str,
    body: ConversationUpdateRequest,
) -> ConversationHead:
    principal = await ensure_user(request)
    conversation = await run_in_threadpool(
        app.state.state.conversation_store.get_conversation,
        conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if conversation.principal_email != principal.email:
        raise HTTPException(status_code=403, detail="Access denied to this conversation.")

    updates: dict[str, object] = {}
    if "title" in body.model_fields_set:
        normalized_title = body.title.strip() if body.title is not None else None
        updates["title"] = normalized_title or None
    if "pinned" in body.model_fields_set:
        updates["pinned_at"] = (
            datetime.now(timezone.utc) if body.pinned else None
        )

    if not updates:
        return conversation

    return await run_in_threadpool(
        app.state.state.conversation_store.update_head,
        conversation_id,
        **updates,
    )


@app.delete("/v1/conversations/{conversation_id}", response_model=ConversationHead)
async def delete_conversation(
    request: Request,
    conversation_id: str,
) -> ConversationHead:
    principal = await ensure_user(request)
    conversation = await run_in_threadpool(
        app.state.state.conversation_store.get_conversation,
        conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if conversation.principal_email != principal.email:
        raise HTTPException(status_code=403, detail="Access denied to this conversation.")

    return await run_in_threadpool(
        app.state.state.conversation_store.update_head,
        conversation_id,
        status="DELETED",
        deleted_at=datetime.now(timezone.utc),
        pinned_at=None,
        active_sandbox_id=None,
    )


@app.get(
    "/v1/conversations/{conversation_id}/events",
    response_model=list[ConversationEvent],
)
async def list_conversation_events(
    request: Request,
    conversation_id: str,
) -> list[ConversationEvent]:
    principal = await ensure_user(request)
    conversation = await run_in_threadpool(
        app.state.state.conversation_store.get_conversation,
        conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if conversation.principal_email != principal.email:
        raise HTTPException(status_code=403, detail="Access denied to this conversation.")
    return await run_in_threadpool(
        app.state.state.conversation_store.list_events,
        conversation_id,
    )


@app.get(
    "/v1/conversations/{conversation_id}/citations/preview",
    response_model=CitationPreviewResponse,
)
async def get_citation_preview(
    request: Request,
    conversation_id: str,
    snapshot_id: str,
    path: str,
    start_line: int,
    end_line: int,
) -> CitationPreviewResponse:
    principal = await ensure_user(request)
    conversation = await run_in_threadpool(
        app.state.state.conversation_store.get_conversation,
        conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if conversation.principal_email != principal.email:
        raise HTTPException(status_code=403, detail="Access denied to this conversation.")

    try:
        normalized_path = normalize_citation_preview_path(path)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    snapshot = await run_in_threadpool(
        app.state.state.workspace_store.get_snapshot,
        tenant_id=principal.tenant_id,
        workspace_id=conversation.workspace_id,
        snapshot_id=snapshot_id,
    )
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="Workspace snapshot not found for this conversation.",
        )

    try:
        preview = await run_in_threadpool(
            build_citation_preview_response,
            principal.tenant_id,
            snapshot,
            normalized_path,
            start_line,
            end_line,
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return preview


@app.post(
    "/v1/conversations/{conversation_id}/questions",
    response_model=QuestionResponse,
)
async def ask_question(
    request: Request,
    conversation_id: str,
    body: QuestionRequest,
) -> QuestionResponse:
    principal = await ensure_user(request)
    conversation = app.state.state.conversation_store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if conversation.principal_email != principal.email:
        raise HTTPException(status_code=403, detail="Access denied to this conversation.")

    try:
        return await app.state.state.question_orchestrator.execute_question(
            conversation_id=conversation_id,
            request=body,
        )
    except HTTPException as error:
        logger.warning(
            "Question request failed with HTTPException: conversation_id=%s principal_email=%s status_code=%s detail=%r",
            conversation_id,
            principal.email,
            error.status_code,
            error.detail,
        )
        raise
    except Exception as error:
        logger.exception(
            "Question execution failed: conversation_id=%s principal_email=%s",
            conversation_id,
            principal.email,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Question execution failed: {error}",
        ) from error


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
    return await app.state.state.question_orchestrator.resume_run_after_approval(
        run_id=run_id,
        decision=request.decision,
        reason=request.reason,
    )


# ---------------------------------------------------------------------------
# Auth & Identity helpers
# ---------------------------------------------------------------------------


def get_requested_tenant_id(request: Request) -> str:
    tenant_id = (request.headers.get("X-Tenant-Id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing X-Tenant-Id header.")
    return tenant_id


async def ensure_user(request: Request) -> User:
    return await run_in_threadpool(
        app.state.state.request_auth_backend.authenticate_request,
        request=request,
        app_state_store=app.state.state.app_state_store,
    )


def raise_for_auth_error(error: AuthError) -> None:
    if isinstance(error, AuthForbiddenError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    if isinstance(error, AuthConflictError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, (AuthTokenExpiredError, AuthTokenUsedError)):
        raise HTTPException(status_code=410, detail=str(error)) from error
    if isinstance(error, AuthNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    raise HTTPException(status_code=400, detail=str(error)) from error


def normalize_citation_preview_path(path: str) -> str:
    normalized = posixpath.normpath((path or "").strip())
    if not normalized or normalized == ".":
        raise ValueError("Citation path is required.")
    if normalized.startswith("../") or normalized.startswith("/") or "\\" in normalized:
        raise ValueError("Citation path must stay within the workspace snapshot.")
    return normalized


def build_citation_preview_response(
    tenant_id: str,
    snapshot: "WorkspaceSnapshotRef",
    path: str,
    start_line: int,
    end_line: int,
) -> CitationPreviewResponse:
    manifest = load_snapshot_manifest(tenant_id, snapshot)
    manifest_paths = {entry.path for entry in manifest.files}
    if path not in manifest_paths:
        raise FileNotFoundError("Citation file was not found in this workspace snapshot.")

    lines = load_snapshot_text_lines(snapshot, path)
    if not lines:
        raise ValueError("Citation preview is unavailable for an empty file.")

    requested_start_line = max(1, start_line)
    requested_end_line = max(requested_start_line, end_line)
    safe_start_line = min(requested_start_line, len(lines))
    safe_end_line = min(max(safe_start_line, requested_end_line), len(lines))

    if safe_end_line - safe_start_line + 1 >= 80:
        preview_start_line = safe_start_line
        preview_end_line = min(len(lines), safe_start_line + 79)
    else:
        preview_start_line = max(1, safe_start_line - 2)
        preview_end_line = min(len(lines), safe_end_line + 2)
        if preview_end_line - preview_start_line + 1 > 80:
            preview_end_line = min(len(lines), preview_start_line + 79)

    preview_lines = [
        CitationPreviewLine(line_number=line_number, content=lines[line_number - 1])
        for line_number in range(preview_start_line, preview_end_line + 1)
    ]

    return CitationPreviewResponse(
        snapshot_id=snapshot.snapshot_id,
        path=path,
        requested_start_line=requested_start_line,
        requested_end_line=requested_end_line,
        preview_start_line=preview_start_line,
        preview_end_line=preview_end_line,
        lines=preview_lines,
    )


def load_snapshot_manifest(tenant_id: str, snapshot: "WorkspaceSnapshotRef") -> SnapshotManifest:
    payload = app.state.state.object_store.download_json(snapshot.manifest_object_key)
    manifest = SnapshotManifest.model_validate(payload)
    if (
        manifest.snapshot_id != snapshot.snapshot_id
        or manifest.workspace_id != snapshot.workspace_id
        or manifest.tenant_id != tenant_id
    ):
        raise ValueError("Workspace snapshot metadata did not match the requested conversation.")
    return manifest


def load_snapshot_text_lines(snapshot: "WorkspaceSnapshotRef", path: str) -> list[str]:
    archive_payload = app.state.state.object_store.download_bytes(snapshot.archive_object_key)
    target_member_name = f"workspace/{path}"
    decompressor = zstandard.ZstdDecompressor()
    with decompressor.stream_reader(io.BytesIO(archive_payload)) as archive_stream:
        with tarfile.open(fileobj=archive_stream, mode="r|") as archive:
            for member in archive:
                if member.name != target_member_name:
                    continue
                file_handle = archive.extractfile(member)
                if file_handle is None:
                    break
                try:
                    return file_handle.read().decode("utf-8").splitlines()
                except UnicodeDecodeError as error:
                    raise ValueError(
                        "Citation preview is only available for UTF-8 text files."
                    ) from error
    raise FileNotFoundError("Citation file contents could not be loaded from the snapshot.")


def normalize_email_or_400(email: str) -> str:
    try:
        return normalize_email(email)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def require_admin(principal: User) -> None:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")


def normalize_team_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Team name is required.")
    return normalized


def normalize_repo_name(name: str | None) -> str | None:
    if name is None:
        return None
    normalized = name.strip()
    return normalized or None


def normalize_repo_endpoint(endpoint: str | None) -> str:
    normalized = (endpoint or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Repository endpoint is required.")
    return normalized


def normalize_team_ids(tenant_id: str, team_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_team_id in team_ids:
        team_id = raw_team_id.strip()
        if not team_id or team_id in seen:
            continue
        seen.add(team_id)
        normalized.append(team_id)

    missing = [
        team_id for team_id in normalized
        if app.state.state.app_state_store.get_team(tenant_id, team_id) is None
    ]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown team id(s): {', '.join(missing)}",
        )
    return normalized


def principal_can_access_repo(principal: User, repo_def: RepositoryDefinition) -> bool:
    if principal.is_admin:
        return True
    user_teams = app.state.state.app_state_store.list_teams_for_user(
        principal.tenant_id,
        principal.email,
    )
    user_team_ids = {team.team_id for team in user_teams}
    return any(team_id in user_team_ids for team_id in repo_def.team_ids)


def ensure_repo_access(principal: User, repo_def: RepositoryDefinition) -> None:
    if not principal_can_access_repo(principal, repo_def):
        raise HTTPException(status_code=403, detail="Access denied to this repository.")


def ensure_repo_is_active(repo_def: RepositoryDefinition) -> None:
    if repo_def.archived_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Repository is archived.",
        )


def resolve_repo_adapter_update(
    *,
    tenant_id: str,
    existing_adapter: RepositoryAdapter,
    update_request: RepositoryAdapterUpdateRequest,
) -> tuple[RepositoryAdapter, str | None, str | None]:
    auth_kind = (existing_adapter.auth_kind or "public").strip().lower() or "public"
    if "auth_kind" in update_request.model_fields_set and update_request.auth_kind is not None:
        auth_kind = update_request.auth_kind.strip().lower() or "public"

    if auth_kind not in {"public", "token"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported repository auth_kind {auth_kind!r}.",
        )

    if auth_kind == "public":
        return (
            RepositoryAdapter(
                kind=existing_adapter.kind,
                auth_kind="public",
                access_secret_ref=None,
                credential_ref=None,
            ),
            None,
            existing_adapter.access_secret_ref,
        )

    access_secret = (
        update_request.access_secret
        if "access_secret" in update_request.model_fields_set
        else None
    )
    if access_secret is not None:
        try:
            new_secret_ref = app.state.state.secret_store.store_secret(
                tenant_id=tenant_id,
                secret=access_secret,
            )
        except SecretStoreError as error:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to store repository access secret: {error}",
            ) from error

        return (
            RepositoryAdapter(
                kind=existing_adapter.kind,
                auth_kind="token",
                access_secret_ref=new_secret_ref,
                credential_ref=None,
            ),
            new_secret_ref,
            existing_adapter.access_secret_ref,
        )

    if existing_adapter.access_secret_ref or (existing_adapter.credential_ref or "").strip():
        return (
            RepositoryAdapter(
                kind=existing_adapter.kind,
                auth_kind="token",
                access_secret_ref=existing_adapter.access_secret_ref,
                credential_ref=existing_adapter.credential_ref,
            ),
            None,
            None,
        )

    raise HTTPException(
        status_code=400,
        detail=(
            "Token-based repositories require an existing secret or credential_ref, "
            "or a new access_secret."
        ),
    )


async def apply_repo_definition_update(
    *,
    principal: User,
    repo_def_id: str,
    body: RepositoryDefinitionUpdateRequest,
) -> RepositoryDefinition:
    existing = await run_in_threadpool(
        app.state.state.app_state_store.get_repo_definition,
        principal.tenant_id,
        repo_def_id,
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="Repository definition not found.")

    updates: dict[str, object] = {}
    if "name" in body.model_fields_set:
        updates["name"] = normalize_repo_name(body.name)
    if "endpoint" in body.model_fields_set:
        updates["endpoint"] = normalize_repo_endpoint(body.endpoint)
    if "team_ids" in body.model_fields_set and body.team_ids is not None:
        updates["team_ids"] = normalize_team_ids(principal.tenant_id, body.team_ids)

    new_secret_ref: str | None = None
    old_secret_ref_to_delete: str | None = None
    if "adapter" in body.model_fields_set and body.adapter is not None:
        adapter, new_secret_ref, old_secret_ref_to_delete = resolve_repo_adapter_update(
            tenant_id=principal.tenant_id,
            existing_adapter=existing.adapter,
            update_request=body.adapter,
        )
        updates["adapter"] = adapter

    updated_repo = existing.model_copy(update=updates)
    try:
        updated_repo = await run_in_threadpool(
            app.state.state.app_state_store.replace_repo_definition,
            principal.tenant_id,
            updated_repo,
        )
    except Exception:
        if new_secret_ref is not None:
            try:
                app.state.state.secret_store.delete_secret(
                    tenant_id=principal.tenant_id,
                    secret_ref=new_secret_ref,
                )
            except SecretStoreError:
                logger.warning(
                    "Failed to roll back stored repository secret after repo update failure: tenant_id=%s repo_def_id=%s",
                    principal.tenant_id,
                    repo_def_id,
                )
        raise

    if (
        old_secret_ref_to_delete is not None
        and old_secret_ref_to_delete != updated_repo.adapter.access_secret_ref
    ):
        try:
            app.state.state.secret_store.delete_secret(
                tenant_id=principal.tenant_id,
                secret_ref=old_secret_ref_to_delete,
            )
        except SecretStoreError:
            logger.warning(
                "Failed to delete superseded repository secret after repo update: tenant_id=%s repo_def_id=%s",
                principal.tenant_id,
                repo_def_id,
            )

    return updated_repo


# ---------------------------------------------------------------------------
# Auth Endpoints
# ---------------------------------------------------------------------------


@app.post(
    "/v1/auth/bootstrap/invitations",
    response_model=RegistrationInviteCreateResponse,
)
async def create_bootstrap_admin_invitation(
    request: Request,
    body: BootstrapAdminInvitationRequest,
) -> RegistrationInviteCreateResponse:
    tenant_id = get_requested_tenant_id(request)
    try:
        invite_url, expires_at = await run_in_threadpool(
            app.state.state.auth_service.create_bootstrap_admin_invitation,
            tenant_id=tenant_id,
            email=body.email,
            name=body.name,
            expires_in_hours=body.expires_in_hours,
            bootstrap_secret=body.bootstrap_secret,
        )
    except AuthError as error:
        raise_for_auth_error(error)
    return RegistrationInviteCreateResponse(
        tenant_id=tenant_id,
        email=normalize_email_or_400(body.email),
        invite_url=invite_url,
        expires_at=expires_at,
    )


@app.post("/v1/auth/invitations", response_model=RegistrationInviteCreateResponse)
async def create_registration_invitation(
    request: Request,
    body: RegistrationInviteCreateRequest,
) -> RegistrationInviteCreateResponse:
    principal = await ensure_user(request)
    require_admin(principal)
    team_ids = normalize_team_ids(principal.tenant_id, body.team_ids)
    try:
        invite_url, expires_at = await run_in_threadpool(
            app.state.state.auth_service.create_registration_invitation,
            tenant_id=principal.tenant_id,
            email=body.email,
            name=body.name,
            team_ids=team_ids,
            is_admin=body.is_admin,
            created_by=principal.email,
            expires_in_hours=body.expires_in_hours,
        )
    except AuthError as error:
        raise_for_auth_error(error)
    return RegistrationInviteCreateResponse(
        tenant_id=principal.tenant_id,
        email=normalize_email_or_400(body.email),
        invite_url=invite_url,
        expires_at=expires_at,
    )


@app.get(
    "/v1/auth/registration/preview",
    response_model=RegistrationInvitePreviewResponse,
)
async def preview_registration_invitation(
    token: str,
) -> RegistrationInvitePreviewResponse:
    try:
        invite = await run_in_threadpool(
            app.state.state.auth_service.preview_registration_invitation,
            token=token,
        )
    except AuthError as error:
        raise_for_auth_error(error)
    return RegistrationInvitePreviewResponse(
        tenant_id=invite.tenant_id,
        email=invite.email,
        name_hint=invite.name_hint,
        team_ids=invite.team_ids,
        is_admin=invite.is_admin,
        expires_at=invite.expires_at,
    )


@app.post("/v1/auth/register/consume", response_model=UserMeResponse)
async def consume_registration_invitation(
    body: RegistrationConsumeRequest,
    response: Response,
) -> UserMeResponse:
    try:
        user, session_token = await run_in_threadpool(
            app.state.state.auth_service.consume_registration_invitation,
            token=body.token,
            name=body.name,
        )
    except AuthError as error:
        raise_for_auth_error(error)

    app.state.state.auth_service.set_session_cookie(response, token=session_token)
    return UserMeResponse(
        tenant_id=user.tenant_id,
        email=user.email,
        name=user.name,
        is_admin=user.is_admin,
    )


@app.post("/v1/auth/sign-in-links", response_model=SignInLinkCreateResponse)
async def create_sign_in_link(
    request: Request,
    body: SignInLinkCreateRequest,
) -> SignInLinkCreateResponse:
    principal = await ensure_user(request)
    require_admin(principal)
    try:
        sign_in_url, expires_at = await run_in_threadpool(
            app.state.state.auth_service.create_sign_in_link,
            tenant_id=principal.tenant_id,
            email=body.email,
            expires_in_hours=body.expires_in_hours,
        )
    except AuthError as error:
        raise_for_auth_error(error)
    return SignInLinkCreateResponse(
        tenant_id=principal.tenant_id,
        email=normalize_email_or_400(body.email),
        sign_in_url=sign_in_url,
        expires_at=expires_at,
    )


@app.post("/v1/auth/sign-in/consume", response_model=UserMeResponse)
async def consume_sign_in_link(
    body: SignInConsumeRequest,
    response: Response,
) -> UserMeResponse:
    try:
        user, session_token = await run_in_threadpool(
            app.state.state.auth_service.consume_sign_in_link,
            token=body.token,
        )
    except AuthError as error:
        raise_for_auth_error(error)

    app.state.state.auth_service.set_session_cookie(response, token=session_token)
    return UserMeResponse(
        tenant_id=user.tenant_id,
        email=user.email,
        name=user.name,
        is_admin=user.is_admin,
    )


@app.post("/v1/auth/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
) -> LogoutResponse:
    await run_in_threadpool(
        app.state.state.auth_service.logout_session,
        token=request.cookies.get(app.state.state.settings.auth_cookie_name),
    )
    app.state.state.auth_service.clear_session_cookie(response)
    return LogoutResponse()


# ---------------------------------------------------------------------------
# Admin & Identity Endpoints
# ---------------------------------------------------------------------------


@app.post("/v1/teams", response_model=TeamCreateResponse)
async def create_team(
    request: Request,
    body: TeamCreateRequest,
) -> TeamCreateResponse:
    principal = await ensure_user(request)
    require_admin(principal)
    team = Team(
        tenant_id=principal.tenant_id,
        team_id=new_id("team"),
        name=normalize_team_name(body.name),
    )
    await run_in_threadpool(
        app.state.state.app_state_store.create_team,
        team,
    )
    return TeamCreateResponse(
        team_id=team.team_id,
        tenant_id=team.tenant_id,
        name=team.name,
        created_at=team.created_at,
    )


@app.get("/v1/teams", response_model=TeamListResponse)
async def list_teams(request: Request) -> TeamListResponse:
    principal = await ensure_user(request)
    require_admin(principal)
    teams = await run_in_threadpool(
        app.state.state.app_state_store.list_teams,
        principal.tenant_id,
    )
    return TeamListResponse(
        tenant_id=principal.tenant_id,
        teams=sorted(teams, key=lambda team: (team.name.lower(), team.team_id)),
    )


@app.get("/v1/admin/users", response_model=UserListResponse)
async def list_admin_users(request: Request) -> UserListResponse:
    principal = await ensure_user(request)
    require_admin(principal)
    users = await run_in_threadpool(
        app.state.state.app_state_store.list_users,
        principal.tenant_id,
    )
    registered_emails = await run_in_threadpool(
        app.state.state.auth_service.registered_emails,
        tenant_id=principal.tenant_id,
    )
    pending_invites = await run_in_threadpool(
        app.state.state.auth_service.list_pending_registration_invites,
        tenant_id=principal.tenant_id,
    )
    return UserListResponse(
        tenant_id=principal.tenant_id,
        users=[
            AdminUserRecord(
                tenant_id=user.tenant_id,
                email=user.email,
                name=user.name,
                is_admin=user.is_admin,
                created_at=user.created_at,
                has_account=user.email in registered_emails,
            )
            for user in sorted(users, key=lambda user: (user.email.lower(), user.created_at))
        ],
        pending_invites=pending_invites,
    )


@app.get("/v1/admin/teams", response_model=AdminTeamListResponse)
async def list_admin_teams(request: Request) -> AdminTeamListResponse:
    principal = await ensure_user(request)
    require_admin(principal)
    db = await run_in_threadpool(
        app.state.state.app_state_store.load_tenant_db,
        principal.tenant_id,
    )

    member_counts: dict[str, int] = {}
    for membership in db.memberships:
        member_counts[membership.team_id] = member_counts.get(membership.team_id, 0) + 1

    team_summaries = [
        TeamSummary(
            tenant_id=team.tenant_id,
            team_id=team.team_id,
            name=team.name,
            created_at=team.created_at,
            member_count=member_counts.get(team.team_id, 0),
        )
        for team in sorted(db.teams.values(), key=lambda item: (item.name.lower(), item.team_id))
    ]

    return AdminTeamListResponse(
        tenant_id=principal.tenant_id,
        teams=team_summaries,
    )


@app.get("/v1/admin/teams/{team_id}", response_model=TeamDetailResponse)
async def get_admin_team_detail(
    request: Request,
    team_id: str,
) -> TeamDetailResponse:
    principal = await ensure_user(request)
    require_admin(principal)
    db = await run_in_threadpool(
        app.state.state.app_state_store.load_tenant_db,
        principal.tenant_id,
    )

    team = db.teams.get(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found.")

    members: list[TeamMemberRecord] = []
    memberships = sorted(
        (membership for membership in db.memberships if membership.team_id == team_id),
        key=lambda membership: membership.user_email.lower(),
    )
    for membership in memberships:
        user = db.users.get(membership.user_email)
        members.append(
            TeamMemberRecord(
                tenant_id=membership.tenant_id,
                team_id=membership.team_id,
                user_email=membership.user_email,
                name=user.name if user is not None else None,
                is_admin=user.is_admin if user is not None else False,
                joined_at=membership.joined_at,
            )
        )

    repositories = sorted(
        (
            repo_def for repo_def in db.repo_definitions.values()
            if team_id in repo_def.team_ids and repo_def.archived_at is None
        ),
        key=lambda repo_def: ((repo_def.name or repo_def.endpoint).lower(), repo_def.repo_def_id),
    )

    return TeamDetailResponse(
        tenant_id=principal.tenant_id,
        team=team,
        members=members,
        repositories=repositories,
    )


@app.get("/v1/admin/repos", response_model=RepositoryDefinitionListResponse)
async def list_admin_repo_definitions(
    request: Request,
    include_archived: bool = False,
) -> RepositoryDefinitionListResponse:
    principal = await ensure_user(request)
    require_admin(principal)
    repo_defs = await run_in_threadpool(
        app.state.state.app_state_store.list_repo_definitions,
        principal.tenant_id,
        include_archived,
    )
    return RepositoryDefinitionListResponse(
        tenant_id=principal.tenant_id,
        repo_definitions=sorted(
            repo_defs,
            key=lambda repo_def: ((repo_def.name or repo_def.endpoint).lower(), repo_def.repo_def_id),
        ),
    )


@app.post("/v1/teams/{team_id}/members", response_model=TeamMemberAddResponse)
async def add_team_member(
    request: Request,
    team_id: str,
    body: TeamMemberAddRequest,
) -> TeamMemberAddResponse:
    principal = await ensure_user(request)
    require_admin(principal)
    tenant_id = principal.tenant_id
    try:
        return await run_in_threadpool(
            app.state.state.app_state_store.add_team_membership,
            tenant_id,
            team_id,
            normalize_email_or_400(body.user_email),
        )
    except KeyError as error:
        detail = str(error).strip("'")
        if detail.startswith("User "):
            raise HTTPException(status_code=404, detail="User not found.") from error
        if detail.startswith("Team "):
            raise HTTPException(status_code=404, detail="Team not found.") from error
        raise HTTPException(status_code=400, detail=detail) from error


@app.delete("/v1/teams/{team_id}/members/{user_email}", response_model=TeamMemberRemoveResponse)
async def remove_team_member(
    request: Request,
    team_id: str,
    user_email: str,
) -> TeamMemberRemoveResponse:
    principal = await ensure_user(request)
    require_admin(principal)
    tenant_id = principal.tenant_id
    try:
        return await run_in_threadpool(
            app.state.state.app_state_store.remove_team_membership,
            tenant_id,
            team_id,
            normalize_email_or_400(user_email),
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Membership not found.") from error


@app.get("/v1/users/me", response_model=UserMeResponse)
async def get_me(request: Request) -> UserMeResponse:
    principal = await ensure_user(request)
    me = await run_in_threadpool(
        app.state.state.app_state_store.me,
        principal.tenant_id,
        principal.email,
    )
    if me is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return me


@app.post("/v1/users", response_model=UserCreateResponse)
async def create_user(
    request: Request,
    body: UserCreateRequest,
) -> UserCreateResponse:
    if app.state.state.request_auth_backend.kind == "header":
        tenant_id = get_requested_tenant_id(request)
        principal_email = request.headers.get("X-User-Email")
        if not principal_email:
            raise HTTPException(status_code=401, detail="Missing X-User-Email header.")
        principal_email = normalize_email_or_400(principal_email)

        db = app.state.state.app_state_store.load_tenant_db(tenant_id)
        is_bootstrap = not any(user.is_admin for user in db.users.values())
        if not is_bootstrap:
            existing_principal = app.state.state.app_state_store.get_user(
                tenant_id,
                principal_email,
            )
            if not existing_principal or not existing_principal.is_admin:
                raise HTTPException(status_code=403, detail="Admin access required.")
    else:
        principal = await ensure_user(request)
        require_admin(principal)
        tenant_id = principal.tenant_id

    email = normalize_email_or_400(body.email)

    user = User(
        tenant_id=tenant_id,
        email=email,
        name=body.name.strip() if body.name else None,
        is_admin=body.is_admin,
    )
    await run_in_threadpool(
        app.state.state.app_state_store.upsert_user,
        user,
    )
    return UserCreateResponse(
        tenant_id=user.tenant_id,
        email=user.email,
        name=user.name,
        is_admin=user.is_admin,
        created_at=user.created_at,
    )


# ---------------------------------------------------------------------------
# Repository Definition Endpoints
# ---------------------------------------------------------------------------


@app.post("/v1/repos", response_model=RepositoryDefinitionCreateResponse)
async def create_repo_definition(
    request: Request,
    body: RepositoryDefinitionCreateRequest,
) -> RepositoryDefinitionCreateResponse:
    principal = await ensure_user(request)
    require_admin(principal)
    team_ids = normalize_team_ids(principal.tenant_id, body.team_ids)
    stored_secret_ref: str | None = None
    if body.adapter.access_secret is not None:
        try:
            stored_secret_ref = app.state.state.secret_store.store_secret(
                tenant_id=principal.tenant_id,
                secret=body.adapter.access_secret,
            )
        except SecretStoreError as error:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to store repository access secret: {error}",
            ) from error

    adapter = RepositoryAdapter(
        kind=body.adapter.kind.strip().lower(),
        auth_kind=body.adapter.auth_kind.strip().lower() or "public",
        access_secret_ref=stored_secret_ref,
        credential_ref=(
            body.adapter.credential_ref
            if stored_secret_ref is None
            else None
        ),
    )
    repo_def = RepositoryDefinition(
        tenant_id=principal.tenant_id,
        repo_def_id=new_id("repo"),
        name=normalize_repo_name(body.name),
        endpoint=normalize_repo_endpoint(body.endpoint),
        adapter=adapter,
        team_ids=team_ids,
    )
    try:
        await run_in_threadpool(
            app.state.state.app_state_store.create_repo_definition,
            repo_def,
        )
    except Exception:
        if stored_secret_ref is not None:
            try:
                app.state.state.secret_store.delete_secret(
                    tenant_id=principal.tenant_id,
                    secret_ref=stored_secret_ref,
                )
            except SecretStoreError:
                logger.warning(
                    "Failed to roll back stored repository secret after repo creation failure: tenant_id=%s repo_def_id=%s",
                    principal.tenant_id,
                    repo_def.repo_def_id,
                )
        raise
    return RepositoryDefinitionCreateResponse(
        tenant_id=repo_def.tenant_id,
        repo_def_id=repo_def.repo_def_id,
        name=repo_def.name,
        endpoint=repo_def.endpoint,
        adapter=repo_def.adapter,
        team_ids=repo_def.team_ids,
        created_at=repo_def.created_at,
    )


@app.get("/v1/repos", response_model=RepositoryDefinitionListResponse)
async def list_repo_definitions(request: Request) -> RepositoryDefinitionListResponse:
    principal = await ensure_user(request)
    if principal.is_admin:
        repo_defs = await run_in_threadpool(
            app.state.state.app_state_store.list_repo_definitions,
            principal.tenant_id,
        )
    else:
        repo_defs = await run_in_threadpool(
            app.state.state.app_state_store.list_repo_definitions_for_principal,
            principal.tenant_id,
            principal.email,
        )
    return RepositoryDefinitionListResponse(
        tenant_id=principal.tenant_id,
        repo_definitions=sorted(
            repo_defs,
            key=lambda repo_def: ((repo_def.name or repo_def.endpoint).lower(), repo_def.repo_def_id),
        ),
    )


@app.get("/v1/repos/{repo_def_id}", response_model=RepositoryDefinition)
async def get_repo_definition(
    request: Request,
    repo_def_id: str,
) -> RepositoryDefinition:
    principal = await ensure_user(request)
    repo_def = await run_in_threadpool(
        app.state.state.app_state_store.get_repo_definition,
        principal.tenant_id,
        repo_def_id,
    )
    if repo_def is None:
        raise HTTPException(status_code=404, detail="Repository definition not found.")
    ensure_repo_access(principal, repo_def)
    return repo_def


@app.patch(
    "/v1/repos/{repo_def_id}/teams",
    response_model=RepositoryDefinitionUpdateTeamsResponse,
)
async def update_repo_definition_teams(
    request: Request,
    repo_def_id: str,
    body: RepositoryDefinitionUpdateTeamsRequest,
) -> RepositoryDefinitionUpdateTeamsResponse:
    principal = await ensure_user(request)
    require_admin(principal)
    updated_repo = await apply_repo_definition_update(
        principal=principal,
        repo_def_id=repo_def_id,
        body=RepositoryDefinitionUpdateRequest(team_ids=body.team_ids),
    )
    return RepositoryDefinitionUpdateTeamsResponse(
        tenant_id=updated_repo.tenant_id,
        repo_def_id=updated_repo.repo_def_id,
        team_ids=updated_repo.team_ids,
    )


@app.patch("/v1/repos/{repo_def_id}", response_model=RepositoryDefinition)
async def update_repo_definition(
    request: Request,
    repo_def_id: str,
    body: RepositoryDefinitionUpdateRequest,
) -> RepositoryDefinition:
    principal = await ensure_user(request)
    require_admin(principal)
    return await apply_repo_definition_update(
        principal=principal,
        repo_def_id=repo_def_id,
        body=body,
    )


@app.delete("/v1/repos/{repo_def_id}", response_model=RepositoryDefinition)
async def archive_repo_definition(
    request: Request,
    repo_def_id: str,
) -> RepositoryDefinition:
    principal = await ensure_user(request)
    require_admin(principal)
    try:
        return await run_in_threadpool(
            app.state.state.app_state_store.archive_repo_definition,
            principal.tenant_id,
            repo_def_id,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Repository definition not found.") from error


@app.post("/v1/repos/{repo_def_id}/restore", response_model=RepositoryDefinition)
async def restore_repo_definition(
    request: Request,
    repo_def_id: str,
) -> RepositoryDefinition:
    principal = await ensure_user(request)
    require_admin(principal)
    try:
        return await run_in_threadpool(
            app.state.state.app_state_store.restore_repo_definition,
            principal.tenant_id,
            repo_def_id,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Repository definition not found.") from error


# ---------------------------------------------------------------------------
# Checkout Endpoints
# ---------------------------------------------------------------------------


@app.post("/v1/repos/{repo_def_id}/checkouts", response_model=CheckoutCreateResponse)
async def create_checkout(
    request: Request,
    repo_def_id: str,
    body: CheckoutCreateRequest,
) -> CheckoutCreateResponse:
    principal = await ensure_user(request)
    tenant_id = principal.tenant_id

    # Resolve repo definition and validate access
    repo_def = app.state.state.app_state_store.get_repo_definition(tenant_id, repo_def_id)
    if repo_def is None:
        raise HTTPException(status_code=404, detail="Repository definition not found.")
    ensure_repo_access(principal, repo_def)
    ensure_repo_is_active(repo_def)

    # Import via workspace service using the repo def's adapter
    try:
        artifacts = await run_in_threadpool(
            app.state.state.workspace_import_service.import_from_repo_definition,
            tenant_id=tenant_id,
            repo_def_id=repo_def_id,
            ref=body.ref,
            endpoint=repo_def.endpoint,
            adapter=repo_def.adapter,
        )
    except WorkspaceImportError as error:
        raise HTTPException(
            status_code=400,
            detail=f"Checkout failed: {error}",
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"Checkout failed: {error}",
        ) from error

    # Register snapshot in workspace store
    await run_in_threadpool(
        app.state.state.workspace_store.register_snapshot,
        tenant_id=tenant_id,
        snapshot=artifacts.snapshot_ref,
    )

    # Create checkout record
    checkout = Checkout(
        tenant_id=tenant_id,
        checkout_id=new_id("chk"),
        repo_def_id=repo_def_id,
        branch=artifacts.snapshot_ref.ref,
        commit_sha=artifacts.snapshot_ref.commit_sha,
        workspace_id=artifacts.snapshot_ref.workspace_id,
        snapshot_id=artifacts.snapshot_ref.snapshot_id,
    )
    await run_in_threadpool(
        app.state.state.app_state_store.create_checkout,
        checkout,
    )

    return CheckoutCreateResponse(
        tenant_id=checkout.tenant_id,
        checkout_id=checkout.checkout_id,
        repo_def_id=checkout.repo_def_id,
        branch=checkout.branch,
        commit_sha=checkout.commit_sha,
        run_timestamp=checkout.run_timestamp,
        workspace_id=checkout.workspace_id,
        snapshot_id=checkout.snapshot_id,
    )


@app.get("/v1/repos/{repo_def_id}/checkouts", response_model=CheckoutListResponse)
async def list_checkouts_for_repo(
    request: Request,
    repo_def_id: str,
) -> CheckoutListResponse:
    principal = await ensure_user(request)
    tenant_id = principal.tenant_id
    repo_def = await run_in_threadpool(
        app.state.state.app_state_store.get_repo_definition,
        tenant_id,
        repo_def_id,
    )
    if repo_def is None:
        raise HTTPException(status_code=404, detail="Repository definition not found.")
    ensure_repo_access(principal, repo_def)

    checkouts = await run_in_threadpool(
        app.state.state.app_state_store.list_checkouts_for_repo,
        tenant_id,
        repo_def_id,
    )
    return CheckoutListResponse(
        tenant_id=tenant_id,
        checkouts=sorted(checkouts, key=lambda checkout: checkout.run_timestamp, reverse=True),
    )


@app.get("/v1/checkouts/{checkout_id}", response_model=Checkout)
async def get_checkout(
    request: Request,
    checkout_id: str,
) -> Checkout:
    principal = await ensure_user(request)
    checkout = await run_in_threadpool(
        app.state.state.app_state_store.get_checkout,
        principal.tenant_id,
        checkout_id,
    )
    if checkout is None:
        raise HTTPException(status_code=404, detail="Checkout not found.")
    repo_def = await run_in_threadpool(
        app.state.state.app_state_store.get_repo_definition,
        principal.tenant_id,
        checkout.repo_def_id,
    )
    if repo_def is None:
        raise HTTPException(status_code=404, detail="Repository definition not found.")
    ensure_repo_access(principal, repo_def)
    return checkout
