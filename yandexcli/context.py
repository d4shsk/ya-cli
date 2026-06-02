from __future__ import annotations

import re
import subprocess
from pathlib import Path


KEY_CONTEXT_FILES = ("AGENTS.md", "README.md", "pyproject.toml", ".gitignore", "vulnerabilities.md")
MAX_CONTEXT_FILE_CHARS = 3000
MAX_RELEVANT_PATHS = 30
MAX_RELEVANT_MATCHES = 20
MAX_MATCH_READ_BYTES = 200_000


def build_workspace_context(*, workspace: Path, prompt: str, files: str) -> str:
    sections = [
        "Снимок рабочей директории перед началом задачи.",
        "Используй этот контекст как карту проекта; при необходимости всё равно читай конкретные файлы инструментами.",
        "",
        f"Workspace: {workspace}",
        "",
        "## Files",
        files,
    ]

    git_status = _git_status(workspace)
    if git_status:
        sections.extend(["", "## Git", git_status])

    key_files = _key_files_context(workspace)
    if key_files:
        sections.extend(["", "## Key Files", key_files])

    relevant = _relevant_context(workspace, prompt, files)
    if relevant:
        sections.extend(["", "## Prompt-Relevant Hints", relevant])

    return "\n".join(sections)


def _git_status(workspace: Path) -> str:
    if not (workspace / ".git").exists():
        return "(not a git repository)"

    status = _run_git(workspace, "status", "--short", "--branch")
    diff_stat = _run_git(workspace, "diff", "--stat")
    if diff_stat:
        return status + "\n\nDiff stat:\n" + diff_stat
    return status


def _run_git(workspace: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(workspace), *args],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "(git status unavailable)"
    output = (completed.stdout or completed.stderr).strip()
    return output[:4000] if output else "(clean)"


def _key_files_context(workspace: Path) -> str:
    entries: list[str] = []
    for name in KEY_CONTEXT_FILES:
        path = workspace / name
        if not path.is_file():
            continue
        text = _read_small_text(path, max_bytes=MAX_MATCH_READ_BYTES)
        if text is None:
            continue
        entries.append(f"### {name}\n{_clip(text, MAX_CONTEXT_FILE_CHARS)}")
    return "\n\n".join(entries)


def _relevant_context(workspace: Path, prompt: str, files: str) -> str:
    terms = _prompt_terms(prompt)
    if not terms:
        return ""

    file_paths = [line.strip() for line in files.splitlines() if line.strip() and not line.startswith("(")]
    relevant_paths = [path for path in file_paths if _matches_any(path, terms)][:MAX_RELEVANT_PATHS]
    matches = _content_matches(workspace, file_paths, terms)

    parts: list[str] = []
    if relevant_paths:
        parts.append("Paths matching prompt terms:\n" + "\n".join(relevant_paths))
    if matches:
        parts.append("Text matches:\n" + "\n".join(matches))
    return "\n\n".join(parts)


def _content_matches(workspace: Path, file_paths: list[str], terms: set[str]) -> list[str]:
    matches: list[str] = []
    for rel in file_paths:
        if len(matches) >= MAX_RELEVANT_MATCHES:
            break
        path = workspace / rel
        text = _read_small_text(path, max_bytes=MAX_MATCH_READ_BYTES)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            lowered = line.lower()
            if any(term in lowered for term in terms):
                matches.append(f"{rel}:{line_no}: {line[:200]}")
                break
    return matches


def _prompt_terms(prompt: str) -> set[str]:
    raw_terms = re.findall(r"[A-Za-zА-Яа-я0-9_.-]{3,}", prompt.lower())
    stopwords = {
        "как",
        "что",
        "это",
        "для",
        "или",
        "the",
        "and",
        "with",
        "from",
        "your",
        "мой",
        "моя",
        "мое",
        "моей",
    }
    return {term for term in raw_terms if term not in stopwords}


def _matches_any(value: str, terms: set[str]) -> bool:
    lowered = value.lower()
    return any(term in lowered for term in terms)


def _read_small_text(path: Path, *, max_bytes: int) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None
    return data.decode("utf-8", errors="replace")


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (truncated)"
