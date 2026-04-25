from __future__ import annotations

import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import zstandard
from code_analyst_contracts import (
    SandboxSessionCreateRequest,
    SandboxSessionRef,
    SnapshotManifest,
)

from .config import Settings
from .object_store import ObjectStore


class WorkspaceMaterializationError(RuntimeError):
    pass


@dataclass(slots=True)
class MaterializedWorkspace:
    session: SandboxSessionRef
    manifest: SnapshotManifest
    session_dir: Path
    workspace_root: Path


class WorkspaceMaterializer:
    def __init__(self, settings: Settings, object_store: ObjectStore) -> None:
        self._settings = settings
        self._object_store = object_store

    def create_or_resume(
        self,
        request: SandboxSessionCreateRequest,
    ) -> MaterializedWorkspace:
        sandbox_id = request.resume_from_sandbox_id or self._new_id("sbx")
        session_dir = Path(self._settings.workspace_root_dir) / sandbox_id
        session_dir.mkdir(parents=True, exist_ok=True)

        manifest = self._load_manifest(request.workspace.manifest_object_key)
        workspace_root = session_dir / manifest.root_prefix

        if not workspace_root.exists():
            if any(session_dir.iterdir()):
                shutil.rmtree(session_dir)
                session_dir.mkdir(parents=True, exist_ok=True)
            self._materialize_archive(
                archive_object_key=request.workspace.archive_object_key,
                session_dir=session_dir,
            )

        if not workspace_root.exists() or not workspace_root.is_dir():
            raise WorkspaceMaterializationError(
                f"Expected workspace root {workspace_root} after extraction."
            )

        session = SandboxSessionRef(
            sandbox_id=sandbox_id,
            runtime_image=request.runtime_image or self._settings.sandbox_runtime_image,
            snapshot_id=request.workspace.snapshot_id,
            session_state_key=self._build_session_state_key(
                archive_object_key=request.workspace.archive_object_key,
                sandbox_id=sandbox_id,
            ),
        )
        return MaterializedWorkspace(
            session=session,
            manifest=manifest,
            session_dir=session_dir,
            workspace_root=workspace_root,
        )

    def dispose(self, session_dir: Path | str) -> None:
        session_path = Path(session_dir)
        if session_path.exists():
            shutil.rmtree(session_path)

    def _load_manifest(self, manifest_object_key: str) -> SnapshotManifest:
        payload = self._object_store.download_json(manifest_object_key)
        return SnapshotManifest.model_validate(payload)

    def _materialize_archive(self, archive_object_key: str, session_dir: Path) -> None:
        archive_path = session_dir / "repo.tar.zst"
        self._object_store.download_file(archive_object_key, archive_path)
        try:
            with archive_path.open("rb") as raw_archive:
                decompressor = zstandard.ZstdDecompressor()
                with decompressor.stream_reader(raw_archive) as compressed_stream:
                    with tarfile.open(fileobj=compressed_stream, mode="r|") as tar:
                        for member in tar:
                            target_path = session_dir / member.name
                            self._ensure_safe_extract_path(session_dir, target_path)
                            self._extract_member(tar, member, target_path)
        finally:
            archive_path.unlink(missing_ok=True)

    def _ensure_safe_extract_path(self, session_dir: Path, target_path: Path) -> None:
        resolved_session_dir = session_dir.resolve()
        resolved_target_path = target_path.resolve(strict=False)
        if not str(resolved_target_path).startswith(str(resolved_session_dir)):
            raise WorkspaceMaterializationError(
                f"Archive member escaped sandbox root: {target_path}"
            )

    def _extract_member(
        self,
        tar: tarfile.TarFile,
        member: tarfile.TarInfo,
        target_path: Path,
    ) -> None:
        if member.isdir():
            target_path.mkdir(parents=True, exist_ok=True)
            return
        if member.islnk() or member.issym() or member.isdev():
            raise WorkspaceMaterializationError(
                f"Unsupported archive member type for {member.name}"
            )
        if not member.isfile():
            return
        target_path.parent.mkdir(parents=True, exist_ok=True)
        file_obj = tar.extractfile(member)
        if file_obj is None:
            raise WorkspaceMaterializationError(
                f"Archive file contents were missing for {member.name}"
            )
        with file_obj, target_path.open("wb") as output:
            shutil.copyfileobj(file_obj, output)

    def _build_session_state_key(self, archive_object_key: str, sandbox_id: str) -> str:
        parts = archive_object_key.split("/")
        tenant_id = "local"
        if len(parts) >= 2 and parts[0] == "tenants":
            tenant_id = parts[1]
        return f"tenants/{tenant_id}/sandboxes/{sandbox_id}/session_state.json"

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:12]}"
