from __future__ import annotations

import asyncio
from pathlib import Path

from sandbox_supervisor_app.analysis_adapter import (
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
