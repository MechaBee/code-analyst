from __future__ import annotations

import subprocess
from pathlib import Path

import boto3
import pytest
from control_plane_app.config import Settings
from control_plane_app.main import app as control_plane_app
from control_plane_app.main import AppState
from fastapi.testclient import TestClient
from moto import mock_aws


def build_test_state(test_settings: Settings) -> AppState:
    state = AppState(test_settings)
    control_plane_app.state.state = state
    return state


@pytest.fixture()
def sample_git_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "checkout-test-repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Checkout Test Repo\n")
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text(
        "def run() -> str:\n"
        "    return 'hello-checkout'\n"
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
def test_checkout_from_repo_definition(
    tmp_path: Path,
    sample_git_repo: Path,
) -> None:
    bucket_name = "code-analyst-checkout-test"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    test_settings = Settings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_tmp_dir=str(tmp_path / "control-plane-tmp"),
        sandbox_supervisor_url="http://sandbox-supervisor",
        auth_backend="header",
        auth_sqlite_path=str(tmp_path / "auth.db"),
    )
    state = build_test_state(test_settings)

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

    # Create team
    team_resp = client.post("/v1/teams", json={"name": "Dev Team"}, headers=headers)
    assert team_resp.status_code == 200
    team_id = team_resp.json()["team_id"]

    # Create member
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

    # Create repo definition pointing to local git repo
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
    assert repo_resp.status_code == 200
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
    assert checkout_resp.status_code == 200
    checkout_data = checkout_resp.json()
    assert checkout_data["repo_def_id"] == repo_def_id
    assert checkout_data["branch"] == "main"
    assert "workspace_id" in checkout_data
    assert "snapshot_id" in checkout_data
    assert "commit_sha" in checkout_data
    checkout_id = checkout_data["checkout_id"]

    # List checkouts for repo
    list_resp = client.get(
        f"/v1/repos/{repo_def_id}/checkouts",
        headers=member_headers,
    )
    assert list_resp.status_code == 200
    checkouts = list_resp.json()["checkouts"]
    assert len(checkouts) == 1
    assert checkouts[0]["checkout_id"] == checkout_id

    # Get checkout by id
    get_resp = client.get(f"/v1/checkouts/{checkout_id}", headers=member_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["checkout_id"] == checkout_id

    # Verify workspace snapshot exists
    ws_head = state.workspace_store.get_latest_snapshot(
        tenant_id="tenant_test",
        workspace_id=checkout_data["workspace_id"],
    )
    assert ws_head is not None
    assert ws_head.snapshot_id == checkout_data["snapshot_id"]

    # Verify checkout is in the light DB
    db = state.app_state_store.load_tenant_db("tenant_test")
    assert checkout_id in db.checkouts
    assert db.checkouts[checkout_id].repo_def_id == repo_def_id


@mock_aws
def test_checkout_unauthorized_user_cannot_access_repo(
    tmp_path: Path,
    sample_git_repo: Path,
) -> None:
    bucket_name = "code-analyst-checkout-auth-test"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    test_settings = Settings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_tmp_dir=str(tmp_path / "control-plane-tmp"),
        sandbox_supervisor_url="http://sandbox-supervisor",
        auth_backend="header",
        auth_sqlite_path=str(tmp_path / "auth.db"),
    )
    state = build_test_state(test_settings)

    client = TestClient(control_plane_app)
    headers = {
        "X-Tenant-Id": "tenant_test",
        "X-User-Email": "admin@test.com",
    }

    # Create admin
    client.post(
        "/v1/users",
        json={"email": "admin@test.com", "name": "Admin", "is_admin": True},
        headers=headers,
    )

    # Create team and repo (no members added)
    team_resp = client.post("/v1/teams", json={"name": "Private Team"}, headers=headers)
    team_id = team_resp.json()["team_id"]

    repo_resp = client.post(
        "/v1/repos",
        json={
            "name": "Private Repo",
            "endpoint": str(sample_git_repo),
            "adapter": {"kind": "github", "credential_ref": "public"},
            "team_ids": [team_id],
        },
        headers=headers,
    )
    repo_def_id = repo_resp.json()["repo_def_id"]

    # Unauthorized user tries to checkout
    unauthorized_headers = {
        "X-Tenant-Id": "tenant_test",
        "X-User-Email": "stranger@test.com",
    }
    resp = client.post(
        f"/v1/repos/{repo_def_id}/checkouts",
        json={"repo_def_id": repo_def_id, "ref": "main"},
        headers=unauthorized_headers,
    )
    assert resp.status_code == 403
