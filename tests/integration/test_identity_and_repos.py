from __future__ import annotations

import boto3
import pytest
from control_plane_app.main import app as control_plane_app
from fastapi.testclient import TestClient
from moto import mock_aws


@mock_aws
def test_identity_and_repo_flow() -> None:
    bucket_name = "code-analyst-identity-test"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    # We need to override settings so the test S3 bucket and no endpoint is used.
    from control_plane_app.config import Settings
    from control_plane_app.object_store import ObjectStore
    from control_plane_app.app_state_store import AppStateStore
    from control_plane_app.state_store import (
        ApprovalStateStore,
        ConversationStateStore,
        RunStateStore,
        WorkspaceStateStore,
    )
    from control_plane_app.workspace_imports import WorkspaceImportService
    from control_plane_app.question_orchestrator import QuestionOrchestrator
    from control_plane_app.sandbox_supervisor_client import SandboxSupervisorClient

    test_settings = Settings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        sandbox_supervisor_url="http://sandbox-supervisor",
    )
    object_store = ObjectStore(test_settings)

    from control_plane_app.main import AppState

    state = AppState()
    state.object_store = object_store
    state.workspace_store = WorkspaceStateStore(object_store)
    state.conversation_store = ConversationStateStore(object_store)
    state.run_store = RunStateStore(object_store)
    state.approval_store = ApprovalStateStore(object_store)
    state.app_state_store = AppStateStore(object_store)
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
        app_state_store=state.app_state_store,
    )
    control_plane_app.state.state = state

    client = TestClient(control_plane_app)
    headers = {
        "X-Tenant-Id": "tenant_test",
        "X-User-Email": "admin@test.com",
    }

    # 1. Create a user
    create_user_resp = client.post(
        "/v1/users",
        json={"email": "admin@test.com", "name": "Admin User", "is_admin": True},
        headers=headers,
    )
    assert create_user_resp.status_code == 200
    user_data = create_user_resp.json()
    assert user_data["email"] == "admin@test.com"
    assert user_data["is_admin"] is True

    # 2. Get /v1/users/me
    me_resp = client.get("/v1/users/me", headers=headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "admin@test.com"

    # 3. Create a team
    create_team_resp = client.post(
        "/v1/teams",
        json={"name": "Platform Team"},
        headers=headers,
    )
    assert create_team_resp.status_code == 200
    team_data = create_team_resp.json()
    assert team_data["name"] == "Platform Team"
    team_id = team_data["team_id"]

    # 4. List teams
    list_teams_resp = client.get("/v1/teams", headers=headers)
    assert list_teams_resp.status_code == 200
    teams = list_teams_resp.json()["teams"]
    assert len(teams) == 1
    assert teams[0]["team_id"] == team_id

    # 5. Add a team member (first create the member user)
    client.post(
        "/v1/users",
        json={"email": "member@test.com", "name": "Member User", "is_admin": False},
        headers=headers,
    )
    add_member_resp = client.post(
        f"/v1/teams/{team_id}/members",
        json={"user_email": "member@test.com"},
        headers=headers,
    )
    assert add_member_resp.status_code == 200

    # 6. Create a repository definition
    create_repo_resp = client.post(
        "/v1/repos",
        json={
            "name": "Example Repo",
            "endpoint": "https://github.com/example/repo.git",
            "adapter": {"kind": "github", "credential_ref": "public"},
            "team_ids": [team_id],
        },
        headers=headers,
    )
    assert create_repo_resp.status_code == 200
    repo_data = create_repo_resp.json()
    assert repo_data["endpoint"] == "https://github.com/example/repo.git"
    repo_def_id = repo_data["repo_def_id"]

    # 7. List repo definitions for principal (member user)
    member_headers = {
        "X-Tenant-Id": "tenant_test",
        "X-User-Email": "member@test.com",
    }
    list_repos_resp = client.get("/v1/repos", headers=member_headers)
    assert list_repos_resp.status_code == 200
    repos = list_repos_resp.json()["repo_definitions"]
    assert len(repos) == 1
    assert repos[0]["repo_def_id"] == repo_def_id

    # 8. Get repo definition
    get_repo_resp = client.get(f"/v1/repos/{repo_def_id}", headers=headers)
    assert get_repo_resp.status_code == 200
    assert get_repo_resp.json()["repo_def_id"] == repo_def_id

    # 9. Update repo definition teams
    update_resp = client.patch(
        f"/v1/repos/{repo_def_id}/teams",
        json={"team_ids": []},
        headers=headers,
    )
    assert update_resp.status_code == 200

    # After removing team access, member should see no repos
    list_repos_after = client.get("/v1/repos", headers=member_headers)
    assert list_repos_after.status_code == 200
    assert len(list_repos_after.json()["repo_definitions"]) == 0

    # 10. Verify app_state.json was persisted
    from control_plane_app.app_state_store import AppStateStore
    db = state.app_state_store.load_tenant_db("tenant_test")
    assert "admin@test.com" in db.users
    assert "member@test.com" in db.users
    assert team_id in db.teams
    assert repo_def_id in db.repo_definitions


@mock_aws
def test_get_me_recovers_admin_for_adminless_tenant() -> None:
    bucket_name = "code-analyst-bootstrap-test"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    from control_plane_app.config import Settings
    from control_plane_app.object_store import ObjectStore
    from control_plane_app.app_state_store import AppStateStore
    from control_plane_app.state_store import (
        ApprovalStateStore,
        ConversationStateStore,
        RunStateStore,
        WorkspaceStateStore,
    )
    from control_plane_app.workspace_imports import WorkspaceImportService
    from control_plane_app.question_orchestrator import QuestionOrchestrator
    from control_plane_app.sandbox_supervisor_client import SandboxSupervisorClient

    test_settings = Settings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        sandbox_supervisor_url="http://sandbox-supervisor",
    )
    object_store = ObjectStore(test_settings)

    from control_plane_app.main import AppState

    state = AppState()
    state.object_store = object_store
    state.workspace_store = WorkspaceStateStore(object_store)
    state.conversation_store = ConversationStateStore(object_store)
    state.run_store = RunStateStore(object_store)
    state.approval_store = ApprovalStateStore(object_store)
    state.app_state_store = AppStateStore(object_store)
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
        app_state_store=state.app_state_store,
    )
    control_plane_app.state.state = state

    client = TestClient(control_plane_app)
    headers = {
        "X-Tenant-Id": "tenant_bootstrap",
        "X-User-Email": "user@tenant.local",
    }

    create_user_resp = client.post(
        "/v1/users",
        json={"email": "user@tenant.local", "name": "Legacy User", "is_admin": False},
        headers=headers,
    )
    assert create_user_resp.status_code == 200
    assert create_user_resp.json()["is_admin"] is False

    me_resp = client.get("/v1/users/me", headers=headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "user@tenant.local"
    assert me_data["is_admin"] is True

    db = state.app_state_store.load_tenant_db("tenant_bootstrap")
    assert db.users["user@tenant.local"].is_admin is True

    second_user_headers = {
        "X-Tenant-Id": "tenant_bootstrap",
        "X-User-Email": "other@tenant.local",
    }
    second_me_resp = client.get("/v1/users/me", headers=second_user_headers)
    assert second_me_resp.status_code == 200
    assert second_me_resp.json()["is_admin"] is False
