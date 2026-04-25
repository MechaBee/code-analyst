from __future__ import annotations

import subprocess
from pathlib import Path

import boto3
import pytest
from code_analyst_contracts import SandboxSessionCreateRequest, WorkspaceImportRequest
from control_plane_app.config import Settings as ControlPlaneSettings
from control_plane_app.object_store import ObjectStore as ControlPlaneObjectStore
from control_plane_app.workspace_imports import WorkspaceImportService
from moto import mock_aws
from sandbox_supervisor_app.config import Settings as SandboxSupervisorSettings
from sandbox_supervisor_app.object_store import ObjectStore as SandboxObjectStore
from sandbox_supervisor_app.workspace_materializer import WorkspaceMaterializer


@pytest.fixture()
def sample_git_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "sample-repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Sample Repo\n")
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "service.py").write_text(
        "def answer() -> str:\n"
        "    return 'forty-two'\n"
    )

    run_git(["init", "-b", "main"], cwd=repo_dir)
    run_git(["config", "user.name", "Code Analyst"], cwd=repo_dir)
    run_git(["config", "user.email", "code-analyst@example.com"], cwd=repo_dir)
    run_git(["add", "."], cwd=repo_dir)
    run_git(["commit", "-m", "Initial commit"], cwd=repo_dir)
    return repo_dir


def run_git(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@mock_aws
def test_import_to_materialized_workspace(tmp_path: Path, sample_git_repo: Path) -> None:
    bucket_name = "code-analyst-test"
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket_name)

    control_plane_settings = ControlPlaneSettings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_tmp_dir=str(tmp_path / "control-plane-tmp"),
    )
    sandbox_settings = SandboxSupervisorSettings(
        s3_endpoint=None,
        s3_bucket=bucket_name,
        workspace_root_dir=str(tmp_path / "sandboxes"),
    )

    import_service = WorkspaceImportService(
        settings=control_plane_settings,
        object_store=ControlPlaneObjectStore(control_plane_settings),
    )
    materializer = WorkspaceMaterializer(
        settings=sandbox_settings,
        object_store=SandboxObjectStore(sandbox_settings),
    )

    import_request = WorkspaceImportRequest(
        tenant_id="tenant_test",
        repo_url=str(sample_git_repo),
        ref="main",
        github_credential_ref="public",
    )
    artifacts = import_service.import_github_repo(import_request)

    s3_client = boto3.client("s3", region_name="us-east-1")
    stored_keys = {
        item["Key"]
        for item in s3_client.list_objects_v2(Bucket=bucket_name).get("Contents", [])
    }
    assert artifacts.snapshot_ref.archive_object_key in stored_keys
    assert artifacts.snapshot_ref.manifest_object_key in stored_keys
    assert artifacts.snapshot_ref.metadata_object_key in stored_keys
    assert artifacts.manifest.file_count == 2

    materialized = materializer.create_or_resume(
        SandboxSessionCreateRequest(workspace=artifacts.snapshot_ref)
    )

    workspace_root = materialized.workspace_root
    assert workspace_root.exists()
    assert (workspace_root / "README.md").read_text() == "# Sample Repo\n"
    assert (workspace_root / "src" / "service.py").read_text() == (
        "def answer() -> str:\n"
        "    return 'forty-two'\n"
    )
    assert materialized.manifest.commit_sha == artifacts.response.source_commit
    assert materialized.session.session_state_key.startswith(
        "tenants/tenant_test/sandboxes/"
    )
    assert materialized.manifest.top_level_entries == ["README.md", "src"]
