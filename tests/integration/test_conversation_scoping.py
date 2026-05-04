from __future__ import annotations

import subprocess
from pathlib import Path

import boto3
import pytest
from control_plane_app.main import app as control_plane_app
from control_plane_app.main import AppState
from control_plane_app.config import Settings
from control_plane_app.object_store import ObjectStore
from control_plane_app.state_store import (
    ApprovalStateStore,
    ConversationStateStore,
    RunStateStore,
    WorkspaceStateStore,
)
from control_plane_app.app_state_store import AppStateStore
from control_plane_app.workspace_imports import WorkspaceImportService
from control_plane_app.question_orchestrator import QuestionOrchestrator
from control_plane_app.sandbox_supervisor_client import SandboxSupervisorClient
from fastapi.testclient import TestClient
from moto import mock_aws


@pytest.fixture()
def sample_git_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "conversation-scoping-test-repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Conversation Scoping Test\n")
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text(
        "def hello() -> str:\n"
        "    return 'hello-convo'\n"
    )

    _run_git(["init", "-b", "main"], cwd=repo_dir)
    _run_git(["config", "user.name", "Test"], cwd=repo_dir)
    _run_git(["config", "user.email", "test@example.com"], cwd=repo_dir)
    _run_git(["add", "."], cwd=repo_dir)
    _run_git(["commit", "-m", "Initial commit"], cwd=repo_dir)
    return repo_dir


def _run_git(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@mock_aws
def test_conversation_scoping_flow(
    tmp_path: Path,
    sample_git_repo: Path,
) -> None:
    bucket_name = "code-analyst-convo-scoping-test"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    test_settings = Settings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_tmp_dir=str(tmp_path / "control-plane-tmp"),
        sandbox_supervisor_url="http://sandbox-supervisor",
    )

    object_store = ObjectStore(test_settings)
    app_state_store = AppStateStore(object_store)
    state = AppState()
    state.object_store = object_store
    state.workspace_store = WorkspaceStateStore(object_store)
    state.conversation_store = ConversationStateStore(object_store)
    state.run_store = RunStateStore(object_store)
    state.approval_store = ApprovalStateStore(object_store)
    state.app_state_store = app_state_store
    state.workspace_import_service = WorkspaceImportService(
        settings=test_settings,
        object_store=object_store,
    )
    state.question_orchestrator = QuestionOrchestrator(
        sandbox_client=SandboxSupervisorClient(
            test_settings.sandbox_supervisor_url,
            timeout_seconds=10,
        ),
        conversation_store=state.conversation_store,
        run_store=state.run_store,
        workspace_store=state.workspace_store,
        approval_store=state.approval_store,
        app_state_store=app_state_store,
    )
    control_plane_app.state.state = state

    client = TestClient(control_plane_app)
    headers = {
        "X-Tenant-Id": "tenant_test",
        "X-User-Email": "admin@test.com",
    }

    # Bootstrap: create admin user
    client.post(
        "/v1/users",
        json={"email": "admin@test.com", "name": "Admin", "is_admin": True},
        headers=headers,
    )

    # Create team and member
    team_resp = client.post("/v1/teams", json={"name": "Dev Team"}, headers=headers)
    team_id = team_resp.json()["team_id"]

    client.post(
        "/v1/users",
        json={"email": "member@test.com", "name": "Member", "is_admin": False},
        headers=headers,
    )
    client.post(
        f"/v1/teams/{team_id}/members",
        json={"user_email": "member@test.com"},
        headers=headers,
    )

    # Create repo definition
    repo_resp = client.post(
        "/v1/repos",
        json={
            "name": "Test Repo",
            "endpoint": str(sample_git_repo),
            "adapter": {"kind": "github", "credential_ref": "public"},
            "team_ids": [team_id],
        },
        headers=headers,
    )
    repo_def_id = repo_resp.json()["repo_def_id"]

    # Create checkout as member
    member_headers = {
        "X-Tenant-Id": "tenant_test",
        "X-User-Email": "member@test.com",
    }
    checkout_resp = client.post(
        f"/v1/repos/{repo_def_id}/checkouts",
        json={"repo_def_id": repo_def_id, "ref": "main"},
        headers=member_headers,
    )
    checkout_data = checkout_resp.json()
    checkout_id = checkout_data["checkout_id"]
    workspace_id = checkout_data["workspace_id"]
    snapshot_id = checkout_data["snapshot_id"]

    # Create conversation scoped to repo + checkout
    conv_resp = client.post(
        "/v1/conversations",
        json={
            "tenant_id": "tenant_test",
            "repo_def_id": repo_def_id,
            "checkout_id": checkout_id,
            "workspace_id": workspace_id,
            "title": "Analysis Chat",
        },
        headers=member_headers,
    )
    assert conv_resp.status_code == 200
    conv_id = conv_resp.json()["conversation_id"]

    # Get conversation head
    get_resp = client.get(f"/v1/conversations/{conv_id}", headers=member_headers)
    assert get_resp.status_code == 200
    head = get_resp.json()
    assert head["conversation_id"] == conv_id
    assert head["principal_email"] == "member@test.com"
    assert head["repo_def_id"] == repo_def_id
    assert head["checkout_id"] == checkout_id
    assert head["workspace_id"] == workspace_id
    assert head["latest_snapshot_id"] == snapshot_id

    # List conversations — should include our new one
    list_resp = client.get("/v1/conversations", headers=member_headers)
    assert list_resp.status_code == 200
    conv_list = list_resp.json()["conversations"]
    assert any(c["conversation_id"] == conv_id for c in conv_list)

    # List conversations filtered by repo_def_id
    filtered_resp = client.get(
        f"/v1/conversations?repo_def_id={repo_def_id}",
        headers=member_headers,
    )
    assert filtered_resp.status_code == 200
    filtered = filtered_resp.json()["conversations"]
    assert all(c["repo_def_id"] == repo_def_id for c in filtered)

    # Create a second checkout and conversation, then verify checkout-level filtering.
    second_checkout_resp = client.post(
        f"/v1/repos/{repo_def_id}/checkouts",
        json={"repo_def_id": repo_def_id, "ref": "main"},
        headers=member_headers,
    )
    second_checkout = second_checkout_resp.json()
    second_conv_resp = client.post(
        "/v1/conversations",
        json={
            "tenant_id": "tenant_test",
            "repo_def_id": repo_def_id,
            "checkout_id": second_checkout["checkout_id"],
            "workspace_id": second_checkout["workspace_id"],
            "title": "Second Scope Chat",
        },
        headers=member_headers,
    )
    assert second_conv_resp.status_code == 200
    second_conv_id = second_conv_resp.json()["conversation_id"]

    checkout_filtered_resp = client.get(
        f"/v1/conversations?repo_def_id={repo_def_id}&checkout_id={checkout_id}",
        headers=member_headers,
    )
    assert checkout_filtered_resp.status_code == 200
    checkout_filtered = checkout_filtered_resp.json()["conversations"]
    assert [c["conversation_id"] for c in checkout_filtered] == [conv_id]

    # Verify conversation S3 path structure
    conv_head_key = (
        f"tenants/tenant_test/conversations/member@test.com/"
        f"{repo_def_id}/{conv_id}/head.json"
    )
    obj = object_store.download_json(conv_head_key)
    assert obj["principal_email"] == "member@test.com"
    assert obj["repo_def_id"] == repo_def_id

    # Another user should not see this conversation
    other_headers = {
        "X-Tenant-Id": "tenant_test",
        "X-User-Email": "other@test.com",
    }
    other_list = client.get("/v1/conversations", headers=other_headers)
    assert other_list.status_code == 200
    assert not any(c["conversation_id"] == conv_id for c in other_list.json()["conversations"])

    # Attempt to access conversation directly as other user — 403
    other_get = client.get(f"/v1/conversations/{conv_id}", headers=other_headers)
    assert other_get.status_code == 403

    # Rename and pin the original conversation.
    update_resp = client.patch(
        f"/v1/conversations/{conv_id}",
        json={"title": "Renamed Analysis Chat", "pinned": True},
        headers=member_headers,
    )
    assert update_resp.status_code == 200
    updated_head = update_resp.json()
    assert updated_head["title"] == "Renamed Analysis Chat"
    assert updated_head["pinned_at"] is not None

    # Delete it softly, verify it disappears from normal reads and listings.
    delete_resp = client.delete(f"/v1/conversations/{conv_id}", headers=member_headers)
    assert delete_resp.status_code == 200
    deleted_head = delete_resp.json()
    assert deleted_head["status"] == "DELETED"
    assert deleted_head["deleted_at"] is not None

    deleted_get = client.get(f"/v1/conversations/{conv_id}", headers=member_headers)
    assert deleted_get.status_code == 404

    list_after_delete = client.get(
        f"/v1/conversations?repo_def_id={repo_def_id}",
        headers=member_headers,
    )
    assert list_after_delete.status_code == 200
    assert [c["conversation_id"] for c in list_after_delete.json()["conversations"]] == [
        second_conv_id
    ]

    obj_after_delete = object_store.download_json(conv_head_key)
    assert obj_after_delete["deleted_at"] is not None


@mock_aws
def test_conversation_requires_repo_def_or_workspace(
    tmp_path: Path,
) -> None:
    bucket_name = "code-analyst-convo-validation-test"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    test_settings = Settings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        sandbox_supervisor_url="http://sandbox-supervisor",
    )

    object_store = ObjectStore(test_settings)
    app_state_store = AppStateStore(object_store)
    state = AppState()
    state.object_store = object_store
    state.workspace_store = WorkspaceStateStore(object_store)
    state.conversation_store = ConversationStateStore(object_store)
    state.run_store = RunStateStore(object_store)
    state.approval_store = ApprovalStateStore(object_store)
    state.app_state_store = app_state_store
    state.workspace_import_service = WorkspaceImportService(
        settings=test_settings,
        object_store=object_store,
    )
    state.question_orchestrator = QuestionOrchestrator(
        sandbox_client=SandboxSupervisorClient(
            test_settings.sandbox_supervisor_url,
            timeout_seconds=10,
        ),
        conversation_store=state.conversation_store,
        run_store=state.run_store,
        workspace_store=state.workspace_store,
        approval_store=state.approval_store,
        app_state_store=app_state_store,
    )
    control_plane_app.state.state = state

    client = TestClient(control_plane_app)
    headers = {
        "X-Tenant-Id": "tenant_test",
        "X-User-Email": "admin@test.com",
    }

    client.post(
        "/v1/users",
        json={"email": "admin@test.com", "name": "Admin", "is_admin": True},
        headers=headers,
    )

    # Missing both repo_def_id and workspace_id
    resp = client.post(
        "/v1/conversations",
        json={"tenant_id": "tenant_test"},
        headers=headers,
    )
    assert resp.status_code == 422  # Pydantic validation error
