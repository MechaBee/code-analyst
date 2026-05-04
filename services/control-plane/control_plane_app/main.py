from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from uuid import uuid4

from code_analyst_contracts import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
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
    QuestionRequest,
    QuestionResponse,
    RepositoryDefinition,
    RepositoryDefinitionCreateRequest,
    RepositoryDefinitionCreateResponse,
    RepositoryDefinitionListResponse,
    RepositoryDefinitionUpdateTeamsRequest,
    RepositoryDefinitionUpdateTeamsResponse,
    RepositoryAdapter,
    Team,
    TeamCreateRequest,
    TeamCreateResponse,
    TeamListResponse,
    TeamMemberAddRequest,
    TeamMemberAddResponse,
    TeamMemberRemoveResponse,
    TeamMembership,
    User,
    UserCreateRequest,
    UserCreateResponse,
    UserMeResponse,
    WorkspaceImportRequest,
    WorkspaceImportResponse,
)
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from .app_state_store import AppStateStore
from .config import settings
from .object_store import ObjectStore
from .question_orchestrator import QuestionOrchestrator
from .sandbox_supervisor_client import SandboxSupervisorClient
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
    def __init__(self) -> None:
        self.object_store = ObjectStore(settings)
        self.workspace_store = WorkspaceStateStore(self.object_store)
        self.conversation_store = ConversationStateStore(self.object_store)
        self.run_store = RunStateStore(self.object_store)
        self.approval_store = ApprovalStateStore(self.object_store)
        self.app_state_store = AppStateStore(self.object_store)
        self.workspace_import_service = WorkspaceImportService(
            settings=settings,
            object_store=self.object_store,
        )
        self.question_orchestrator = QuestionOrchestrator(
            sandbox_client=SandboxSupervisorClient(
                settings.sandbox_supervisor_url,
                timeout_seconds=settings.sandbox_supervisor_timeout_seconds,
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

    user_teams = app.state.state.app_state_store.list_teams_for_user(
        tenant_id, principal.email
    )
    user_team_ids = {t.team_id for t in user_teams}
    if not any(tid in user_team_ids for tid in repo_def.team_ids):
        raise HTTPException(status_code=403, detail="Access denied to this repository.")

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


def get_principal(request: Request) -> tuple[str, str]:
    """Extract tenant_id and user_email from request headers."""
    tenant_id = request.headers.get("X-Tenant-Id")
    user_email = request.headers.get("X-User-Email")
    if not tenant_id or not user_email:
        raise HTTPException(
            status_code=401,
            detail="Missing X-Tenant-Id or X-User-Email header.",
        )
    return tenant_id, user_email


async def ensure_user(request: Request) -> User:
    tenant_id, user_email = get_principal(request)
    db = app.state.state.app_state_store.load_tenant_db(tenant_id)
    has_admin = any(existing.is_admin for existing in db.users.values())
    user = db.users.get(user_email)
    if user is None:
        user = User(
            tenant_id=tenant_id,
            email=user_email,
            # Self-bootstrap the first effective principal for empty or
            # admin-less tenants so the local UI can recover into the
            # team/repo setup flow.
            is_admin=not has_admin,
        )
        user = await run_in_threadpool(
            app.state.state.app_state_store.upsert_user,
            user,
        )
    elif not has_admin and not user.is_admin:
        user = user.model_copy(update={"is_admin": True})
        user = await run_in_threadpool(
            app.state.state.app_state_store.upsert_user,
            user,
        )
    return user


# ---------------------------------------------------------------------------
# Admin & Identity Endpoints
# ---------------------------------------------------------------------------


@app.post("/v1/teams", response_model=TeamCreateResponse)
async def create_team(
    request: Request,
    body: TeamCreateRequest,
) -> TeamCreateResponse:
    principal = await ensure_user(request)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    tenant_id, _ = get_principal(request)
    team = Team(
        tenant_id=tenant_id,
        team_id=new_id("team"),
        name=body.name,
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
    teams = await run_in_threadpool(
        app.state.state.app_state_store.list_teams,
        principal.tenant_id,
    )
    return TeamListResponse(
        tenant_id=principal.tenant_id,
        teams=teams,
    )


@app.post("/v1/teams/{team_id}/members", response_model=TeamMemberAddResponse)
async def add_team_member(
    request: Request,
    team_id: str,
    body: TeamMemberAddRequest,
) -> TeamMemberAddResponse:
    principal = await ensure_user(request)
    tenant_id = principal.tenant_id
    return await run_in_threadpool(
        app.state.state.app_state_store.add_team_membership,
        tenant_id,
        team_id,
        body.user_email,
    )


@app.delete("/v1/teams/{team_id}/members/{user_email}", response_model=TeamMemberRemoveResponse)
async def remove_team_member(
    request: Request,
    team_id: str,
    user_email: str,
) -> TeamMemberRemoveResponse:
    principal = await ensure_user(request)
    tenant_id = principal.tenant_id
    return await run_in_threadpool(
        app.state.state.app_state_store.remove_team_membership,
        tenant_id,
        team_id,
        user_email,
    )


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
    tenant_id = request.headers.get("X-Tenant-Id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing X-Tenant-Id header.")

    principal = request.headers.get("X-User-Email")
    if not principal:
        raise HTTPException(status_code=401, detail="Missing X-User-Email header.")

    # Bootstrap: if tenant has no admins, allow recovery without an admin check.
    db = app.state.state.app_state_store.load_tenant_db(tenant_id)
    is_bootstrap = not any(user.is_admin for user in db.users.values())

    if not is_bootstrap:
        existing_principal = app.state.state.app_state_store.get_user(tenant_id, principal)
        if not existing_principal or not existing_principal.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required.")

    user = User(
        tenant_id=tenant_id,
        email=body.email,
        name=body.name,
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
    repo_def = RepositoryDefinition(
        tenant_id=principal.tenant_id,
        repo_def_id=new_id("repo"),
        name=body.name,
        endpoint=body.endpoint,
        adapter=body.adapter,
        team_ids=body.team_ids,
    )
    await run_in_threadpool(
        app.state.state.app_state_store.create_repo_definition,
        repo_def,
    )
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
    repo_defs = await run_in_threadpool(
        app.state.state.app_state_store.list_repo_definitions_for_principal,
        principal.tenant_id,
        principal.email,
    )
    return RepositoryDefinitionListResponse(
        tenant_id=principal.tenant_id,
        repo_definitions=repo_defs,
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
    return await run_in_threadpool(
        app.state.state.app_state_store.update_repo_definition_teams,
        principal.tenant_id,
        repo_def_id,
        body.team_ids,
    )


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

    # Check principal has team access
    user_teams = app.state.state.app_state_store.list_teams_for_user(tenant_id, principal.email)
    user_team_ids = {t.team_id for t in user_teams}
    if not any(tid in user_team_ids for tid in repo_def.team_ids):
        raise HTTPException(status_code=403, detail="Access denied to this repository.")

    # Import via workspace service using the repo def's adapter
    try:
        artifacts = await run_in_threadpool(
            app.state.state.workspace_import_service.import_from_repo_definition,
            tenant_id=tenant_id,
            repo_def_id=repo_def_id,
            ref=body.ref,
            endpoint=repo_def.endpoint,
            credential_ref=repo_def.adapter.credential_ref,
        )
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
    checkouts = await run_in_threadpool(
        app.state.state.app_state_store.list_checkouts_for_repo,
        tenant_id,
        repo_def_id,
    )
    return CheckoutListResponse(tenant_id=tenant_id, checkouts=checkouts)


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
    return checkout
