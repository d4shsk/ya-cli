from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .attachments import expand_at_references, message_with_attachments, strip_images_from_messages
from .context import build_workspace_context
from .legacy import contains_pseudo_tool_call, parse_legacy_tool_calls
from .safety import SafetyError
from .tools import TOOL_SCHEMAS, ToolRunner, canonical_tool_name


AgentMode = Literal["plan", "edit"]
PLAN_TOOL_NAMES = {"read_file", "list_files", "search_files"}


SYSTEM_PROMPT = """You are YandexCLI, a terminal coding assistant.

Use the provided tools whenever you need to inspect, create, or edit files.
Before starting work, use the workspace context from the user message and inspect existing files when needed.
Do not print file contents in chat when a file should be created or modified.
For small focused changes, prefer edit_file with exact old_text/new_text. Use write_file only when creating a new file or replacing a full file intentionally.
Never print pseudo tool calls like [write_file] or [TOOL_CALL_START].
For HTML/CSS/frontend tasks: do not reference local images, fonts, scripts, or other assets unless they already exist in the workspace or you create them. If assets are unavailable, use CSS, inline SVG, gradients, or self-contained markup instead of broken local paths.
Prefer small, focused changes. Never attempt to access files outside the workspace.
When unsure about security implications, mention the concern and update vulnerabilities.md.
"""


PLAN_MODE_PROMPT = """Mode: Plan Mode.

Inspect the workspace as needed, then respond with a concise implementation plan.
Do not modify files, do not call edit/write tools, and do not run shell commands.
If the user asks for code changes, explain what would be changed and wait for Edit Mode.
"""


EDIT_MODE_PROMPT = """Mode: Edit Mode.

You may inspect and modify files using the provided tools.
Prefer edit_file for focused edits and write_file only for new files or intentional full replacements.
"""


FRONTEND_QA_PROMPT = """Проверь только что записанные HTML/CSS/frontend-файлы перед финальным ответом.

Обязательно проверь:
- нет ли ссылок на несуществующие локальные изображения, CSS, JS, шрифты или другие assets;
- не осталось ли placeholder-путей вроде logo.png, product1.jpg, door-background.jpg без созданных файлов;
- страница не должна полагаться на локальные assets, которых нет в workspace;
- если assets отсутствуют, исправь HTML/CSS через CSS-градиенты, inline SVG, data URI или самодостаточную разметку.

Если нужно исправить файлы, используй write_file. Если всё корректно, кратко ответь, что готово.
"""


class CompletionClient(Protocol):
    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> dict[str, Any]:
        ...


@dataclass
class Agent:
    client: CompletionClient
    tool_runner: ToolRunner
    max_iterations: int = 20
    temperature: float = 0.2
    max_tokens: int = 8192
    verbose: bool = True
    messages: list[dict[str, Any]] | None = None

    def run(self, prompt: str, history: list[dict[str, Any]] | None = None, *, remember: bool = False, mode: AgentMode = "edit") -> str:
        mode = normalize_mode(mode)
        attachments = expand_at_references(prompt, self.tool_runner.policy)
        prompt = attachments.prompt
        if history is not None:
            messages = list(history)
        elif remember:
            messages = self.messages if self.messages is not None else [{"role": "system", "text": SYSTEM_PROMPT}]
        else:
            messages = [{"role": "system", "text": SYSTEM_PROMPT}]

        if _needs_workspace_snapshot(messages):
            messages.append({"role": "user", "text": self._workspace_snapshot_message(prompt)})

        messages.append({"role": "user", "text": _mode_prompt(mode)})
        messages.append(message_with_attachments("user", prompt, attachments.images))
        frontend_qa_requests = 0

        for iteration in range(1, self.max_iterations + 1):
            response = self.client.complete(
                messages=[dict(message) for message in messages],
                tools=_tool_schemas_for_mode(mode),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            message, status = _extract_message(response)

            native_calls = message.get("toolCallList", {}).get("toolCalls", [])
            if native_calls:
                if self.verbose:
                    print(f"[agent] iteration {iteration}: executing {len(native_calls)} native tool call(s)")
                messages.append({"role": "assistant", "toolCallList": {"toolCalls": native_calls}})
                messages.append(self._execute_tool_calls(native_calls, mode=mode))
                if _has_frontend_change(native_calls) and frontend_qa_requests < 2:
                    frontend_qa_requests += 1
                    messages.append({"role": "user", "text": FRONTEND_QA_PROMPT})
                continue

            text = message.get("text", "")
            legacy_calls = parse_legacy_tool_calls(text) if isinstance(text, str) else []
            if legacy_calls:
                if self.verbose:
                    print(f"[agent] iteration {iteration}: recovered {len(legacy_calls)} text tool call(s)")
                tool_calls = [
                    {
                        "functionCall": {
                            "name": canonical_tool_name(legacy_call.name),
                            "arguments": legacy_call.arguments,
                        }
                    }
                    for legacy_call in legacy_calls
                ]
                messages.append({"role": "assistant", "toolCallList": {"toolCalls": tool_calls}})
                messages.append(self._execute_tool_calls(tool_calls, mode=mode))
                if _has_frontend_change(tool_calls) and frontend_qa_requests < 2:
                    frontend_qa_requests += 1
                    messages.append({"role": "user", "text": FRONTEND_QA_PROMPT})
                continue

            if isinstance(text, str) and contains_pseudo_tool_call(text):
                messages.append(
                    {
                        "role": "user",
                        "text": (
                            "Your previous response printed a pseudo tool call instead of using the provided tools. "
                            "Repeat the action now using native toolCallList only. Do not print JSON or file contents."
                        ),
                    }
                )
                continue

            if status and self.verbose:
                print(f"[agent] final status: {status}")
            final_text = text if isinstance(text, str) else json.dumps(message, ensure_ascii=False)
            messages.append({"role": "assistant", "text": final_text})
            if remember:
                self.messages = strip_images_from_messages(messages)
            return final_text

        raise RuntimeError(f"Reached max_iterations={self.max_iterations} without a final answer.")

    def _workspace_snapshot_message(self, prompt: str) -> str:
        try:
            files = self.tool_runner.run("list_files", {"path": ".", "limit": 200})
        except Exception as exc:
            files = f"Не удалось получить список файлов: {exc}"
        return build_workspace_context(
            workspace=self.tool_runner.policy.workspace,
            prompt=prompt,
            files=files,
        )

    def _execute_tool_calls(self, tool_calls: list[dict[str, Any]], *, mode: AgentMode = "edit") -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        allowed_tool_names = _allowed_tool_names(mode)
        for call in tool_calls:
            function_call = call.get("functionCall", {})
            name = function_call.get("name")
            arguments = function_call.get("arguments", {})
            if not isinstance(name, str):
                name = ""
            if not isinstance(arguments, dict):
                arguments = {}

            try:
                canonical_name = canonical_tool_name(name)
                if canonical_name not in allowed_tool_names:
                    raise SafetyError(f"Инструмент {canonical_name} отключен в Plan Mode.")
                content = self.tool_runner.run(name, arguments)
            except SafetyError as exc:
                content = f"TOOL_ERROR: {exc}"
            except Exception as exc:
                content = f"TOOL_ERROR: unexpected {type(exc).__name__}: {exc}"

            results.append(
                {
                    "functionResult": {
                        "name": name,
                        "content": content,
                    }
                }
            )

        return {"role": "user", "toolResultList": {"toolResults": results}}


def normalize_mode(mode: str) -> AgentMode:
    return "plan" if mode == "plan" else "edit"


def _mode_prompt(mode: AgentMode) -> str:
    return PLAN_MODE_PROMPT if mode == "plan" else EDIT_MODE_PROMPT


def _allowed_tool_names(mode: AgentMode) -> set[str]:
    if mode == "plan":
        return set(PLAN_TOOL_NAMES)
    return {_tool_schema_name(schema) for schema in TOOL_SCHEMAS}


def _tool_schemas_for_mode(mode: AgentMode) -> list[dict[str, Any]]:
    if mode == "edit":
        return TOOL_SCHEMAS
    return [schema for schema in TOOL_SCHEMAS if _tool_schema_name(schema) in PLAN_TOOL_NAMES]


def _tool_schema_name(schema: dict[str, Any]) -> str:
    function = schema.get("function", {})
    name = function.get("name") if isinstance(function, dict) else ""
    return name if isinstance(name, str) else ""


def _extract_message(response: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    try:
        alternative = response["result"]["alternatives"][0]
        message = alternative["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected Yandex response shape: {json.dumps(response, ensure_ascii=False)[:1000]}") from exc

    if not isinstance(message, dict):
        raise RuntimeError(f"Unexpected message shape: {message!r}")
    status = alternative.get("status")
    return message, status if isinstance(status, str) else None


def _needs_workspace_snapshot(messages: list[dict[str, Any]]) -> bool:
    return not any(
        message.get("role") == "user" and isinstance(message.get("text"), str) and message["text"].startswith("Снимок рабочей директории")
        for message in messages
    )


def _has_frontend_change(tool_calls: list[dict[str, Any]]) -> bool:
    frontend_suffixes = (".html", ".htm", ".css", ".js", ".jsx", ".tsx", ".ts")
    for call in tool_calls:
        function_call = call.get("functionCall", {})
        name = canonical_tool_name(str(function_call.get("name", "")))
        arguments = function_call.get("arguments", {})
        if name not in {"write_file", "edit_file"} or not isinstance(arguments, dict):
            continue
        path = str(arguments.get("path", "")).lower()
        if path.endswith(frontend_suffixes):
            return True
    return False
