from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from code_analyst_contracts import User
from control_plane_app.config import Settings
from control_plane_app.main import AppState
from control_plane_app.main import app as control_plane_app
from fastapi.testclient import TestClient
from moto import mock_aws


BOOTSTRAP_SECRET = "test-bootstrap-secret"


def build_test_settings(*, bucket_name: str, tmp_path: Path) -> Settings:
    return Settings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        sandbox_supervisor_url="http://sandbox-supervisor",
        auth_backend="session_cookie",
        auth_sqlite_path=str(tmp_path / "auth.db"),
        auth_bootstrap_secret=BOOTSTRAP_SECRET,
        auth_cookie_secure=False,
        app_public_url="http://localhost:3000",
    )


def build_test_state(test_settings: Settings) -> AppState:
    state = AppState(test_settings)
    control_plane_app.state.state = state
    return state


def extract_token(shared_url: str) -> str:
    query = parse_qs(urlparse(shared_url).query)
    tokens = query.get("token") or []
    assert len(tokens) == 1
    return tokens[0]


def tenant_headers(tenant_id: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id}


def bootstrap_admin_session(
    *,
    client: TestClient,
    tenant_id: str,
    email: str = "admin@test.com",
    name: str = "Admin User",
) -> str:
    bootstrap_resp = client.post(
        "/v1/auth/bootstrap/invitations",
        json={
            "email": email,
            "name": name,
            "bootstrap_secret": BOOTSTRAP_SECRET,
        },
        headers=tenant_headers(tenant_id),
    )
    assert bootstrap_resp.status_code == 200

    invite_token = extract_token(bootstrap_resp.json()["invite_url"])
    register_resp = client.post(
        "/v1/auth/register/consume",
        json={"token": invite_token, "name": name},
    )
    assert register_resp.status_code == 200
    assert register_resp.json()["email"] == email
    assert register_resp.json()["is_admin"] is True
    return invite_token


@mock_aws
def test_bootstrap_registration_sets_session_and_logout_revokes(tmp_path: Path) -> None:
    bucket_name = "code-analyst-auth-bootstrap"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    state = build_test_state(build_test_settings(bucket_name=bucket_name, tmp_path=tmp_path))
    client = TestClient(control_plane_app)
    headers = tenant_headers("tenant_auth")

    unauthenticated_me = client.get("/v1/users/me", headers=headers)
    assert unauthenticated_me.status_code == 401

    bootstrap_resp = client.post(
        "/v1/auth/bootstrap/invitations",
        json={
            "email": "admin@test.com",
            "name": "Bootstrap Admin",
            "bootstrap_secret": BOOTSTRAP_SECRET,
        },
        headers=headers,
    )
    assert bootstrap_resp.status_code == 200
    invite_token = extract_token(bootstrap_resp.json()["invite_url"])

    preview_resp = client.get(
        f"/v1/auth/registration/preview?token={invite_token}",
    )
    assert preview_resp.status_code == 200
    assert preview_resp.json()["email"] == "admin@test.com"
    assert preview_resp.json()["is_admin"] is True

    register_resp = client.post(
        "/v1/auth/register/consume",
        json={"token": invite_token, "name": "Bootstrap Admin"},
    )
    assert register_resp.status_code == 200
    assert register_resp.json()["email"] == "admin@test.com"
    assert register_resp.json()["is_admin"] is True

    me_resp = client.get("/v1/users/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "admin@test.com"
    assert me_resp.json()["is_admin"] is True

    admin_users_resp = client.get("/v1/admin/users", headers=headers)
    assert admin_users_resp.status_code == 200
    payload = admin_users_resp.json()
    assert payload["pending_invites"] == []
    assert payload["users"][0]["email"] == "admin@test.com"
    assert payload["users"][0]["has_account"] is True

    logout_resp = client.post("/v1/auth/logout", headers=headers)
    assert logout_resp.status_code == 200
    assert logout_resp.json()["status"] == "ok"

    me_after_logout = client.get("/v1/users/me", headers=headers)
    assert me_after_logout.status_code == 401

    reused_invite = client.post(
        "/v1/auth/register/consume",
        json={"token": invite_token, "name": "Bootstrap Admin"},
    )
    assert reused_invite.status_code == 410

    db = state.app_state_store.load_tenant_db("tenant_auth")
    assert db.users["admin@test.com"].is_admin is True


@mock_aws
def test_admin_invite_registration_and_sign_in_link_flow(tmp_path: Path) -> None:
    bucket_name = "code-analyst-auth-links"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    state = build_test_state(build_test_settings(bucket_name=bucket_name, tmp_path=tmp_path))
    admin_client = TestClient(control_plane_app)
    member_client = TestClient(control_plane_app)
    sign_in_client = TestClient(control_plane_app)
    headers = tenant_headers("tenant_auth")

    bootstrap_admin_session(client=admin_client, tenant_id="tenant_auth")

    team_resp = admin_client.post("/v1/teams", json={"name": "Platform"}, headers=headers)
    assert team_resp.status_code == 200
    team_id = team_resp.json()["team_id"]

    invite_resp = admin_client.post(
        "/v1/auth/invitations",
        json={
            "email": "member@test.com",
            "name": "Member User",
            "team_ids": [team_id],
            "is_admin": False,
        },
        headers=headers,
    )
    assert invite_resp.status_code == 200
    invite_token = extract_token(invite_resp.json()["invite_url"])

    admin_users_resp = admin_client.get("/v1/admin/users", headers=headers)
    assert admin_users_resp.status_code == 200
    admin_users = admin_users_resp.json()
    assert [user["email"] for user in admin_users["users"]] == ["admin@test.com"]
    assert [invite["email"] for invite in admin_users["pending_invites"]] == ["member@test.com"]

    preview_resp = member_client.get(
        f"/v1/auth/registration/preview?token={invite_token}",
    )
    assert preview_resp.status_code == 200
    assert preview_resp.json()["team_ids"] == [team_id]

    register_resp = member_client.post(
        "/v1/auth/register/consume",
        json={"token": invite_token, "name": "Member User"},
    )
    assert register_resp.status_code == 200
    assert register_resp.json()["email"] == "member@test.com"
    assert register_resp.json()["is_admin"] is False

    member_me = member_client.get("/v1/users/me", headers=headers)
    assert member_me.status_code == 200
    assert member_me.json()["email"] == "member@test.com"

    teams_for_member = state.app_state_store.list_teams_for_user(
        "tenant_auth",
        "member@test.com",
    )
    assert [team.team_id for team in teams_for_member] == [team_id]

    sign_in_link_resp = admin_client.post(
        "/v1/auth/sign-in-links",
        json={"email": "member@test.com"},
        headers=headers,
    )
    assert sign_in_link_resp.status_code == 200
    sign_in_token = extract_token(sign_in_link_resp.json()["sign_in_url"])

    logout_member = member_client.post("/v1/auth/logout", headers=headers)
    assert logout_member.status_code == 200
    assert member_client.get("/v1/users/me", headers=headers).status_code == 401

    sign_in_resp = sign_in_client.post(
        "/v1/auth/sign-in/consume",
        json={"token": sign_in_token},
    )
    assert sign_in_resp.status_code == 200
    assert sign_in_resp.json()["email"] == "member@test.com"

    signed_in_me = sign_in_client.get("/v1/users/me", headers=headers)
    assert signed_in_me.status_code == 200
    assert signed_in_me.json()["email"] == "member@test.com"

    reused_sign_in = sign_in_client.post(
        "/v1/auth/sign-in/consume",
        json={"token": sign_in_token},
    )
    assert reused_sign_in.status_code == 410


@mock_aws
def test_legacy_tenant_can_claim_first_auth_admin(tmp_path: Path) -> None:
    bucket_name = "code-analyst-auth-legacy-claim"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    state = build_test_state(build_test_settings(bucket_name=bucket_name, tmp_path=tmp_path))
    client = TestClient(control_plane_app)
    headers = tenant_headers("tenant_auth")

    state.app_state_store.upsert_user(
        User(
            tenant_id="tenant_auth",
            email="user@tenant.local",
            name="Legacy Admin",
            is_admin=True,
        )
    )
    state.app_state_store.upsert_user(
        User(
            tenant_id="tenant_auth",
            email="member@tenant.local",
            name="Legacy Member",
            is_admin=False,
        )
    )

    bootstrap_resp = client.post(
        "/v1/auth/bootstrap/invitations",
        json={
            "email": "new-admin@test.com",
            "name": "New Admin",
            "bootstrap_secret": BOOTSTRAP_SECRET,
        },
        headers=headers,
    )
    assert bootstrap_resp.status_code == 200
    invite_token = extract_token(bootstrap_resp.json()["invite_url"])

    register_resp = client.post(
        "/v1/auth/register/consume",
        json={"token": invite_token, "name": "New Admin"},
    )
    assert register_resp.status_code == 200
    assert register_resp.json()["email"] == "new-admin@test.com"
    assert register_resp.json()["is_admin"] is True

    claimed_me = client.get("/v1/users/me", headers=headers)
    assert claimed_me.status_code == 200
    assert claimed_me.json()["email"] == "new-admin@test.com"
    assert claimed_me.json()["is_admin"] is True

    users = state.app_state_store.list_users("tenant_auth")
    assert sorted((user.email, user.is_admin) for user in users) == [
        ("member@tenant.local", False),
        ("new-admin@test.com", True),
        ("user@tenant.local", True),
    ]

    second_bootstrap_resp = client.post(
        "/v1/auth/bootstrap/invitations",
        json={
            "email": "another-admin@test.com",
            "name": "Another Admin",
            "bootstrap_secret": BOOTSTRAP_SECRET,
        },
        headers=headers,
    )
    assert second_bootstrap_resp.status_code == 409


@mock_aws
def test_expired_invites_and_unclaimed_users_cannot_get_sign_in_links(tmp_path: Path) -> None:
    bucket_name = "code-analyst-auth-expiry"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    state = build_test_state(build_test_settings(bucket_name=bucket_name, tmp_path=tmp_path))
    client = TestClient(control_plane_app)
    headers = tenant_headers("tenant_auth")

    bootstrap_admin_session(client=client, tenant_id="tenant_auth")

    expired_invite_resp = client.post(
        "/v1/auth/invitations",
        json={
            "email": "expired@test.com",
            "expires_in_hours": 0,
        },
        headers=headers,
    )
    assert expired_invite_resp.status_code == 200
    expired_invite_token = extract_token(expired_invite_resp.json()["invite_url"])

    expired_preview = client.get(
        f"/v1/auth/registration/preview?token={expired_invite_token}",
    )
    assert expired_preview.status_code == 410

    legacy_user = User(
        tenant_id="tenant_auth",
        email="legacy@test.com",
        name="Legacy User",
        is_admin=False,
    )
    state.app_state_store.upsert_user(legacy_user)

    sign_in_link_resp = client.post(
        "/v1/auth/sign-in-links",
        json={"email": "legacy@test.com"},
        headers=headers,
    )
    assert sign_in_link_resp.status_code == 409
