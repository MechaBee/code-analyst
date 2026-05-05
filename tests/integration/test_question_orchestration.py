from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import uuid4

import boto3
import httpx
import pytest
from code_analyst_contracts import ConversationCreateRequest
from control_plane_app.app_state_store import AppStateStore
from control_plane_app.main import app as control_plane_app
from control_plane_app.main import AppState as ControlPlaneAppState
from control_plane_app.object_store import ObjectStore as ControlPlaneObjectStore
from control_plane_app.question_orchestrator import QuestionOrchestrator
from control_plane_app.sandbox_supervisor_client import SandboxSupervisorClient
from control_plane_app.state_store import (
    ApprovalStateStore,
    ConversationStateStore,
    RunStateStore,
    WorkspaceStateStore,
)
from control_plane_app.workspace_imports import WorkspaceImportService
from fastapi.testclient import TestClient
from moto import mock_aws
from sandbox_supervisor_app.analysis_adapter import DeterministicAnalysisAdapter
from sandbox_supervisor_app.main import app as sandbox_supervisor_app
from sandbox_supervisor_app.main import AppState as SandboxSupervisorAppState
from sandbox_supervisor_app.object_store import ObjectStore as SandboxObjectStore
from sandbox_supervisor_app.workspace_materializer import WorkspaceMaterializer

from control_plane_app.config import Settings as ControlPlaneSettings
from sandbox_supervisor_app.config import Settings as SandboxSupervisorSettings


@pytest.fixture()
def sample_git_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "sample-repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Question Flow Repo\n")
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "service.py").write_text(
        "def answer() -> str:\n"
        "    return 'forty-two'\n"
    )

    run_git(["init", "-b", "main"], cwd=repo_dir)
    run_git(["config", "user.name", "Code Analyst"], cwd=repo_dir)
    run_git(["config", "user.email", "code-analyst@example.com"], cwd=repo_dir)
    run_git(["add", "."], cwd=repo_dir)
    run_git(["commit", "-m", "Initial commit"], cwd=repo_dir)
    return repo_dir


def run_git(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@mock_aws
def test_question_flow_calls_sandbox_supervisor(
    tmp_path: Path,
    sample_git_repo: Path,
) -> None:
    bucket_name = "code-analyst-question-flow"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    control_plane_settings = ControlPlaneSettings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_tmp_dir=str(tmp_path / "control-plane-tmp"),
        sandbox_supervisor_url="http://sandbox-supervisor",
    )
    sandbox_settings = SandboxSupervisorSettings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_root_dir=str(tmp_path / "sandboxes"),
    )

    supervisor_state = SandboxSupervisorAppState()
    supervisor_state.sessions = {}
    supervisor_state.materializer = WorkspaceMaterializer(
        settings=sandbox_settings,
        object_store=SandboxObjectStore(sandbox_settings),
    )
    supervisor_state.analysis_adapter = DeterministicAnalysisAdapter()
    sandbox_supervisor_app.state.state = supervisor_state

    sandbox_transport = httpx.ASGITransport(app=sandbox_supervisor_app)
    control_plane_state = ControlPlaneAppState()
    control_plane_state.object_store = ControlPlaneObjectStore(control_plane_settings)
    control_plane_state.workspace_store = WorkspaceStateStore(control_plane_state.object_store)
    control_plane_state.conversation_store = ConversationStateStore(
        control_plane_state.object_store
    )
    control_plane_state.run_store = RunStateStore(control_plane_state.object_store)
    control_plane_state.approval_store = ApprovalStateStore(control_plane_state.object_store)
    control_plane_state.app_state_store = AppStateStore(control_plane_state.object_store)
    control_plane_state.workspace_import_service = WorkspaceImportService(
        settings=control_plane_settings,
        object_store=control_plane_state.object_store,
    )
    control_plane_state.question_orchestrator = QuestionOrchestrator(
        sandbox_client=SandboxSupervisorClient(
            "http://sandbox-supervisor",
            transport=sandbox_transport,
        ),
        conversation_store=control_plane_state.conversation_store,
        run_store=control_plane_state.run_store,
        workspace_store=control_plane_state.workspace_store,
        approval_store=control_plane_state.approval_store,
        app_state_store=control_plane_state.app_state_store,
    )
    control_plane_app.state.state = control_plane_state

    client = TestClient(
        control_plane_app,
        headers={
            "X-Tenant-Id": "tenant_test",
            "X-User-Email": "test@test.com",
        },
    )

    import_response = client.post(
        "/v1/workspaces/imports/github",
        json={
            "tenant_id": "tenant_test",
            "repo_url": str(sample_git_repo),
            "ref": "main",
            "github_credential_ref": "public",
        },
    )
    assert import_response.status_code == 200
    snapshot_payload = import_response.json()

    # Create conversation directly via store (bypassing repo-scoping auth for legacy import tests)
    conversation_id = f"conv_{uuid4().hex[:12]}"
    control_plane_state.conversation_store.create_conversation(
        conversation_id=conversation_id,
        request=ConversationCreateRequest(
            tenant_id="tenant_test",
            repo_def_id="__legacy__",
            workspace_id=snapshot_payload["workspace_id"],
            title="Question flow conversation",
        ),
        principal_email="test@test.com",
        workspace_id=snapshot_payload["workspace_id"],
    )

    question_response = client.post(
        f"/v1/conversations/{conversation_id}/questions",
        json={
            "message": "Summarize the workspace that was imported.",
            "resume_sandbox": True,
        },
    )
    assert question_response.status_code == 200
    run_payload = question_response.json()
    assert run_payload["status"] == "COMPLETED"

    events_response = client.get(run_payload["events_url"])
    assert events_response.status_code == 200
    body = events_response.text
    assert "event: run.started" in body
    assert "event: run.progress" in body
    assert "event: citation.created" in body
    assert "event: run.completed" in body
    assert "Created sandbox session" in body
    assert "Question Flow Repo" in body
    assert "answer()" in body
    assert "forty-two" in body

    run_state = control_plane_app.state.state.run_store.get_run(run_payload["run_id"])
    assert run_state is not None
    assert run_state.sandbox_id is not None
    assert run_state.answer is not None
    assert len(run_state.answer.citations) == 2
    assert {citation.path for citation in run_state.answer.citations} == {
        "README.md",
        "src/service.py",
    }
    assert "Question Flow Repo" in run_state.answer.answer_markdown
    assert "answer()" in run_state.answer.answer_markdown
    assert "forty-two" in run_state.answer.answer_markdown
    conversation_head = control_plane_app.state.state.conversation_store.get_conversation(
        conversation_id
    )
    assert conversation_head is not None
    assert conversation_head.active_sandbox_id == run_state.sandbox_id
    assert conversation_head.latest_run_id == run_payload["run_id"]
    assert len(sandbox_supervisor_app.state.state.sessions) == 1


@mock_aws
def test_question_flow_disposes_sandbox_when_not_resuming(
    tmp_path: Path,
    sample_git_repo: Path,
) -> None:
    bucket_name = "code-analyst-dispose-test"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    control_plane_settings = ControlPlaneSettings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_tmp_dir=str(tmp_path / "control-plane-tmp"),
        sandbox_supervisor_url="http://sandbox-supervisor",
    )
    sandbox_settings = SandboxSupervisorSettings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_root_dir=str(tmp_path / "sandboxes"),
    )

    supervisor_state = SandboxSupervisorAppState()
    supervisor_state.sessions = {}
    supervisor_state.materializer = WorkspaceMaterializer(
        settings=sandbox_settings,
        object_store=SandboxObjectStore(sandbox_settings),
    )
    supervisor_state.analysis_adapter = DeterministicAnalysisAdapter()
    sandbox_supervisor_app.state.state = supervisor_state

    sandbox_transport = httpx.ASGITransport(app=sandbox_supervisor_app)
    control_plane_state = ControlPlaneAppState()
    control_plane_state.object_store = ControlPlaneObjectStore(control_plane_settings)
    control_plane_state.workspace_store = WorkspaceStateStore(control_plane_state.object_store)
    control_plane_state.conversation_store = ConversationStateStore(
        control_plane_state.object_store
    )
    control_plane_state.run_store = RunStateStore(control_plane_state.object_store)
    control_plane_state.approval_store = ApprovalStateStore(control_plane_state.object_store)
    control_plane_state.app_state_store = AppStateStore(control_plane_state.object_store)
    control_plane_state.workspace_import_service = WorkspaceImportService(
        settings=control_plane_settings,
        object_store=control_plane_state.object_store,
    )
    control_plane_state.question_orchestrator = QuestionOrchestrator(
        sandbox_client=SandboxSupervisorClient(
            "http://sandbox-supervisor",
            transport=sandbox_transport,
        ),
        conversation_store=control_plane_state.conversation_store,
        run_store=control_plane_state.run_store,
        workspace_store=control_plane_state.workspace_store,
        approval_store=control_plane_state.approval_store,
        app_state_store=control_plane_state.app_state_store,
    )
    control_plane_app.state.state = control_plane_state

    client = TestClient(
        control_plane_app,
        headers={
            "X-Tenant-Id": "tenant_test",
            "X-User-Email": "test@test.com",
        },
    )

    import_response = client.post(
        "/v1/workspaces/imports/github",
        json={
            "tenant_id": "tenant_test",
            "repo_url": str(sample_git_repo),
            "ref": "main",
            "github_credential_ref": "public",
        },
    )
    assert import_response.status_code == 200
    snapshot_payload = import_response.json()

    # Create conversation directly via store (bypassing repo-scoping auth for legacy import tests)
    conversation_id = f"conv_{uuid4().hex[:12]}"
    control_plane_state.conversation_store.create_conversation(
        conversation_id=conversation_id,
        request=ConversationCreateRequest(
            tenant_id="tenant_test",
            repo_def_id="__legacy__",
            workspace_id=snapshot_payload["workspace_id"],
            title="Dispose test conversation",
        ),
        principal_email="test@test.com",
        workspace_id=snapshot_payload["workspace_id"],
    )

    question_response = client.post(
        f"/v1/conversations/{conversation_id}/questions",
        json={
            "message": "Summarize the workspace that was imported.",
            "resume_sandbox": False,
        },
    )
    assert question_response.status_code == 200
    run_payload = question_response.json()
    assert run_payload["status"] == "COMPLETED"

    # The sandbox should have been disposed because resume_sandbox=False
    assert len(sandbox_supervisor_app.state.state.sessions) == 0


@mock_aws
def test_archived_repo_conversation_can_still_execute_questions(
    tmp_path: Path,
    sample_git_repo: Path,
) -> None:
    bucket_name = "code-analyst-archived-repo-question-flow"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    control_plane_settings = ControlPlaneSettings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_tmp_dir=str(tmp_path / "control-plane-tmp"),
        sandbox_supervisor_url="http://sandbox-supervisor",
    )
    sandbox_settings = SandboxSupervisorSettings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_root_dir=str(tmp_path / "sandboxes"),
    )

    supervisor_state = SandboxSupervisorAppState()
    supervisor_state.sessions = {}
    supervisor_state.materializer = WorkspaceMaterializer(
        settings=sandbox_settings,
        object_store=SandboxObjectStore(sandbox_settings),
    )
    supervisor_state.analysis_adapter = DeterministicAnalysisAdapter()
    sandbox_supervisor_app.state.state = supervisor_state

    sandbox_transport = httpx.ASGITransport(app=sandbox_supervisor_app)
    control_plane_state = ControlPlaneAppState()
    control_plane_state.object_store = ControlPlaneObjectStore(control_plane_settings)
    control_plane_state.workspace_store = WorkspaceStateStore(control_plane_state.object_store)
    control_plane_state.conversation_store = ConversationStateStore(
        control_plane_state.object_store
    )
    control_plane_state.run_store = RunStateStore(control_plane_state.object_store)
    control_plane_state.approval_store = ApprovalStateStore(control_plane_state.object_store)
    control_plane_state.app_state_store = AppStateStore(control_plane_state.object_store)
    control_plane_state.workspace_import_service = WorkspaceImportService(
        settings=control_plane_settings,
        object_store=control_plane_state.object_store,
    )
    control_plane_state.question_orchestrator = QuestionOrchestrator(
        sandbox_client=SandboxSupervisorClient(
            "http://sandbox-supervisor",
            transport=sandbox_transport,
        ),
        conversation_store=control_plane_state.conversation_store,
        run_store=control_plane_state.run_store,
        workspace_store=control_plane_state.workspace_store,
        approval_store=control_plane_state.approval_store,
        app_state_store=control_plane_state.app_state_store,
    )
    control_plane_app.state.state = control_plane_state

    client = TestClient(control_plane_app)
    admin_headers = {
        "X-Tenant-Id": "tenant_test",
        "X-User-Email": "admin@test.com",
    }
    member_headers = {
        "X-Tenant-Id": "tenant_test",
        "X-User-Email": "member@test.com",
    }

    client.post(
        "/v1/users",
        json={"email": "admin@test.com", "name": "Admin", "is_admin": True},
        headers=admin_headers,
    )
    team_resp = client.post(
        "/v1/teams",
        json={"name": "Dev Team"},
        headers=admin_headers,
    )
    team_id = team_resp.json()["team_id"]
    client.post(
        "/v1/users",
        json={"email": "member@test.com", "name": "Member", "is_admin": False},
        headers=admin_headers,
    )
    client.post(
        f"/v1/teams/{team_id}/members",
        json={"user_email": "member@test.com"},
        headers=admin_headers,
    )

    repo_resp = client.post(
        "/v1/repos",
        json={
            "name": "Question Repo",
            "endpoint": str(sample_git_repo),
            "adapter": {"kind": "github", "credential_ref": "public"},
            "team_ids": [team_id],
        },
        headers=admin_headers,
    )
    assert repo_resp.status_code == 200
    repo_def_id = repo_resp.json()["repo_def_id"]

    checkout_resp = client.post(
        f"/v1/repos/{repo_def_id}/checkouts",
        json={"repo_def_id": repo_def_id, "ref": "main"},
        headers=member_headers,
    )
    assert checkout_resp.status_code == 200
    checkout_payload = checkout_resp.json()

    conversation_resp = client.post(
        "/v1/conversations",
        json={
            "tenant_id": "tenant_test",
            "repo_def_id": repo_def_id,
            "checkout_id": checkout_payload["checkout_id"],
            "workspace_id": checkout_payload["workspace_id"],
            "title": "Archived repo conversation",
        },
        headers=member_headers,
    )
    assert conversation_resp.status_code == 200
    conversation_id = conversation_resp.json()["conversation_id"]

    archive_resp = client.delete(f"/v1/repos/{repo_def_id}", headers=admin_headers)
    assert archive_resp.status_code == 200
    assert archive_resp.json()["archived_at"] is not None

    question_resp = client.post(
        f"/v1/conversations/{conversation_id}/questions",
        json={
            "message": "What does the sample repository return?",
            "resume_sandbox": True,
        },
        headers=member_headers,
    )
    assert question_resp.status_code == 200
    run_payload = question_resp.json()
    assert run_payload["status"] == "COMPLETED"

    run_state = control_plane_app.state.state.run_store.get_run(run_payload["run_id"])
    assert run_state is not None
    assert run_state.answer is not None
    assert "forty-two" in run_state.answer.answer_markdown

    run_state = control_plane_app.state.state.run_store.get_run(run_payload["run_id"])
    assert run_state is not None
    assert run_state.sandbox_id is not None
    assert run_state.answer is not None

    conversation_head = control_plane_app.state.state.conversation_store.get_conversation(
        conversation_id
    )
    assert conversation_head is not None
    assert conversation_head.active_sandbox_id == run_state.sandbox_id


@mock_aws
def test_question_flow_requires_approval_and_approves(
    tmp_path: Path,
    sample_git_repo: Path,
) -> None:
    bucket_name = "code-analyst-approval-test"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    control_plane_settings = ControlPlaneSettings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_tmp_dir=str(tmp_path / "control-plane-tmp"),
        sandbox_supervisor_url="http://sandbox-supervisor",
    )
    sandbox_settings = SandboxSupervisorSettings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_root_dir=str(tmp_path / "sandboxes"),
    )

    supervisor_state = SandboxSupervisorAppState()
    supervisor_state.sessions = {}
    supervisor_state.materializer = WorkspaceMaterializer(
        settings=sandbox_settings,
        object_store=SandboxObjectStore(sandbox_settings),
    )
    supervisor_state.analysis_adapter = DeterministicAnalysisAdapter()
    sandbox_supervisor_app.state.state = supervisor_state

    sandbox_transport = httpx.ASGITransport(app=sandbox_supervisor_app)
    control_plane_state = ControlPlaneAppState()
    control_plane_state.object_store = ControlPlaneObjectStore(control_plane_settings)
    control_plane_state.workspace_store = WorkspaceStateStore(control_plane_state.object_store)
    control_plane_state.conversation_store = ConversationStateStore(
        control_plane_state.object_store
    )
    control_plane_state.run_store = RunStateStore(control_plane_state.object_store)
    control_plane_state.approval_store = ApprovalStateStore(control_plane_state.object_store)
    control_plane_state.app_state_store = AppStateStore(control_plane_state.object_store)
    control_plane_state.workspace_import_service = WorkspaceImportService(
        settings=control_plane_settings,
        object_store=control_plane_state.object_store,
    )
    control_plane_state.question_orchestrator = QuestionOrchestrator(
        sandbox_client=SandboxSupervisorClient(
            "http://sandbox-supervisor",
            transport=sandbox_transport,
        ),
        conversation_store=control_plane_state.conversation_store,
        run_store=control_plane_state.run_store,
        workspace_store=control_plane_state.workspace_store,
        approval_store=control_plane_state.approval_store,
        app_state_store=control_plane_state.app_state_store,
    )
    control_plane_app.state.state = control_plane_state

    client = TestClient(
        control_plane_app,
        headers={
            "X-Tenant-Id": "tenant_test",
            "X-User-Email": "test@test.com",
        },
    )

    import_response = client.post(
        "/v1/workspaces/imports/github",
        json={
            "tenant_id": "tenant_test",
            "repo_url": str(sample_git_repo),
            "ref": "main",
            "github_credential_ref": "public",
        },
    )
    assert import_response.status_code == 200
    snapshot_payload = import_response.json()

    # Create conversation directly via store (bypassing repo-scoping auth for legacy import tests)
    conversation_id = f"conv_{uuid4().hex[:12]}"
    control_plane_state.conversation_store.create_conversation(
        conversation_id=conversation_id,
        request=ConversationCreateRequest(
            tenant_id="tenant_test",
            repo_def_id="__legacy__",
            workspace_id=snapshot_payload["workspace_id"],
            title="Approval flow conversation",
        ),
        principal_email="test@test.com",
        workspace_id=snapshot_payload["workspace_id"],
    )

    # Ask a question with approval_policy=required
    question_response = client.post(
        f"/v1/conversations/{conversation_id}/questions",
        json={
            "message": "Summarize the workspace that was imported.",
            "resume_sandbox": False,
            "approval_policy": "required",
        },
    )
    assert question_response.status_code == 200
    run_payload = question_response.json()
    assert run_payload["status"] == "PENDING_APPROVAL"
    run_id = run_payload["run_id"]

    # Run should be pending approval, no sandbox created yet
    run_state = control_plane_app.state.state.run_store.get_run(run_id)
    assert run_state is not None
    assert run_state.status.value == "PENDING_APPROVAL"
    assert run_state.pending_approval_id is not None
    assert run_state.sandbox_id is None

    # Events should include approval.required
    events_response = client.get(run_payload["events_url"])
    assert events_response.status_code == 200
    body = events_response.text
    assert "event: approval.required" in body

    # Resolve the approval with "approve"
    approval_id = run_state.pending_approval_id
    approval_response = client.post(
        f"/v1/runs/{run_id}/approvals/{approval_id}",
        json={"decision": "approve", "reason": "Looks good"},
    )
    assert approval_response.status_code == 200
    approval_payload = approval_response.json()
    assert approval_payload["status"] == "COMPLETED"

    # Run should now be completed
    run_state = control_plane_app.state.state.run_store.get_run(run_id)
    assert run_state is not None
    assert run_state.status.value == "COMPLETED"
    assert run_state.answer is not None
    assert len(run_state.answer.citations) == 2

    # Sandbox should have been disposed because resume_sandbox=False
    assert len(sandbox_supervisor_app.state.state.sessions) == 0


@mock_aws
def test_question_flow_requires_approval_and_denies(
    tmp_path: Path,
    sample_git_repo: Path,
) -> None:
    bucket_name = "code-analyst-approval-deny-test"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    control_plane_settings = ControlPlaneSettings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_tmp_dir=str(tmp_path / "control-plane-tmp"),
        sandbox_supervisor_url="http://sandbox-supervisor",
    )
    sandbox_settings = SandboxSupervisorSettings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_root_dir=str(tmp_path / "sandboxes"),
    )

    supervisor_state = SandboxSupervisorAppState()
    supervisor_state.sessions = {}
    supervisor_state.materializer = WorkspaceMaterializer(
        settings=sandbox_settings,
        object_store=SandboxObjectStore(sandbox_settings),
    )
    supervisor_state.analysis_adapter = DeterministicAnalysisAdapter()
    sandbox_supervisor_app.state.state = supervisor_state

    sandbox_transport = httpx.ASGITransport(app=sandbox_supervisor_app)
    control_plane_state = ControlPlaneAppState()
    control_plane_state.object_store = ControlPlaneObjectStore(control_plane_settings)
    control_plane_state.workspace_store = WorkspaceStateStore(control_plane_state.object_store)
    control_plane_state.conversation_store = ConversationStateStore(
        control_plane_state.object_store
    )
    control_plane_state.run_store = RunStateStore(control_plane_state.object_store)
    control_plane_state.approval_store = ApprovalStateStore(control_plane_state.object_store)
    control_plane_state.app_state_store = AppStateStore(control_plane_state.object_store)
    control_plane_state.workspace_import_service = WorkspaceImportService(
        settings=control_plane_settings,
        object_store=control_plane_state.object_store,
    )
    control_plane_state.question_orchestrator = QuestionOrchestrator(
        sandbox_client=SandboxSupervisorClient(
            "http://sandbox-supervisor",
            transport=sandbox_transport,
        ),
        conversation_store=control_plane_state.conversation_store,
        run_store=control_plane_state.run_store,
        workspace_store=control_plane_state.workspace_store,
        approval_store=control_plane_state.approval_store,
        app_state_store=control_plane_state.app_state_store,
    )
    control_plane_app.state.state = control_plane_state

    client = TestClient(
        control_plane_app,
        headers={
            "X-Tenant-Id": "tenant_test",
            "X-User-Email": "test@test.com",
        },
    )

    import_response = client.post(
        "/v1/workspaces/imports/github",
        json={
            "tenant_id": "tenant_test",
            "repo_url": str(sample_git_repo),
            "ref": "main",
            "github_credential_ref": "public",
        },
    )
    assert import_response.status_code == 200
    snapshot_payload = import_response.json()

    # Create conversation directly via store (bypassing repo-scoping auth for legacy import tests)
    conversation_id = f"conv_{uuid4().hex[:12]}"
    control_plane_state.conversation_store.create_conversation(
        conversation_id=conversation_id,
        request=ConversationCreateRequest(
            tenant_id="tenant_test",
            repo_def_id="__legacy__",
            workspace_id=snapshot_payload["workspace_id"],
            title="Approval deny conversation",
        ),
        principal_email="test@test.com",
        workspace_id=snapshot_payload["workspace_id"],
    )

    question_response = client.post(
        f"/v1/conversations/{conversation_id}/questions",
        json={
            "message": "Summarize the workspace that was imported.",
            "resume_sandbox": False,
            "approval_policy": "required",
        },
    )
    assert question_response.status_code == 200
    run_payload = question_response.json()
    assert run_payload["status"] == "PENDING_APPROVAL"
    run_id = run_payload["run_id"]

    run_state = control_plane_app.state.state.run_store.get_run(run_id)
    assert run_state is not None
    approval_id = run_state.pending_approval_id
    assert approval_id is not None

    # Resolve with "deny"
    approval_response = client.post(
        f"/v1/runs/{run_id}/approvals/{approval_id}",
        json={"decision": "deny", "reason": "Not authorized"},
    )
    assert approval_response.status_code == 200
    approval_payload = approval_response.json()
    assert approval_payload["status"] == "FAILED"

    # Run should be failed, no sandbox created
    run_state = control_plane_app.state.state.run_store.get_run(run_id)
    assert run_state is not None
    assert run_state.status.value == "FAILED"
    assert run_state.sandbox_id is None
    assert run_state.answer is None
    assert len(sandbox_supervisor_app.state.state.sessions) == 0

    # Events should include run.failed
    events_response = client.get(run_payload["events_url"])
    assert events_response.status_code == 200
    body = events_response.text
    assert "event: run.failed" in body
    assert "Not authorized" in body
