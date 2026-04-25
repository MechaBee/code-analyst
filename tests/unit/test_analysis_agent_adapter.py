from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from sandbox_supervisor_app.analysis_adapter import (
    ClaudeAgentAnalysisAdapter,
    DraftAnswer,
    DraftCitation,
    OpenAIAnalysisAgentAdapter,
)
from sandbox_supervisor_app.config import Settings


def create_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text(
        "# Analysis Adapter Repo\n"
        "This workspace is used for adapter tests.\n"
    )
    src_dir = workspace / "src"
    src_dir.mkdir()
    (src_dir / "service.py").write_text(
        "def answer() -> str:\n"
        "    return 'forty-two'\n"
    )
    return workspace


def test_openai_analysis_adapter_builds_grounded_answer(tmp_path: Path) -> None:
    workspace = create_workspace(tmp_path)

    async def fake_run_agent(_context, _question: str) -> DraftAnswer:
        _context.record_read("README.md", 1, 2)
        _context.record_read("src/service.py", 1, 2)
        return DraftAnswer(
            answer_markdown=(
                "The workspace README identifies the repo, and `src/service.py` "
                "defines `answer()` returning `forty-two`."
            ),
            citations=[
                DraftCitation(path="README.md", start_line=1, end_line=2),
                DraftCitation(path="src/service.py", start_line=1, end_line=2),
            ],
            followups=["Inspect other services under `src/`."],
        )

    adapter = OpenAIAnalysisAgentAdapter(
        settings=Settings(analysis_backend="openai"),
        run_agent=fake_run_agent,
    )

    answer = asyncio.run(
        adapter.analyze(
            workspace_root=workspace,
            snapshot_id="snapshot_test",
            question="What does this repo contain?",
            top_level_entries=["README.md", "src"],
        )
    )

    assert "forty-two" in answer.answer_markdown
    assert len(answer.citations) == 2
    assert answer.citations[0].path == "README.md"
    assert answer.citations[1].path == "src/service.py"
    assert answer.followups == ["Inspect other services under `src/`."]
    assert all(citation.excerpt_hash.startswith("sha256:") for citation in answer.citations)


def test_openai_analysis_adapter_falls_back_when_citations_are_ungrounded(
    tmp_path: Path,
) -> None:
    workspace = create_workspace(tmp_path)

    async def fake_run_agent(_context, _question: str) -> DraftAnswer:
        return DraftAnswer(
            answer_markdown="This answer is not actually grounded in a file read.",
            citations=[
                DraftCitation(path="src/service.py", start_line=1, end_line=2),
            ],
            followups=[],
        )

    adapter = OpenAIAnalysisAgentAdapter(
        settings=Settings(
            analysis_backend="openai",
            analysis_fallback_to_deterministic=True,
        ),
        run_agent=fake_run_agent,
    )

    answer = asyncio.run(
        adapter.analyze(
            workspace_root=workspace,
            snapshot_id="snapshot_test",
            question="Summarize the workspace.",
            top_level_entries=["README.md", "src"],
        )
    )

    assert "Analysis Adapter Repo" in answer.answer_markdown
    assert "answer()" in answer.answer_markdown
    assert len(answer.citations) == 2


@pytest.mark.skipif(
    Settings().anthropic_api_key is None,
    reason="ANTHROPIC_API_KEY not set",
)
def test_claude_analysis_adapter_real_api_against_codebase(tmp_path: Path) -> None:
    """Live end-to-end test: Claude adapter on real code, no fallback allowed."""
    # Use the code-analyst repo itself as the workspace so there is real content.
    workspace = Path(__file__).parent.parent.parent.resolve()

    adapter = ClaudeAgentAnalysisAdapter(
        settings=Settings(
            analysis_backend="claude",
            analysis_fallback_to_deterministic=False,
        ),
    )

    answer = asyncio.run(
        adapter.analyze(
            workspace_root=workspace,
            snapshot_id="live-test",
            question="What is the overall architecture of this codebase? Describe the main services and their responsibilities.",
            top_level_entries=["services", "apps", "packages", "tests"],
        )
    )

    # Must have produced an answer with citations.
    assert answer.answer_markdown.strip()
    assert len(answer.citations) >= 1

    # Assert it did NOT fall back to the deterministic inspector output.
    deterministic_phrases = [
        "I inspected the materialized workspace and found these grounded points",
        "I inspected the materialized workspace, but I could not find a readable text file",
    ]
    for phrase in deterministic_phrases:
        assert phrase not in answer.answer_markdown, (
            f"Answer appears to be deterministic fallback (contains: {phrase!r})"
        )

    # Citations must point to real files in the workspace.
    for citation in answer.citations:
        assert (workspace / citation.path).exists(), (
            f"Citation path does not exist: {citation.path}"
        )
        assert citation.start_line >= 1
        assert citation.end_line >= citation.start_line
        assert citation.excerpt_hash.startswith("sha256:")


def test_claude_analysis_adapter_falls_back_when_no_citations(
    tmp_path: Path,
) -> None:
    workspace = create_workspace(tmp_path)

    async def fake_run_query(_workspace_path: Path, _question: str, _snapshot_id: str) -> DraftAnswer:
        return DraftAnswer(
            answer_markdown="This answer has no citations.",
            citations=[],
            followups=[],
        )

    adapter = ClaudeAgentAnalysisAdapter(
        settings=Settings(
            analysis_backend="claude",
            analysis_fallback_to_deterministic=True,
        ),
        run_query=fake_run_query,
    )

    answer = asyncio.run(
        adapter.analyze(
            workspace_root=workspace,
            snapshot_id="snapshot_test",
            question="Summarize the workspace.",
            top_level_entries=["README.md", "src"],
        )
    )

    assert "Analysis Adapter Repo" in answer.answer_markdown
    assert "answer()" in answer.answer_markdown
    assert len(answer.citations) == 2
