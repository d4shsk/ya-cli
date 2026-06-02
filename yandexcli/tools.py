from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .safety import SafetyError, SafetyPolicy


MAX_READ_BYTES = 300 * 1024 * 1024
MAX_SEARCH_FILE_BYTES = 300 * 1024 * 1024


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
            "name": "edit_file",
            "description": "Replace an exact UTF-8 text fragment in an existing workspace file. Prefer this for focused edits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the workspace."},
                    "old_text": {"type": "string", "description": "Exact text currently present in the file."},
                    "new_text": {"type": "string", "description": "Replacement text."},
                    "replace_all": {"type": "boolean", "description": "Replace every occurrence instead of requiring exactly one.", "default": False},
                },
                "required": ["path", "old_text", "new_text"],
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
            "edit_file": self._edit_file,
            "list_files": self._list_files,
            "search_files": self._search_files,
            "run_shell": self._run_shell,
        }
        if canonical_name not in tools:
            raise SafetyError(f"Неизвестный инструмент: {name}")
        return tools[canonical_name](arguments)

    def _read_file(self, arguments: dict[str, Any]) -> str:
        path = self.policy.resolve_workspace_path(str(arguments.get("path", "")))
        if not path.is_file():
            raise SafetyError(f"Файл не найден: {self._display(path)}")
        data = _read_text_bytes(path, max_bytes=MAX_READ_BYTES)
        return data.decode("utf-8", errors="replace")

    def _write_file(self, arguments: dict[str, Any]) -> str:
        path = self.policy.resolve_workspace_path(str(arguments.get("path", "")))
        content = arguments.get("content")
        if not isinstance(content, str):
            raise SafetyError("write_file требует строковое поле content.")

        rel = self._display(path)
        if self.policy.dry_run:
            return f"Предпросмотр: было бы записано {len(content.encode('utf-8'))} байт в {rel}"
        if not self.policy.confirm_file_write(f"Записать файл {rel}?"):
            raise SafetyError(f"Пользователь отклонил запись в {rel}")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Записано {len(content.encode('utf-8'))} байт в {rel}"

    def _edit_file(self, arguments: dict[str, Any]) -> str:
        path = self.policy.resolve_workspace_path(str(arguments.get("path", "")))
        if not path.is_file():
            raise SafetyError(f"Файл не найден: {self._display(path)}")

        old_text = arguments.get("old_text")
        new_text = arguments.get("new_text")
        replace_all = bool(arguments.get("replace_all", False))
        if not isinstance(old_text, str) or not old_text:
            raise SafetyError("edit_file требует непустое строковое поле old_text.")
        if not isinstance(new_text, str):
            raise SafetyError("edit_file требует строковое поле new_text.")

        content = _read_text_bytes(path, max_bytes=MAX_READ_BYTES).decode("utf-8", errors="replace")
        count = content.count(old_text)
        if count == 0:
            raise SafetyError("edit_file не нашел old_text в файле.")
        if count > 1 and not replace_all:
            raise SafetyError(f"edit_file нашел old_text {count} раз(а); уточните фрагмент или передайте replace_all=true.")

        updated = content.replace(old_text, new_text) if replace_all else content.replace(old_text, new_text, 1)
        rel = self._display(path)
        replacements = count if replace_all else 1
        if self.policy.dry_run:
            return f"Предпросмотр: было бы заменено {replacements} фрагмент(а/ов) в {rel}"
        if not self.policy.confirm_file_write(f"Изменить файл {rel} ({replacements} замен)?"):
            raise SafetyError(f"Пользователь отклонил изменение {rel}")

        path.write_text(updated, encoding="utf-8")
        return f"Изменено {replacements} фрагмент(а/ов) в {rel}"

    def _list_files(self, arguments: dict[str, Any]) -> str:
        root = self.policy.resolve_workspace_path(str(arguments.get("path", ".")))
        limit = _int_arg(arguments.get("limit"), default=200, minimum=1, maximum=2000)
        if not root.exists():
            raise SafetyError(f"Путь не найден: {self._display(root)}")
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
        return "\n".join(results) if results else "(файлы не найдены)"

    def _search_files(self, arguments: dict[str, Any]) -> str:
        query = arguments.get("query")
        if not isinstance(query, str) or not query:
            raise SafetyError("search_files требует непустое поле query.")
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
                data = _read_text_bytes(path, max_bytes=MAX_SEARCH_FILE_BYTES)
                for line_no, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                    if query in line:
                        matches.append(f"{self._display(path)}:{line_no}: {line[:300]}")
                        if len(matches) >= limit:
                            break
            except (OSError, SafetyError):
                continue
        return "\n".join(matches) if matches else "(совпадения не найдены)"

    def _run_shell(self, arguments: dict[str, Any]) -> str:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            raise SafetyError("run_shell требует команду.")
        if not self.policy.allow_shell:
            raise SafetyError("Shell-инструмент выключен. Перезапустите CLI с --allow-shell, чтобы включить его.")
        if not self.policy.confirm_shell(f"Выполнить shell-команду: {command!r}?"):
            raise SafetyError("Пользователь отклонил shell-команду.")

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


def _read_text_bytes(path: Path, *, max_bytes: int) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise SafetyError(f"Не удалось прочитать файл: {path}") from exc
    if size > max_bytes:
        raise SafetyError(f"Файл слишком большой для чтения инструментом: {path.name} ({size} байт, лимит {max_bytes}).")

    data = path.read_bytes()
    if _looks_binary(data):
        raise SafetyError(f"Файл похож на бинарный и не будет прочитан как текст: {path.name}")
    return data


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:4096]


def canonical_tool_name(name: str) -> str:
    aliases = {"write": "write_file", "read": "read_file", "edit": "edit_file", "shell": "run_shell"}
    return aliases.get(name, name)
