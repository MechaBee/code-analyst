from __future__ import annotations

from pathlib import Path

import boto3
import pytest
from control_plane_app.config import Settings
from control_plane_app.main import AppState
from control_plane_app.main import app as control_plane_app
from fastapi.testclient import TestClient
from moto import mock_aws


def build_test_settings(
    *,
    bucket_name: str,
    tmp_path: Path,
    secret_store_s3_bucket: str | None = None,
) -> Settings:
    return Settings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        secret_store_s3_bucket=secret_store_s3_bucket,
        sandbox_supervisor_url="http://sandbox-supervisor",
        auth_backend="header",
        auth_sqlite_path=str(tmp_path / "auth.db"),
    )


def build_test_state(test_settings: Settings) -> AppState:
    state = AppState(test_settings)
    control_plane_app.state.state = state
    return state


@mock_aws
def test_identity_and_repo_flow(tmp_path: Path) -> None:
    bucket_name = "code-analyst-identity-test"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    test_settings = build_test_settings(bucket_name=bucket_name, tmp_path=tmp_path)
    state = build_test_state(test_settings)

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

    admin_users_resp = client.get("/v1/admin/users", headers=headers)
    assert admin_users_resp.status_code == 200
    admin_users = admin_users_resp.json()["users"]
    assert [user["email"] for user in admin_users] == ["admin@test.com", "member@test.com"]

    admin_teams_resp = client.get("/v1/admin/teams", headers=headers)
    assert admin_teams_resp.status_code == 200
    admin_teams = admin_teams_resp.json()["teams"]
    assert admin_teams[0]["team_id"] == team_id
    assert admin_teams[0]["member_count"] == 1

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

    admin_team_detail_resp = client.get(
        f"/v1/admin/teams/{team_id}",
        headers=headers,
    )
    assert admin_team_detail_resp.status_code == 200
    team_detail = admin_team_detail_resp.json()
    assert team_detail["team"]["team_id"] == team_id
    assert [member["user_email"] for member in team_detail["members"]] == ["member@test.com"]
    assert [repo["repo_def_id"] for repo in team_detail["repositories"]] == [repo_def_id]

    admin_repos_resp = client.get("/v1/admin/repos", headers=headers)
    assert admin_repos_resp.status_code == 200
    assert [repo["repo_def_id"] for repo in admin_repos_resp.json()["repo_definitions"]] == [repo_def_id]

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

    member_admin_users_resp = client.get("/v1/admin/users", headers=member_headers)
    assert member_admin_users_resp.status_code == 403

    member_list_teams_resp = client.get("/v1/teams", headers=member_headers)
    assert member_list_teams_resp.status_code == 403

    member_add_self_resp = client.post(
        f"/v1/teams/{team_id}/members",
        json={"user_email": "member@test.com"},
        headers=member_headers,
    )
    assert member_add_self_resp.status_code == 403

    # 8. Get repo definition
    get_repo_resp = client.get(f"/v1/repos/{repo_def_id}", headers=headers)
    assert get_repo_resp.status_code == 200
    assert get_repo_resp.json()["repo_def_id"] == repo_def_id

    # 9. Update repo definition metadata through the generic PATCH endpoint.
    update_repo_resp = client.patch(
        f"/v1/repos/{repo_def_id}",
        json={
            "name": "Renamed Example Repo",
            "endpoint": "https://github.com/example/renamed-repo.git",
            "team_ids": [team_id],
        },
        headers=headers,
    )
    assert update_repo_resp.status_code == 200
    updated_repo = update_repo_resp.json()
    assert updated_repo["name"] == "Renamed Example Repo"
    assert updated_repo["endpoint"] == "https://github.com/example/renamed-repo.git"
    assert updated_repo["team_ids"] == [team_id]

    member_get_repo_before_archive = client.get(
        f"/v1/repos/{repo_def_id}",
        headers=member_headers,
    )
    assert member_get_repo_before_archive.status_code == 200
    assert member_get_repo_before_archive.json()["archived_at"] is None

    # 10. Archive the repo and verify visibility / access semantics.
    archive_resp = client.delete(f"/v1/repos/{repo_def_id}", headers=headers)
    assert archive_resp.status_code == 200
    archived_repo = archive_resp.json()
    assert archived_repo["archived_at"] is not None

    member_get_repo_archived = client.get(f"/v1/repos/{repo_def_id}", headers=member_headers)
    assert member_get_repo_archived.status_code == 200
    assert member_get_repo_archived.json()["archived_at"] is not None

    member_repos_archived = client.get("/v1/repos", headers=member_headers)
    assert member_repos_archived.status_code == 200
    assert member_repos_archived.json()["repo_definitions"] == []

    admin_active_repos_archived = client.get("/v1/repos", headers=headers)
    assert admin_active_repos_archived.status_code == 200
    assert admin_active_repos_archived.json()["repo_definitions"] == []

    admin_archived_default = client.get("/v1/admin/repos", headers=headers)
    assert admin_archived_default.status_code == 200
    assert admin_archived_default.json()["repo_definitions"] == []

    admin_archived_included = client.get(
        "/v1/admin/repos?include_archived=true",
        headers=headers,
    )
    assert admin_archived_included.status_code == 200
    assert [repo["repo_def_id"] for repo in admin_archived_included.json()["repo_definitions"]] == [
        repo_def_id
    ]

    archived_team_detail = client.get(f"/v1/admin/teams/{team_id}", headers=headers)
    assert archived_team_detail.status_code == 200
    assert archived_team_detail.json()["repositories"] == []

    archived_checkout_resp = client.post(
        f"/v1/repos/{repo_def_id}/checkouts",
        json={"repo_def_id": repo_def_id, "ref": "main"},
        headers=member_headers,
    )
    assert archived_checkout_resp.status_code == 409

    archived_conversation_resp = client.post(
        "/v1/conversations",
        json={
            "tenant_id": "tenant_test",
            "repo_def_id": repo_def_id,
            "workspace_id": "ws_placeholder",
        },
        headers=member_headers,
    )
    assert archived_conversation_resp.status_code == 409

    # 11. Restore the repo and verify access returns without mutating team grants.
    restore_resp = client.post(f"/v1/repos/{repo_def_id}/restore", headers=headers)
    assert restore_resp.status_code == 200
    assert restore_resp.json()["archived_at"] is None

    restored_team_detail = client.get(f"/v1/admin/teams/{team_id}", headers=headers)
    assert restored_team_detail.status_code == 200
    assert [repo["repo_def_id"] for repo in restored_team_detail.json()["repositories"]] == [
        repo_def_id
    ]

    restored_member_repos = client.get("/v1/repos", headers=member_headers)
    assert restored_member_repos.status_code == 200
    assert [repo["repo_def_id"] for repo in restored_member_repos.json()["repo_definitions"]] == [
        repo_def_id
    ]

    # 12. Update repo definition teams through the compatibility endpoint.
    update_resp = client.patch(
        f"/v1/repos/{repo_def_id}/teams",
        json={"team_ids": []},
        headers=headers,
    )
    assert update_resp.status_code == 200

    member_update_repo_resp = client.patch(
        f"/v1/repos/{repo_def_id}/teams",
        json={"team_ids": [team_id]},
        headers=member_headers,
    )
    assert member_update_repo_resp.status_code == 403

    # After removing team access, member should see no repos
    list_repos_after = client.get("/v1/repos", headers=member_headers)
    assert list_repos_after.status_code == 200
    assert len(list_repos_after.json()["repo_definitions"]) == 0

    member_get_repo_after = client.get(f"/v1/repos/{repo_def_id}", headers=member_headers)
    assert member_get_repo_after.status_code == 403

    admin_repos_after = client.get("/v1/repos", headers=headers)
    assert admin_repos_after.status_code == 200
    assert len(admin_repos_after.json()["repo_definitions"]) == 1

    # 10. Verify app_state.json was persisted
    db = state.app_state_store.load_tenant_db("tenant_test")
    assert "admin@test.com" in db.users
    assert "member@test.com" in db.users
    assert team_id in db.teams
    assert repo_def_id in db.repo_definitions


@mock_aws
def test_get_me_recovers_admin_for_adminless_tenant(tmp_path: Path) -> None:
    bucket_name = "code-analyst-bootstrap-test"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    test_settings = build_test_settings(bucket_name=bucket_name, tmp_path=tmp_path)
    state = build_test_state(test_settings)

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


@mock_aws
def test_private_repo_definition_stores_secret_outside_app_state(tmp_path: Path) -> None:
    bucket_name = "code-analyst-private-repo-test"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    test_settings = build_test_settings(
        bucket_name=bucket_name,
        tmp_path=tmp_path,
        secret_store_s3_bucket=bucket_name,
    )
    state = build_test_state(test_settings)

    client = TestClient(control_plane_app)
    headers = {
        "X-Tenant-Id": "tenant_test",
        "X-User-Email": "admin@test.com",
    }

    create_user_resp = client.post(
        "/v1/users",
        json={"email": "admin@test.com", "name": "Admin User", "is_admin": True},
        headers=headers,
    )
    assert create_user_resp.status_code == 200

    create_team_resp = client.post(
        "/v1/teams",
        json={"name": "Platform Team"},
        headers=headers,
    )
    assert create_team_resp.status_code == 200
    team_id = create_team_resp.json()["team_id"]

    create_repo_resp = client.post(
        "/v1/repos",
        json={
            "name": "Private Repo",
            "endpoint": "https://github.com/example/private-repo.git",
            "adapter": {
                "kind": "github",
                "auth_kind": "token",
                "access_secret": {
                    "token": "ghs_example_secret_token",
                    "note": "opaque blob field",
                },
            },
            "team_ids": [team_id],
        },
        headers=headers,
    )
    assert create_repo_resp.status_code == 200
    repo_data = create_repo_resp.json()
    adapter = repo_data["adapter"]
    assert adapter["kind"] == "github"
    assert adapter["auth_kind"] == "token"
    assert adapter["access_secret_ref"].startswith("s3:")
    assert "access_secret" not in adapter

    stored_secret = state.secret_store.get_secret(
        tenant_id="tenant_test",
        secret_ref=adapter["access_secret_ref"],
    )
    assert stored_secret == {
        "note": "opaque blob field",
        "token": "ghs_example_secret_token",
    }

    db = state.app_state_store.load_tenant_db("tenant_test")
    repo_def = next(iter(db.repo_definitions.values()))
    assert repo_def.adapter.access_secret_ref == adapter["access_secret_ref"]
    assert "ghs_example_secret_token" not in db.model_dump_json()

    from control_plane_app.secret_store import SecretNotFoundError

    rotate_resp = client.patch(
        f"/v1/repos/{repo_data['repo_def_id']}",
        json={
            "adapter": {
                "auth_kind": "token",
                "access_secret": {
                    "token": "ghs_rotated_secret_token",
                    "note": "new secret",
                },
            }
        },
        headers=headers,
    )
    assert rotate_resp.status_code == 200
    rotated_adapter = rotate_resp.json()["adapter"]
    assert rotated_adapter["access_secret_ref"].startswith("s3:")
    assert rotated_adapter["access_secret_ref"] != adapter["access_secret_ref"]

    rotated_secret = state.secret_store.get_secret(
        tenant_id="tenant_test",
        secret_ref=rotated_adapter["access_secret_ref"],
    )
    assert rotated_secret == {
        "note": "new secret",
        "token": "ghs_rotated_secret_token",
    }

    with pytest.raises(SecretNotFoundError):
        state.secret_store.get_secret(
            tenant_id="tenant_test",
            secret_ref=adapter["access_secret_ref"],
        )

    public_resp = client.patch(
        f"/v1/repos/{repo_data['repo_def_id']}",
        json={"adapter": {"auth_kind": "public"}},
        headers=headers,
    )
    assert public_resp.status_code == 200
    public_adapter = public_resp.json()["adapter"]
    assert public_adapter["auth_kind"] == "public"
    assert public_adapter["access_secret_ref"] is None
    assert public_adapter["credential_ref"] is None

    with pytest.raises(SecretNotFoundError):
        state.secret_store.get_secret(
            tenant_id="tenant_test",
            secret_ref=rotated_adapter["access_secret_ref"],
        )
