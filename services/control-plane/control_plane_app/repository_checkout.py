from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from code_analyst_contracts import RepositoryAdapter

from .config import Settings
from .secret_store import SecretStoreService


class RepositoryCheckoutError(RuntimeError):
    pass


class RepositoryCheckoutProvider(Protocol):
    kind: str

    def checkout(
        self,
        *,
        tenant_id: str,
        endpoint: str,
        ref: str,
        adapter: RepositoryAdapter,
        target_dir: Path,
    ) -> str:
        ...


class RepositoryCheckoutService:
    def __init__(self, providers: list[RepositoryCheckoutProvider]) -> None:
        self._providers = {provider.kind: provider for provider in providers}

    def checkout(
        self,
        *,
        tenant_id: str,
        endpoint: str,
        ref: str,
        adapter: RepositoryAdapter,
        target_dir: Path,
    ) -> str:
        provider = self._providers.get(adapter.kind.strip().lower())
        if provider is None:
            raise RepositoryCheckoutError(
                f"Unsupported repository kind {adapter.kind!r}."
            )
        return provider.checkout(
            tenant_id=tenant_id,
            endpoint=endpoint,
            ref=ref,
            adapter=adapter,
            target_dir=target_dir,
        )


class GitHubCheckoutProvider:
    kind = "github"

    def __init__(self, secret_store: SecretStoreService) -> None:
        self._secret_store = secret_store

    def checkout(
        self,
        *,
        tenant_id: str,
        endpoint: str,
        ref: str,
        adapter: RepositoryAdapter,
        target_dir: Path,
    ) -> str:
        remote_env = self._build_remote_git_env(
            tenant_id=tenant_id,
            endpoint=endpoint,
            adapter=adapter,
        )
        try:
            self._run_git(
                ["clone", "--filter=blob:none", "--no-checkout", endpoint, str(target_dir)],
                cwd=target_dir.parent,
                env=remote_env,
            )
        except subprocess.CalledProcessError as error:
            raise RepositoryCheckoutError(
                error.stderr.strip() or "Failed to clone repository."
            ) from error

        resolved_ref = ref.strip() if ref else ""
        if not resolved_ref:
            resolved_ref = self._detect_default_branch(target_dir, env=remote_env)

        fetch_commands = [
            ["fetch", "--depth", "1", "origin", resolved_ref],
            ["fetch", "origin", resolved_ref],
        ]
        last_error: subprocess.CalledProcessError | None = None
        for command in fetch_commands:
            try:
                self._run_git(command, cwd=target_dir, env=remote_env)
                self._run_git(
                    ["checkout", "FETCH_HEAD"],
                    cwd=target_dir,
                    env=remote_env,
                )
                return resolved_ref
            except subprocess.CalledProcessError as error:
                last_error = error

        if last_error is None:
            raise RepositoryCheckoutError(
                "Repository fetch failed without a git error."
            )
        raise RepositoryCheckoutError(
            last_error.stderr.strip() or "Failed to fetch ref."
        )

    def _build_remote_git_env(
        self,
        *,
        tenant_id: str,
        endpoint: str,
        adapter: RepositoryAdapter,
    ) -> dict[str, str]:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"

        auth_header = self._resolve_auth_header(
            tenant_id=tenant_id,
            endpoint=endpoint,
            adapter=adapter,
        )
        if auth_header is None:
            return env

        parsed_endpoint = urlsplit(endpoint)
        if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc:
            raise RepositoryCheckoutError(
                "Private GitHub checkout currently requires an https repository URL."
            )

        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = (
            f"http.{parsed_endpoint.scheme}://{parsed_endpoint.netloc}/.extraHeader"
        )
        env["GIT_CONFIG_VALUE_0"] = auth_header
        return env

    def _resolve_auth_header(
        self,
        *,
        tenant_id: str,
        endpoint: str,
        adapter: RepositoryAdapter,
    ) -> str | None:
        auth_kind = (adapter.auth_kind or "public").strip().lower() or "public"
        legacy_credential_ref = (adapter.credential_ref or "").strip()

        if auth_kind == "public" and not legacy_credential_ref:
            return None

        if adapter.access_secret_ref:
            secret = self._secret_store.get_secret(
                tenant_id=tenant_id,
                secret_ref=adapter.access_secret_ref,
            )
            return self._build_auth_header_from_secret(
                endpoint=endpoint,
                auth_kind=auth_kind,
                secret=secret,
            )

        if legacy_credential_ref:
            return self._build_auth_header_from_legacy_credential_ref(
                endpoint=endpoint,
                auth_kind=auth_kind,
                credential_ref=legacy_credential_ref,
            )

        if auth_kind == "public":
            return None

        raise RepositoryCheckoutError(
            "Private repository checkout requires an access_secret_ref."
        )

    def _build_auth_header_from_secret(
        self,
        *,
        endpoint: str,
        auth_kind: str,
        secret: dict[str, object],
    ) -> str:
        if auth_kind != "token":
            raise RepositoryCheckoutError(
                f"Unsupported GitHub auth_kind {auth_kind!r}."
            )

        token = secret.get("token")
        if not isinstance(token, str) or not token.strip():
            raise RepositoryCheckoutError(
                "GitHub token auth requires a secret JSON object with a non-empty 'token' field."
            )
        self._ensure_https_endpoint(endpoint)
        return self._build_basic_auth_header(token.strip())

    def _build_auth_header_from_legacy_credential_ref(
        self,
        *,
        endpoint: str,
        auth_kind: str,
        credential_ref: str,
    ) -> str | None:
        normalized = credential_ref.strip()
        if normalized in {"", "public", "none"}:
            return None
        if normalized.startswith("env:"):
            env_var_name = normalized.split(":", 1)[1]
            token = os.getenv(env_var_name)
            if token:
                self._ensure_https_endpoint(endpoint)
                return self._build_basic_auth_header(token)
            raise RepositoryCheckoutError(
                f"GitHub credential environment variable {env_var_name} is not set."
            )
        if auth_kind == "public":
            return None
        raise RepositoryCheckoutError(
            "Unsupported legacy github credential_ref. Use 'public' or 'env:VAR_NAME'."
        )

    def _ensure_https_endpoint(self, endpoint: str) -> None:
        parsed_endpoint = urlsplit(endpoint)
        if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc:
            raise RepositoryCheckoutError(
                "Token-based GitHub checkout currently requires an https repository URL."
            )

    def _build_basic_auth_header(self, token: str) -> str:
        encoded = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode(
            "ascii"
        )
        return f"AUTHORIZATION: basic {encoded}"

    def _detect_default_branch(
        self,
        target_dir: Path,
        *,
        env: dict[str, str],
    ) -> str:
        try:
            result = self._run_git(
                ["symbolic-ref", "refs/remotes/origin/HEAD", "--short"],
                cwd=target_dir,
                env=env,
            )
            branch = result.stdout.strip().replace("origin/", "")
            if branch:
                return branch
        except subprocess.CalledProcessError:
            pass

        for fallback in ("main", "master"):
            try:
                self._run_git(
                    ["fetch", "--depth", "1", "origin", fallback],
                    cwd=target_dir,
                    env=env,
                )
                return fallback
            except subprocess.CalledProcessError:
                continue

        raise RepositoryCheckoutError(
            "Could not auto-detect the repository default branch. "
            "Please provide an explicit ref (e.g. main, master, or a tag name)."
        )

    def _run_git(
        self,
        arguments: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )


def build_repository_checkout_service(
    settings: Settings,
    *,
    secret_store: SecretStoreService,
) -> RepositoryCheckoutService:
    del settings
    return RepositoryCheckoutService(
        providers=[GitHubCheckoutProvider(secret_store)],
    )
