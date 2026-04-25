from __future__ import annotations

import subprocess
import tarfile
import tempfile
from pathlib import Path

import boto3
import pytest
import zstandard
from code_analyst_contracts import WorkspaceImportRequest
from control_plane_app.object_store import ObjectStore
from control_plane_app.workspace_imports import WorkspaceImportService
from moto import mock_aws

from control_plane_app.config import Settings as ControlPlaneSettings


def run_git(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def symlink_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "symlink-repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Symlink Repo\n")
    (repo_dir / "docs.md").write_text("workspace documentation\n")
    (repo_dir / "CLAUDE.md").symlink_to("docs.md")

    run_git(["init", "-b", "main"], cwd=repo_dir)
    run_git(["config", "user.name", "Code Analyst"], cwd=repo_dir)
    run_git(["config", "user.email", "code-analyst@example.com"], cwd=repo_dir)
    run_git(["add", "."], cwd=repo_dir)
    run_git(["commit", "-m", "Initial commit"], cwd=repo_dir)
    return repo_dir


@mock_aws
def test_workspace_import_skips_symlink_archive_members(
    tmp_path: Path,
    symlink_repo: Path,
) -> None:
    bucket_name = "code-analyst-symlink-archive"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    settings = ControlPlaneSettings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_tmp_dir=str(tmp_path / "workspace-import-tmp"),
    )
    object_store = ObjectStore(settings)
    service = WorkspaceImportService(settings=settings, object_store=object_store)

    artifacts = service.import_github_repo(
        request=WorkspaceImportRequest(
            tenant_id="tenant_test",
            repo_url=str(symlink_repo),
            ref="main",
            github_credential_ref="public",
        )
    )

    manifest_paths = {entry.path for entry in artifacts.manifest.files}
    assert "CLAUDE.md" not in manifest_paths
    assert "CLAUDE.md" not in artifacts.manifest.top_level_entries

    archive_payload = object_store.download_bytes(artifacts.snapshot_ref.archive_object_key)
    with tempfile.TemporaryDirectory(prefix="symlink-archive-") as temp_dir:
        archive_path = Path(temp_dir) / "repo.tar.zst"
        archive_path.write_bytes(archive_payload)
        with archive_path.open("rb") as raw_archive:
            decompressor = zstandard.ZstdDecompressor()
            with decompressor.stream_reader(raw_archive) as compressed_stream:
                with tarfile.open(fileobj=compressed_stream, mode="r|") as archive:
                    member_names = [member.name for member in archive]

    assert "workspace/CLAUDE.md" not in member_names
    assert "workspace/docs.md" in member_names
