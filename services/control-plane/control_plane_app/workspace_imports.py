from __future__ import annotations

import hashlib
import os
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

import zstandard
from code_analyst_contracts import (
    SnapshotFileEntry,
    SnapshotManifest,
    WorkspaceImportRequest,
    WorkspaceImportResponse,
    WorkspaceSnapshotRef,
)

from .config import Settings
from .object_store import ObjectStore


class WorkspaceImportError(RuntimeError):
    pass


@dataclass(slots=True)
class WorkspaceImportArtifacts:
    snapshot_ref: WorkspaceSnapshotRef
    manifest: SnapshotManifest
    response: WorkspaceImportResponse


class WorkspaceImportService:
    def __init__(self, settings: Settings, object_store: ObjectStore) -> None:
        self._settings = settings
        self._object_store = object_store

    def import_github_repo(
        self,
        request: WorkspaceImportRequest,
    ) -> WorkspaceImportArtifacts:
        """Legacy raw-repo import (creates workspace without checkout record)."""
        return self._import_core(
            tenant_id=request.tenant_id,
            repo_url=request.repo_url,
            ref=request.ref,
            github_credential_ref=request.github_credential_ref,
        )

    def import_from_repo_definition(
        self,
        *,
        tenant_id: str,
        repo_def_id: str,
        ref: str,
        endpoint: str,
        credential_ref: str,
    ) -> WorkspaceImportArtifacts:
        """Import from a repository definition. Returns workspace artifacts."""
        return self._import_core(
            tenant_id=tenant_id,
            repo_url=endpoint,
            ref=ref,
            github_credential_ref=credential_ref,
        )

    def _import_core(
        self,
        tenant_id: str,
        repo_url: str,
        ref: str,
        github_credential_ref: str,
    ) -> WorkspaceImportArtifacts:
        workspace_id = self._new_id("ws")
        snapshot_id = self._new_id("snap")
        base_tmp_dir = Path(self._settings.workspace_tmp_dir)
        base_tmp_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix="workspace-import-",
            dir=base_tmp_dir,
        ) as temp_dir:
            temp_path = Path(temp_dir)
            repo_dir = temp_path / "repo"
            archive_path = temp_path / "repo.tar.zst"

            self._clone_repository(
                repo_url=repo_url,
                ref=ref,
                github_credential_ref=github_credential_ref,
                target_dir=repo_dir,
            )
            commit_sha = self._resolve_commit_sha(repo_dir)
            archive_object_key, manifest_object_key, metadata_object_key = (
                self._build_object_keys(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    snapshot_id=snapshot_id,
                )
            )

            snapshot_ref = WorkspaceSnapshotRef(
                workspace_id=workspace_id,
                snapshot_id=snapshot_id,
                repo_url=repo_url,
                ref=ref,
                commit_sha=commit_sha,
                archive_object_key=archive_object_key,
                manifest_object_key=manifest_object_key,
                metadata_object_key=metadata_object_key,
            )
            manifest = self._build_manifest(
                tenant_id=tenant_id,
                snapshot=snapshot_ref,
                repo_dir=repo_dir,
            )
            self._create_archive(repo_dir=repo_dir, archive_path=archive_path)
            self._upload_snapshot(
                tenant_id=tenant_id,
                github_credential_ref=github_credential_ref,
                snapshot=snapshot_ref,
                manifest=manifest,
                archive_path=archive_path,
            )

        response = WorkspaceImportResponse(
            workspace_id=workspace_id,
            snapshot_id=snapshot_id,
            source_commit=commit_sha,
            archive_object_key=archive_object_key,
            manifest_object_key=manifest_object_key,
            metadata_object_key=metadata_object_key,
            file_count=manifest.file_count,
            total_size_bytes=manifest.total_size_bytes,
        )
        return WorkspaceImportArtifacts(
            snapshot_ref=snapshot_ref,
            manifest=manifest,
            response=response,
        )

    def _build_manifest(
        self,
        tenant_id: str,
        snapshot: WorkspaceSnapshotRef,
        repo_dir: Path,
    ) -> SnapshotManifest:
        file_entries: list[SnapshotFileEntry] = []
        total_size_bytes = 0

        for file_path in sorted(repo_dir.rglob("*")):
            if ".git" in file_path.parts:
                continue
            if not file_path.is_file() or file_path.is_symlink():
                continue
            sha256 = self._sha256_for_file(file_path)
            size_bytes = file_path.stat().st_size
            total_size_bytes += size_bytes
            file_entries.append(
                SnapshotFileEntry(
                    path=file_path.relative_to(repo_dir).as_posix(),
                    size_bytes=size_bytes,
                    sha256=sha256,
                )
            )

        top_level_entries = sorted(
            child.name
            for child in repo_dir.iterdir()
            if child.name != ".git" and not child.is_symlink()
        )
        return SnapshotManifest(
            tenant_id=tenant_id,
            workspace_id=snapshot.workspace_id,
            snapshot_id=snapshot.snapshot_id,
            repo_url=snapshot.repo_url,
            ref=snapshot.ref,
            commit_sha=snapshot.commit_sha,
            archive_object_key=snapshot.archive_object_key,
            manifest_object_key=snapshot.manifest_object_key,
            metadata_object_key=snapshot.metadata_object_key or "",
            file_count=len(file_entries),
            total_size_bytes=total_size_bytes,
            top_level_entries=top_level_entries,
            files=file_entries,
        )

    def _upload_snapshot(
        self,
        *,
        tenant_id: str,
        github_credential_ref: str,
        snapshot: WorkspaceSnapshotRef,
        manifest: SnapshotManifest,
        archive_path: Path,
    ) -> None:
        self._object_store.upload_file(
            object_key=snapshot.archive_object_key,
            local_path=archive_path,
            content_type="application/zstd",
        )
        self._object_store.upload_json(
            object_key=snapshot.manifest_object_key,
            payload=manifest.model_dump(mode="json"),
        )
        metadata = {
            "tenant_id": tenant_id,
            "github_credential_ref": github_credential_ref,
            "snapshot": snapshot.model_dump(mode="json"),
        }
        if snapshot.metadata_object_key is None:
            raise WorkspaceImportError("Snapshot metadata object key was not set")
        self._object_store.upload_json(
            object_key=snapshot.metadata_object_key,
            payload=metadata,
        )

    def _clone_repository(
        self,
        repo_url: str,
        ref: str,
        github_credential_ref: str,
        target_dir: Path,
    ) -> None:
        clone_url = self._build_clone_url(repo_url, github_credential_ref)
        self._run_git(
            ["clone", "--filter=blob:none", "--no-checkout", clone_url, str(target_dir)],
            cwd=target_dir.parent,
        )

        resolved_ref = ref.strip() if ref else ""
        if not resolved_ref:
            resolved_ref = self._detect_default_branch(target_dir)

        fetch_commands = [
            ["fetch", "--depth", "1", "origin", resolved_ref],
            ["fetch", "origin", resolved_ref],
        ]
        last_error: subprocess.CalledProcessError | None = None
        for command in fetch_commands:
            try:
                self._run_git(command, cwd=target_dir)
                self._run_git(["checkout", "FETCH_HEAD"], cwd=target_dir)
                return
            except subprocess.CalledProcessError as error:
                last_error = error

        if last_error is None:
            raise WorkspaceImportError("Repository fetch failed without a git error")
        raise WorkspaceImportError(last_error.stderr.strip() or "Failed to fetch ref")

    def _detect_default_branch(self, target_dir: Path) -> str:
        """Attempt to detect the remote default branch (HEAD)."""
        try:
            result = self._run_git(
                ["symbolic-ref", "refs/remotes/origin/HEAD", "--short"],
                cwd=target_dir,
            )
            branch = result.stdout.strip().replace("origin/", "")
            if branch:
                return branch
        except subprocess.CalledProcessError:
            pass

        # Fallback: try common default branch names
        for fallback in ("main", "master"):
            try:
                self._run_git(["fetch", "--depth", "1", "origin", fallback], cwd=target_dir)
                return fallback
            except subprocess.CalledProcessError:
                continue

        raise WorkspaceImportError(
            "Could not auto-detect the repository default branch. "
            "Please provide an explicit ref (e.g., main, master, or a tag name)."
        )

    def _resolve_commit_sha(self, repo_dir: Path) -> str:
        completed = self._run_git(["rev-parse", "HEAD"], cwd=repo_dir)
        return completed.stdout.strip()

    def _create_archive(self, repo_dir: Path, archive_path: Path) -> None:
        with archive_path.open("wb") as raw_archive:
            compressor = zstandard.ZstdCompressor(level=3)
            with compressor.stream_writer(raw_archive) as compressed_stream:
                with tarfile.open(fileobj=compressed_stream, mode="w|") as tar:
                    tar.add(
                        repo_dir,
                        arcname="workspace",
                        filter=self._tar_filter,
                    )

    def _tar_filter(self, tar_info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = Path(tar_info.name).parts
        if ".git" in parts:
            return None
        if tar_info.issym() or tar_info.islnk() or tar_info.isdev():
            return None
        return tar_info

    def _build_object_keys(
        self,
        tenant_id: str,
        workspace_id: str,
        snapshot_id: str,
    ) -> tuple[str, str, str]:
        prefix = (
            f"tenants/{tenant_id}/workspaces/{workspace_id}/snapshots/{snapshot_id}"
        )
        return (
            f"{prefix}/repo.tar.zst",
            f"{prefix}/manifest.json",
            f"{prefix}/metadata.json",
        )

    def _build_clone_url(self, repo_url: str, github_credential_ref: str) -> str:
        token = self._resolve_token(github_credential_ref)
        if token is None:
            return repo_url

        parsed = urlsplit(repo_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise WorkspaceImportError(
                "Token-based GitHub import currently requires an https repository URL."
            )

        username = "x-access-token"
        password = quote(token, safe="")
        netloc = f"{username}:{password}@{parsed.netloc}"
        return urlunsplit(
            (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
        )

    def _resolve_token(self, github_credential_ref: str) -> str | None:
        normalized = github_credential_ref.strip()
        if normalized in {"", "public", "none"}:
            return None
        if normalized.startswith("env:"):
            env_var_name = normalized.split(":", 1)[1]
            token = os.getenv(env_var_name)
            if token:
                return token
            raise WorkspaceImportError(
                f"GitHub credential environment variable {env_var_name} is not set."
            )
        raise WorkspaceImportError(
            "Unsupported github_credential_ref. Use 'public' or 'env:VAR_NAME'."
        )

    def _run_git(
        self,
        arguments: list[str],
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        return subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    def _sha256_for_file(self, file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:12]}"
