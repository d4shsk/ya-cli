from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .safety import SafetyError, SafetyPolicy


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file from the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the workspace."},
                },
                "required": ["path"],
            },
        }
    },
    {
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a UTF-8 text file in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the workspace."},
                    "content": {"type": "string", "description": "Full file content to write."},
                },
                "required": ["path", "content"],
            },
        }
    },
    {
        "function": {
            "name": "list_files",
            "description": "List files under a workspace directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path relative to the workspace.", "default": "."},
                    "limit": {"type": "integer", "description": "Maximum number of files.", "default": 200},
                },
            },
        }
    },
    {
        "function": {
            "name": "search_files",
            "description": "Search for text in workspace files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for."},
                    "path": {"type": "string", "description": "Directory path relative to the workspace.", "default": "."},
                    "limit": {"type": "integer", "description": "Maximum number of matches.", "default": 100},
                },
                "required": ["query"],
            },
        }
    },
    {
        "function": {
            "name": "run_shell",
            "description": "Run a shell command in the workspace. Use only when necessary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to run."},
                },
                "required": ["command"],
            },
        }
    },
]


@dataclass
class ToolRunner:
    policy: SafetyPolicy

    def run(self, name: str, arguments: dict[str, Any]) -> str:
        canonical_name = canonical_tool_name(name)
        tools: dict[str, Callable[[dict[str, Any]], str]] = {
            "read_file": self._read_file,
            "write_file": self._write_file,
            "list_files": self._list_files,
            "search_files": self._search_files,
            "run_shell": self._run_shell,
        }
        if canonical_name not in tools:
            raise SafetyError(f"Unknown tool: {name}")
        return tools[canonical_name](arguments)

    def _read_file(self, arguments: dict[str, Any]) -> str:
        path = self.policy.resolve_workspace_path(str(arguments.get("path", "")))
        if not path.is_file():
            raise SafetyError(f"File does not exist: {self._display(path)}")
        return path.read_text(encoding="utf-8", errors="replace")

    def _write_file(self, arguments: dict[str, Any]) -> str:
        path = self.policy.resolve_workspace_path(str(arguments.get("path", "")))
        content = arguments.get("content")
        if not isinstance(content, str):
            raise SafetyError("write_file requires string content.")

        rel = self._display(path)
        if self.policy.dry_run:
            return f"DRY RUN: would write {len(content.encode('utf-8'))} bytes to {rel}"
        if not self.policy.confirm(f"Write {rel}?"):
            raise SafetyError(f"User denied write to {rel}")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content.encode('utf-8'))} bytes to {rel}"

    def _list_files(self, arguments: dict[str, Any]) -> str:
        root = self.policy.resolve_workspace_path(str(arguments.get("path", ".")))
        limit = _int_arg(arguments.get("limit"), default=200, minimum=1, maximum=2000)
        if not root.exists():
            raise SafetyError(f"Path does not exist: {self._display(root)}")
        if root.is_file():
            return self._display(root)

        results: list[str] = []
        for child in sorted(root.rglob("*")):
            if len(results) >= limit:
                break
            if _skip_path(child):
                continue
            if child.is_file():
                results.append(self._display(child))
        return "\n".join(results) if results else "(no files)"

    def _search_files(self, arguments: dict[str, Any]) -> str:
        query = arguments.get("query")
        if not isinstance(query, str) or not query:
            raise SafetyError("search_files requires a non-empty query.")
        root = self.policy.resolve_workspace_path(str(arguments.get("path", ".")))
        limit = _int_arg(arguments.get("limit"), default=100, minimum=1, maximum=1000)

        matches: list[str] = []
        files = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in files:
            if len(matches) >= limit:
                break
            if _skip_path(path) or not path.is_file():
                continue
            try:
                for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if query in line:
                        matches.append(f"{self._display(path)}:{line_no}: {line[:300]}")
                        if len(matches) >= limit:
                            break
            except OSError:
                continue
        return "\n".join(matches) if matches else "(no matches)"

    def _run_shell(self, arguments: dict[str, Any]) -> str:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            raise SafetyError("run_shell requires a command.")
        if not self.policy.allow_shell:
            raise SafetyError("Shell tool is disabled. Re-run with --allow-shell to enable it.")
        if not self.policy.confirm(f"Run shell command: {command!r}?"):
            raise SafetyError("User denied shell command.")

        completed = subprocess.run(
            command,
            cwd=self.policy.workspace,
            shell=True,
            text=True,
            capture_output=True,
            timeout=120,
        )
        return json.dumps(
            {
                "returncode": completed.returncode,
                "stdout": completed.stdout[-8000:],
                "stderr": completed.stderr[-8000:],
            },
            ensure_ascii=False,
        )

    def _display(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.policy.workspace))
        except ValueError:
            return str(path)


def _skip_path(path: Path) -> bool:
    ignored_names = {".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", ".pytest_cache"}
    return any(part in ignored_names for part in path.parts)


def _int_arg(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def canonical_tool_name(name: str) -> str:
    aliases = {"write": "write_file", "read": "read_file", "shell": "run_shell"}
    return aliases.get(name, name)
