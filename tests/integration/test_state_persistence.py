from __future__ import annotations

import subprocess
from pathlib import Path

import boto3
import httpx
import pytest
from control_plane_app.config import Settings as ControlPlaneSettings
from control_plane_app.main import AppState as ControlPlaneAppState
from control_plane_app.main import app as control_plane_app
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
from sandbox_supervisor_app.config import Settings as SandboxSupervisorSettings
from sandbox_supervisor_app.main import AppState as SandboxSupervisorAppState
from sandbox_supervisor_app.main import app as sandbox_supervisor_app
from sandbox_supervisor_app.object_store import ObjectStore as SandboxObjectStore
from sandbox_supervisor_app.workspace_materializer import WorkspaceMaterializer


@pytest.fixture()
def sample_git_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "sample-repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Persistent Repo\n")
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "service.py").write_text(
        "def answer() -> str:\n"
        "    return 'durable-value'\n"
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


def build_control_plane_state(
    *,
    settings: ControlPlaneSettings,
    sandbox_transport: httpx.ASGITransport,
) -> ControlPlaneAppState:
    state = ControlPlaneAppState()
    state.object_store = ControlPlaneObjectStore(settings)
    state.workspace_store = WorkspaceStateStore(state.object_store)
    state.conversation_store = ConversationStateStore(state.object_store)
    state.run_store = RunStateStore(state.object_store)
    state.approval_store = ApprovalStateStore(state.object_store)
    state.workspace_import_service = WorkspaceImportService(
        settings=settings,
        object_store=state.object_store,
    )
    state.question_orchestrator = QuestionOrchestrator(
        sandbox_client=SandboxSupervisorClient(
            settings.sandbox_supervisor_url,
            transport=sandbox_transport,
        ),
        conversation_store=state.conversation_store,
        run_store=state.run_store,
        workspace_store=state.workspace_store,
        approval_store=state.approval_store,
    )
    return state


@mock_aws
def test_state_persists_across_control_plane_restart(
    tmp_path: Path,
    sample_git_repo: Path,
) -> None:
    bucket_name = "code-analyst-persistence"
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
    control_plane_app.state.state = build_control_plane_state(
        settings=control_plane_settings,
        sandbox_transport=sandbox_transport,
    )
    client = TestClient(control_plane_app)

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
    workspace_id = import_response.json()["workspace_id"]

    conversation_response = client.post(
        "/v1/conversations",
        json={
            "tenant_id": "tenant_test",
            "workspace_id": workspace_id,
            "title": "Persistent conversation",
        },
    )
    assert conversation_response.status_code == 200
    conversation_id = conversation_response.json()["conversation_id"]

    first_question_response = client.post(
        f"/v1/conversations/{conversation_id}/questions",
        json={
            "message": "What does answer return?",
            "resume_sandbox": True,
        },
    )
    assert first_question_response.status_code == 200
    first_run_id = first_question_response.json()["run_id"]

    control_plane_app.state.state = build_control_plane_state(
        settings=control_plane_settings,
        sandbox_transport=sandbox_transport,
    )
    restarted_client = TestClient(control_plane_app)

    events_response = restarted_client.get(f"/v1/runs/{first_run_id}/events")
    assert events_response.status_code == 200
    body = events_response.text
    assert "event: run.completed" in body
    assert "durable-value" in body
    assert "src/service.py" in body

    second_question_response = restarted_client.post(
        f"/v1/conversations/{conversation_id}/questions",
        json={
            "message": "Show more detail from service.py",
            "resume_sandbox": True,
        },
    )
    assert second_question_response.status_code == 200
    second_run_id = second_question_response.json()["run_id"]

    run_store = control_plane_app.state.state.run_store
    first_run_state = run_store.get_run(first_run_id)
    second_run_state = run_store.get_run(second_run_id)
    assert first_run_state is not None
    assert second_run_state is not None
    assert first_run_state.sandbox_id == second_run_state.sandbox_id

    conversation_store = control_plane_app.state.state.conversation_store
    conversation_head = conversation_store.get_conversation(conversation_id)
    assert conversation_head is not None
    assert conversation_head.latest_run_id == second_run_id
    assert conversation_head.active_sandbox_id == second_run_state.sandbox_id

    conversation_events = conversation_store.list_events(conversation_id)
    assert [event.type for event in conversation_events] == [
        "user.message.created",
        "assistant.message.created",
        "user.message.created",
        "assistant.message.created",
    ]
