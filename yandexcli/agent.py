from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from .legacy import parse_legacy_tool_call
from .safety import SafetyError
from .tools import TOOL_SCHEMAS, ToolRunner, canonical_tool_name


SYSTEM_PROMPT = """You are YandexCLI, a terminal coding assistant.

Use the provided tools whenever you need to inspect, create, or edit files.
Do not print file contents in chat when a file should be created or modified.
Call write_file with path and content instead.
Prefer small, focused changes. Never attempt to access files outside the workspace.
When unsure about security implications, mention the concern and update vulnerabilities.md.
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

    def run(self, prompt: str, history: list[dict[str, Any]] | None = None) -> str:
        messages = list(history or [{"role": "system", "text": SYSTEM_PROMPT}])
        messages.append({"role": "user", "text": prompt})

        for iteration in range(1, self.max_iterations + 1):
            response = self.client.complete(
                messages=messages,
                tools=TOOL_SCHEMAS,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            message, status = _extract_message(response)

            native_calls = message.get("toolCallList", {}).get("toolCalls", [])
            if native_calls:
                if self.verbose:
                    print(f"[agent] iteration {iteration}: executing {len(native_calls)} native tool call(s)")
                messages.append({"role": "assistant", "toolCallList": {"toolCalls": native_calls}})
                messages.append(self._execute_tool_calls(native_calls))
                continue

            text = message.get("text", "")
            legacy_call = parse_legacy_tool_call(text) if isinstance(text, str) else None
            if legacy_call:
                if self.verbose:
                    print(f"[agent] iteration {iteration}: recovered legacy text tool call `{legacy_call.name}`")
                tool_call = {
                    "functionCall": {
                        "name": canonical_tool_name(legacy_call.name),
                        "arguments": legacy_call.arguments,
                    }
                }
                messages.append({"role": "assistant", "toolCallList": {"toolCalls": [tool_call]}})
                messages.append(self._execute_tool_calls([tool_call]))
                continue

            if status and self.verbose:
                print(f"[agent] final status: {status}")
            return text if isinstance(text, str) else json.dumps(message, ensure_ascii=False)

        raise RuntimeError(f"Reached max_iterations={self.max_iterations} without a final answer.")

    def _execute_tool_calls(self, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for call in tool_calls:
            function_call = call.get("functionCall", {})
            name = function_call.get("name")
            arguments = function_call.get("arguments", {})
            if not isinstance(name, str):
                name = ""
            if not isinstance(arguments, dict):
                arguments = {}

            try:
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
