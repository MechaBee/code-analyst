from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from code_analyst_contracts import RepositoryAdapter
from control_plane_app.repository_checkout import (
    GitHubCheckoutProvider,
    RepositoryCheckoutError,
)


class FakeSecretStore:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def get_secret(self, *, tenant_id: str, secret_ref: str) -> dict[str, object]:
        self.calls.append((tenant_id, secret_ref))
        return self.payload


def test_github_checkout_uses_secret_store_token_via_git_env(
    tmp_path: Path,
) -> None:
    secret_store = FakeSecretStore({"token": "ghs_example_token"})
    provider = GitHubCheckoutProvider(secret_store)
    target_dir = tmp_path / "repo"
    commands: list[tuple[list[str], Path, dict[str, str] | None]] = []

    def fake_run_git(
        arguments: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        commands.append((arguments, cwd, env))
        return subprocess.CompletedProcess(
            args=["git", *arguments],
            returncode=0,
            stdout="",
            stderr="",
        )

    provider._run_git = fake_run_git  # type: ignore[method-assign]

    resolved_ref = provider.checkout(
        tenant_id="tenant_test",
        endpoint="https://github.com/acme/private-repo.git",
        ref="main",
        adapter=RepositoryAdapter(
            kind="github",
            auth_kind="token",
            access_secret_ref="s3:secret-store/tenants/tenant_test/secrets/sec_01.json",
        ),
        target_dir=target_dir,
    )

    assert resolved_ref == "main"
    assert secret_store.calls == [
        ("tenant_test", "s3:secret-store/tenants/tenant_test/secrets/sec_01.json")
    ]
    assert [command for command, _, _ in commands] == [
        ["clone", "--filter=blob:none", "--no-checkout", "https://github.com/acme/private-repo.git", str(target_dir)],
        ["fetch", "--depth", "1", "origin", "main"],
        ["checkout", "FETCH_HEAD"],
    ]

    clone_env = commands[0][2]
    fetch_env = commands[1][2]
    checkout_env = commands[2][2]
    assert clone_env is not None
    assert fetch_env == clone_env
    assert checkout_env == clone_env
    assert clone_env["GIT_TERMINAL_PROMPT"] == "0"
    assert clone_env["GIT_CONFIG_COUNT"] == "1"
    assert (
        clone_env["GIT_CONFIG_KEY_0"]
        == "http.https://github.com/.extraHeader"
    )
    assert clone_env["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic ")


def test_github_checkout_rejects_secret_without_token() -> None:
    provider = GitHubCheckoutProvider(FakeSecretStore({"client_id": "abc"}))

    with pytest.raises(RepositoryCheckoutError, match="non-empty 'token' field"):
        provider.checkout(
            tenant_id="tenant_test",
            endpoint="https://github.com/acme/private-repo.git",
            ref="main",
            adapter=RepositoryAdapter(
                kind="github",
                auth_kind="token",
                access_secret_ref="s3:secret-store/tenants/tenant_test/secrets/sec_01.json",
            ),
            target_dir=Path("/tmp/repo"),
        )


def test_github_checkout_surfaces_clone_stderr(tmp_path: Path) -> None:
    provider = GitHubCheckoutProvider(FakeSecretStore({"token": "ghs_example_token"}))

    def fake_run_git(
        arguments: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(
            returncode=128,
            cmd=["git", *arguments],
            stderr="fatal: Authentication failed for repo",
        )

    provider._run_git = fake_run_git  # type: ignore[method-assign]

    with pytest.raises(
        RepositoryCheckoutError,
        match="fatal: Authentication failed for repo",
    ):
        provider.checkout(
            tenant_id="tenant_test",
            endpoint="https://github.com/acme/private-repo.git",
            ref="main",
            adapter=RepositoryAdapter(
                kind="github",
                auth_kind="token",
                access_secret_ref="s3:secret-store/tenants/tenant_test/secrets/sec_01.json",
            ),
            target_dir=tmp_path / "repo",
        )
