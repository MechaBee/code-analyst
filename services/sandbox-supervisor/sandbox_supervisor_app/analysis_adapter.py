from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from code_analyst_contracts import AnswerEnvelope, EvidenceRef
from pydantic import BaseModel, Field

from .config import Settings
from .workspace_inspector import STOPWORDS, TEXT_FILE_SUFFIXES, WorkspaceInspector


class AnalysisAdapterError(RuntimeError):
    """Raised when an analysis backend cannot produce a grounded answer."""


class AnalysisAdapterConfigurationError(AnalysisAdapterError):
    """Raised when an analysis backend is selected but not configured correctly."""


@dataclass(slots=True)
class AnalysisContext:
    workspace_root: Path
    snapshot_id: str
    top_level_entries: list[str]
    max_search_results: int
    max_read_lines: int
    max_list_files: int
    read_spans: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    _text_files: list[Path] | None = None

    def text_files(self) -> list[Path]:
        if self._text_files is None:
            self._text_files = []
            for file_path in sorted(self.workspace_root.rglob("*")):
                if not file_path.is_file() or file_path.is_symlink():
                    continue
                if file_path.suffix and file_path.suffix.lower() not in TEXT_FILE_SUFFIXES:
                    continue
                if file_path.stat().st_size > 256 * 1024:
                    continue
                self._text_files.append(file_path)
        return self._text_files

    def record_read(self, path: str, start_line: int, end_line: int) -> None:
        self.read_spans.setdefault(path, []).append((start_line, end_line))

    def was_read(self, path: str, start_line: int, end_line: int) -> bool:
        for read_start, read_end in self.read_spans.get(path, []):
            if read_start <= start_line and read_end >= end_line:
                return True
        return False


class DraftCitation(BaseModel):
    path: str = Field(description="Relative file path inside the workspace.")
    start_line: int = Field(ge=1, description="1-based starting line number.")
    end_line: int = Field(ge=1, description="1-based ending line number.")


class DraftAnswer(BaseModel):
    answer_markdown: str = Field(
        description="Concise grounded answer in Markdown for a business analyst or tester.",
    )
    citations: list[DraftCitation] = Field(
        default_factory=list,
        description="Exact file and line ranges that ground the answer.",
    )
    followups: list[str] = Field(
        default_factory=list,
        description="Short follow-up questions that would deepen the analysis.",
    )


class DeterministicAnalysisAdapter:
    def __init__(self, inspector: WorkspaceInspector | None = None) -> None:
        self._inspector = inspector or WorkspaceInspector()

    async def analyze(
        self,
        *,
        workspace_root: Path | str,
        snapshot_id: str,
        question: str,
        top_level_entries: list[str],
    ) -> AnswerEnvelope:
        return await asyncio.to_thread(
            self._inspector.inspect,
            workspace_root=workspace_root,
            snapshot_id=snapshot_id,
            question=question,
            top_level_entries=top_level_entries,
        )


RunAgentCallable = Callable[[AnalysisContext, str], Awaitable[DraftAnswer]]


class OpenAIAnalysisAgentAdapter:
    def __init__(
        self,
        *,
        settings: Settings,
        fallback_adapter: DeterministicAnalysisAdapter | None = None,
        run_agent: RunAgentCallable | None = None,
    ) -> None:
        self._settings = settings
        self._fallback_to_deterministic = settings.analysis_fallback_to_deterministic
        self._fallback_adapter = fallback_adapter
        if self._fallback_adapter is None and self._fallback_to_deterministic:
            self._fallback_adapter = DeterministicAnalysisAdapter()
        self._run_agent_override = run_agent

    async def analyze(
        self,
        *,
        workspace_root: Path | str,
        snapshot_id: str,
        question: str,
        top_level_entries: list[str],
    ) -> AnswerEnvelope:
        context = AnalysisContext(
            workspace_root=Path(workspace_root),
            snapshot_id=snapshot_id,
            top_level_entries=top_level_entries,
            max_search_results=self._settings.analysis_max_search_results,
            max_read_lines=self._settings.analysis_max_read_lines,
            max_list_files=self._settings.analysis_max_list_files,
        )

        try:
            draft = await self._run_agent(context, question)
            return self._draft_to_answer(context, draft)
        except AnalysisAdapterConfigurationError:
            raise
        except AnalysisAdapterError:
            if self._fallback_adapter is not None and self._fallback_to_deterministic:
                return await self._fallback_adapter.analyze(
                    workspace_root=workspace_root,
                    snapshot_id=snapshot_id,
                    question=question,
                    top_level_entries=top_level_entries,
                )
            raise
        except Exception as error:
            if self._fallback_adapter is not None and self._fallback_to_deterministic:
                return await self._fallback_adapter.analyze(
                    workspace_root=workspace_root,
                    snapshot_id=snapshot_id,
                    question=question,
                    top_level_entries=top_level_entries,
                )
            raise AnalysisAdapterError(
                "OpenAI analysis run failed before a grounded answer was produced."
            ) from error

    async def _run_agent(
        self,
        context: AnalysisContext,
        question: str,
    ) -> DraftAnswer:
        if self._run_agent_override is not None:
            return await self._run_agent_override(context, question)
        return await self._run_agent_with_sdk(context, question)

    async def _run_agent_with_sdk(
        self,
        context: AnalysisContext,
        question: str,
    ) -> DraftAnswer:
        if not os.getenv("OPENAI_API_KEY"):
            raise AnalysisAdapterConfigurationError(
                "ANALYSIS_BACKEND is set to `openai`, but OPENAI_API_KEY is not configured."
            )

        try:
            from agents import Agent, ModelSettings, RunContextWrapper, Runner, function_tool
            from openai.types.shared import Reasoning
        except ImportError as error:
            raise AnalysisAdapterConfigurationError(
                "The sandbox supervisor OpenAI backend requires the `openai-agents` package."
            ) from error

        @function_tool
        def describe_workspace(wrapper: RunContextWrapper[AnalysisContext]) -> str:
            """Return a high-level summary of the current workspace."""

            context = wrapper.context
            summary = {
                "top_level_entries": context.top_level_entries[:20],
                "text_file_count": len(context.text_files()),
            }
            return json.dumps(summary, indent=2)

        @function_tool
        def list_files(
            wrapper: RunContextWrapper[AnalysisContext],
            directory: str | None = None,
            limit: int | None = None,
        ) -> str:
            """List readable text files in the workspace.

            Args:
                directory: Optional relative directory prefix to filter by.
                limit: Maximum number of paths to return.
            """

            run_context = wrapper.context
            max_results = min(
                limit or run_context.max_list_files,
                run_context.max_list_files,
            )
            directory_prefix = ""
            if directory:
                prefix_path = self._resolve_workspace_entry(
                    run_context.workspace_root,
                    directory,
                )
                directory_prefix = prefix_path.relative_to(
                    run_context.workspace_root
                ).as_posix()

            matched_paths: list[str] = []
            for file_path in run_context.text_files():
                relative_path = file_path.relative_to(run_context.workspace_root).as_posix()
                if directory_prefix and not relative_path.startswith(directory_prefix):
                    continue
                matched_paths.append(relative_path)
                if len(matched_paths) >= max_results:
                    break

            if not matched_paths:
                return "No readable text files matched that request."
            return "\n".join(matched_paths)

        @function_tool
        def search_text(
            wrapper: RunContextWrapper[AnalysisContext],
            query: str,
            limit: int | None = None,
        ) -> str:
            """Search readable workspace files for text or symbol matches.

            Args:
                query: Text or symbol to search for.
                limit: Maximum number of results to return.
            """

            run_context = wrapper.context
            keywords = self._extract_keywords(query)
            if not keywords and query.strip():
                keywords = [query.strip().lower()]
            max_results = min(
                limit or run_context.max_search_results,
                run_context.max_search_results,
            )
            hits: list[dict[str, str | int]] = []

            for file_path in run_context.text_files():
                try:
                    lines = file_path.read_text(encoding="utf-8").splitlines()
                except UnicodeDecodeError:
                    continue
                relative_path = file_path.relative_to(run_context.workspace_root).as_posix()
                path_lower = relative_path.lower()
                path_keyword_hits = sum(1 for keyword in keywords if keyword in path_lower)
                for line_number, line in enumerate(lines, start=1):
                    line_lower = line.lower()
                    line_hits = [keyword for keyword in keywords if keyword in line_lower]
                    literal_hit = query.strip().lower() in line_lower if query.strip() else False
                    if not literal_hit and not line_hits and not path_keyword_hits:
                        continue
                    score = len(line_hits) * 10 + path_keyword_hits * 3 + (5 if literal_hit else 0)
                    hits.append(
                        {
                            "path": relative_path,
                            "line": line_number,
                            "score": score,
                            "excerpt": line.strip()[:220],
                        }
                    )

            hits.sort(
                key=lambda item: (
                    -int(item["score"]),
                    str(item["path"]),
                    int(item["line"]),
                )
            )
            if not hits:
                return "No matches were found in readable text files."
            return json.dumps(hits[:max_results], indent=2)

        @function_tool
        def read_file(
            wrapper: RunContextWrapper[AnalysisContext],
            path: str,
            start_line: int = 1,
            end_line: int | None = None,
        ) -> str:
            """Read a file excerpt with line numbers. Use this before citing a file.

            Args:
                path: Relative path to the file inside the workspace.
                start_line: 1-based line number to start reading from.
                end_line: Optional inclusive line number to stop at.
            """

            run_context = wrapper.context
            resolved_path = self._resolve_relative_path(run_context.workspace_root, path)
            lines = self._load_text_lines(resolved_path)
            if not lines:
                relative_path = resolved_path.relative_to(run_context.workspace_root).as_posix()
                run_context.record_read(relative_path, 1, 1)
                return f"FILE {relative_path} is empty."

            safe_start = max(1, start_line)
            safe_end = end_line or (safe_start + run_context.max_read_lines - 1)
            if safe_end < safe_start:
                raise ValueError("end_line must be greater than or equal to start_line")
            safe_end = min(safe_end, safe_start + run_context.max_read_lines - 1)
            safe_end = min(safe_end, len(lines))

            relative_path = resolved_path.relative_to(run_context.workspace_root).as_posix()
            run_context.record_read(relative_path, safe_start, safe_end)
            excerpt = "\n".join(
                f"{line_number}: {lines[line_number - 1]}"
                for line_number in range(safe_start, safe_end + 1)
            )
            return f"FILE {relative_path} LINES {safe_start}-{safe_end}\n{excerpt}"

        model_settings = ModelSettings(
            parallel_tool_calls=False,
            truncation="auto",
            verbosity="low",
        )
        if self._settings.openai_model.startswith("gpt-5"):
            model_settings = ModelSettings(
                parallel_tool_calls=False,
                truncation="auto",
                verbosity="low",
                reasoning=Reasoning(effort=self._settings.openai_reasoning_effort),
            )

        agent = Agent[AnalysisContext](
            name="Codebase Analysis Agent",
            model=self._settings.openai_model,
            model_settings=model_settings,
            instructions=(
                "You analyze a software workspace for business analysts and testers. "
                "Use the available tools to inspect the local codebase before answering. "
                "Ground every material claim in file content you actually read with `read_file`. "
                "Prefer concise, high-signal answers. Keep citations tight and exact. "
                "If the question is broad, summarize the most relevant findings and suggest a narrower follow-up."
            ),
            tools=[describe_workspace, list_files, search_text, read_file],
            output_type=DraftAnswer,
        )

        workspace_summary = ", ".join(context.top_level_entries[:10]) or "(empty workspace root)"
        result = await Runner.run(
            agent,
            (
                "Workspace top-level entries: "
                f"{workspace_summary}\n\n"
                "Answer this question about the materialized codebase:\n"
                f"{question}"
            ),
            context=context,
            max_turns=8,
        )
        final_output = result.final_output
        if final_output is None:
            raise AnalysisAdapterError(
                "OpenAI analysis run completed without producing a final output."
            )
        if not isinstance(final_output, DraftAnswer):
            raise AnalysisAdapterError(
                "OpenAI analysis run returned an unexpected output type."
            )
        return final_output

    def _draft_to_answer(
        self,
        context: AnalysisContext,
        draft: DraftAnswer,
    ) -> AnswerEnvelope:
        answer_markdown = draft.answer_markdown.strip()
        if not answer_markdown:
            raise AnalysisAdapterError(
                "OpenAI analysis run returned an empty answer."
            )

        citations: list[EvidenceRef] = []
        seen_ranges: set[tuple[str, int, int]] = set()
        for draft_citation in draft.citations:
            citation = self._build_citation(context, draft_citation)
            if citation is None:
                continue
            citation_key = (citation.path, citation.start_line, citation.end_line)
            if citation_key in seen_ranges:
                continue
            citations.append(citation)
            seen_ranges.add(citation_key)
            if len(citations) == 5:
                break

        if not citations:
            raise AnalysisAdapterError(
                "OpenAI analysis run did not produce any valid citations grounded in file reads."
            )

        followups = [
            followup.strip()
            for followup in draft.followups
            if followup.strip()
        ][:3]
        return AnswerEnvelope(
            answer_markdown=answer_markdown,
            citations=citations,
            followups=followups,
        )

    def _build_citation(
        self,
        context: AnalysisContext,
        draft_citation: DraftCitation,
    ) -> EvidenceRef | None:
        try:
            resolved_path = self._resolve_relative_path(
                context.workspace_root,
                draft_citation.path,
            )
        except ValueError:
            return None

        lines = self._load_text_lines(resolved_path)
        if not lines:
            return None

        relative_path = resolved_path.relative_to(context.workspace_root).as_posix()
        start_line = min(max(1, draft_citation.start_line), len(lines))
        end_line = min(max(start_line, draft_citation.end_line), len(lines))
        if not context.was_read(relative_path, start_line, end_line):
            return None

        excerpt_lines = lines[start_line - 1 : end_line]
        return EvidenceRef(
            snapshot_id=context.snapshot_id,
            path=relative_path,
            start_line=start_line,
            end_line=end_line,
            excerpt_hash=self._excerpt_hash(excerpt_lines),
        )

    def _extract_keywords(self, query: str) -> list[str]:
        words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", query.lower())
        keywords = [
            word
            for word in words
            if word not in STOPWORDS
        ]
        return list(dict.fromkeys(keywords))

    def _resolve_relative_path(self, workspace_root: Path, relative_path: str) -> Path:
        candidate = self._resolve_workspace_entry(workspace_root, relative_path)
        if not candidate.is_file():
            raise ValueError("Path does not point to a file.")
        return candidate

    def _resolve_workspace_entry(self, workspace_root: Path, relative_path: str) -> Path:
        candidate = (workspace_root / relative_path).resolve()
        root = workspace_root.resolve()
        if root != candidate and root not in candidate.parents:
            raise ValueError("Path escapes the workspace root.")
        if not candidate.exists():
            raise ValueError("Path does not exist in the workspace.")
        return candidate

    def _load_text_lines(self, file_path: Path) -> list[str]:
        try:
            return file_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as error:
            raise AnalysisAdapterError(
                f"File `{file_path.name}` could not be decoded as UTF-8."
            ) from error

    def _excerpt_hash(self, lines: list[str]) -> str:
        excerpt = "\n".join(lines).encode("utf-8")
        digest = hashlib.sha256(excerpt).hexdigest()
        return f"sha256:{digest}"


def build_analysis_adapter(settings: Settings) -> DeterministicAnalysisAdapter | OpenAIAnalysisAgentAdapter:
    deterministic = DeterministicAnalysisAdapter()
    backend = settings.analysis_backend.strip().lower()
    if backend == "deterministic":
        return deterministic
    if backend == "openai":
        fallback = deterministic if settings.analysis_fallback_to_deterministic else None
        return OpenAIAnalysisAgentAdapter(
            settings=settings,
            fallback_adapter=fallback,
        )
    raise AnalysisAdapterConfigurationError(
        f"Unsupported ANALYSIS_BACKEND value `{settings.analysis_backend}`."
    )
