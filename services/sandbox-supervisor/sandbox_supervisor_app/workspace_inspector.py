from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from code_analyst_contracts import AnswerEnvelope, EvidenceRef


TEXT_FILE_SUFFIXES = {
    ".c",
    ".cfg",
    ".conf",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

STOPWORDS = {
    "about",
    "code",
    "does",
    "flow",
    "from",
    "how",
    "imported",
    "into",
    "module",
    "repo",
    "repository",
    "show",
    "summarize",
    "summary",
    "tell",
    "that",
    "the",
    "this",
    "was",
    "what",
    "where",
    "which",
    "workspace",
}

DECLARATION_PATTERNS = [
    re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\s*export\s+function\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\s*const\s+([A-Za-z_][A-Za-z0-9_]*)\s*="),
]

RETURN_LITERAL_PATTERN = re.compile(r"""^\s*return\s+(['"])(.+?)\1""")


@dataclass(slots=True)
class TextDocument:
    path: str
    full_path: Path
    lines: list[str]


@dataclass(slots=True)
class Candidate:
    path: str
    score: int
    start_line: int
    end_line: int
    excerpt_lines: list[str]


class WorkspaceInspector:
    def inspect(
        self,
        *,
        workspace_root: Path | str,
        snapshot_id: str,
        question: str,
        top_level_entries: list[str],
    ) -> AnswerEnvelope:
        root_path = Path(workspace_root)
        documents = self._load_documents(root_path)
        keywords = self._extract_keywords(question)
        candidates = self._find_keyword_candidates(documents, keywords)

        if not candidates:
            candidates = self._build_fallback_candidates(documents)

        selected = self._select_candidates(candidates)
        citations = [
            EvidenceRef(
                snapshot_id=snapshot_id,
                path=candidate.path,
                start_line=candidate.start_line,
                end_line=candidate.end_line,
                excerpt_hash=self._excerpt_hash(candidate.excerpt_lines),
            )
            for candidate in selected
        ]

        if not selected:
            answer_markdown = (
                "I inspected the materialized workspace, but I could not find a readable "
                "text file to ground an answer."
            )
            followups = ["Ask about a specific file or function name."]
            return AnswerEnvelope(
                answer_markdown=answer_markdown,
                citations=[],
                followups=followups,
            )

        bullet_lines = [
            f"- {self._summarize_candidate(candidate)}"
            for candidate in selected
        ]
        answer_markdown = (
            "I inspected the materialized workspace and found these grounded points:\n\n"
            + "\n".join(bullet_lines)
        )
        followups = self._build_followups(selected, top_level_entries)
        return AnswerEnvelope(
            answer_markdown=answer_markdown,
            citations=citations,
            followups=followups,
        )

    def _load_documents(self, workspace_root: Path) -> list[TextDocument]:
        documents: list[TextDocument] = []
        for file_path in sorted(workspace_root.rglob("*")):
            if not file_path.is_file() or file_path.is_symlink():
                continue
            if file_path.stat().st_size > 256 * 1024:
                continue
            if file_path.suffix.lower() not in TEXT_FILE_SUFFIXES and file_path.suffix:
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            documents.append(
                TextDocument(
                    path=file_path.relative_to(workspace_root).as_posix(),
                    full_path=file_path,
                    lines=content.splitlines(),
                )
            )
        return documents

    def _extract_keywords(self, question: str) -> list[str]:
        words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", question.lower())
        keywords = [
            word
            for word in words
            if word not in STOPWORDS
        ]
        return list(dict.fromkeys(keywords))

    def _find_keyword_candidates(
        self,
        documents: list[TextDocument],
        keywords: list[str],
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        if not keywords:
            return candidates

        for document in documents:
            path_lower = document.path.lower()
            path_keyword_hits = sum(1 for keyword in keywords if keyword in path_lower)
            for index, line in enumerate(document.lines, start=1):
                line_lower = line.lower()
                line_hits = [keyword for keyword in keywords if keyword in line_lower]
                if not line_hits and not path_keyword_hits:
                    continue
                score = len(line_hits) * 10 + path_keyword_hits * 3
                if score <= 0:
                    continue
                start_line = max(1, index - 1)
                end_line = min(len(document.lines), index + 1)
                candidates.append(
                    Candidate(
                        path=document.path,
                        score=score,
                        start_line=start_line,
                        end_line=end_line,
                        excerpt_lines=document.lines[start_line - 1 : end_line],
                    )
                )
        return candidates

    def _build_fallback_candidates(
        self,
        documents: list[TextDocument],
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        for document in documents:
            path_lower = document.path.lower()
            if path_lower.endswith("readme.md") or path_lower == "readme.md":
                candidate = self._candidate_from_readme(document)
                if candidate is not None:
                    candidates.append(candidate)
                    continue

            candidate = self._candidate_from_declaration(document)
            if candidate is not None:
                candidates.append(candidate)

        return candidates

    def _candidate_from_readme(self, document: TextDocument) -> Candidate | None:
        non_empty = [
            (index, line)
            for index, line in enumerate(document.lines, start=1)
            if line.strip()
        ]
        if not non_empty:
            return None
        start_line = non_empty[0][0]
        end_line = min(len(document.lines), start_line + 2)
        return Candidate(
            path=document.path,
            score=100,
            start_line=start_line,
            end_line=end_line,
            excerpt_lines=document.lines[start_line - 1 : end_line],
        )

    def _candidate_from_declaration(self, document: TextDocument) -> Candidate | None:
        for index, line in enumerate(document.lines, start=1):
            for pattern in DECLARATION_PATTERNS:
                if pattern.search(line):
                    start_line = index
                    end_line = min(len(document.lines), index + 2)
                    return Candidate(
                        path=document.path,
                        score=80,
                        start_line=start_line,
                        end_line=end_line,
                        excerpt_lines=document.lines[start_line - 1 : end_line],
                    )
        return None

    def _select_candidates(self, candidates: list[Candidate]) -> list[Candidate]:
        selected: list[Candidate] = []
        seen_paths: set[str] = set()
        for candidate in sorted(
            candidates,
            key=lambda item: (-item.score, item.path, item.start_line),
        ):
            if candidate.path in seen_paths:
                continue
            selected.append(candidate)
            seen_paths.add(candidate.path)
            if len(selected) == 3:
                break
        return selected

    def _summarize_candidate(self, candidate: Candidate) -> str:
        cleaned_lines = [line.strip() for line in candidate.excerpt_lines if line.strip()]
        if not cleaned_lines:
            return f"`{candidate.path}` contains relevant but empty-looking content."

        first_line = cleaned_lines[0]
        if first_line.startswith("#"):
            heading = first_line.lstrip("#").strip()
            return f"`{candidate.path}` identifies the workspace as {heading!r}."

        declaration_name = self._extract_declaration_name(cleaned_lines)
        if declaration_name:
            return_literal = self._extract_return_literal(cleaned_lines[1:])
            if return_literal is not None:
                return (
                    f"`{candidate.path}` defines {declaration_name} and returns "
                    f"`{return_literal}`."
                )
            return f"`{candidate.path}` defines {declaration_name}."

        excerpt = cleaned_lines[0]
        if len(excerpt) > 120:
            excerpt = f"{excerpt[:117]}..."
        return f"`{candidate.path}` contains `{excerpt}`."

    def _extract_declaration_name(self, lines: list[str]) -> str | None:
        for line in lines:
            for pattern in DECLARATION_PATTERNS:
                match = pattern.search(line)
                if match:
                    name = match.group(1)
                    if line.lstrip().startswith("class "):
                        return f"class `{name}`"
                    if line.lstrip().startswith("def "):
                        return f"`{name}()`"
                    return f"`{name}`"
        return None

    def _extract_return_literal(self, lines: list[str]) -> str | None:
        for line in lines:
            match = RETURN_LITERAL_PATTERN.search(line)
            if match:
                return match.group(2)
        return None

    def _excerpt_hash(self, lines: list[str]) -> str:
        excerpt = "\n".join(lines).encode("utf-8")
        digest = hashlib.sha256(excerpt).hexdigest()
        return f"sha256:{digest}"

    def _build_followups(
        self,
        candidates: list[Candidate],
        top_level_entries: list[str],
    ) -> list[str]:
        followups: list[str] = []
        for candidate in candidates[:2]:
            followups.append(f"Show more detail from `{candidate.path}`.")
        if top_level_entries:
            followups.append(
                f"Inspect another top-level entry such as `{top_level_entries[0]}`."
            )
        else:
            followups.append("Ask about a specific file path, symbol, or behavior.")
        return followups[:3]
