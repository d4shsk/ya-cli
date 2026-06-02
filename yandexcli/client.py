from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import ConfigError, ResolvedModel, YacliConfig


YANDEX_COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
YANDEX_BASE_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1"
ANTHROPIC_VERSION = "2023-06-01"


class YandexAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class YandexClient:
    folder_id: str
    token: str
    model_uri: str
    api_url: str = YANDEX_COMPLETION_URL
    timeout: int = 300
    auth_scheme: str = "Bearer"
    max_retries: int = 2
    retry_delay: float = 0.5
    provider_id: str = "yandex"
    provider_name: str = "Yandex"
    provider_npm: str = "yandex"
    model_id: str = ""
    base_url: str = YANDEX_BASE_URL

    @classmethod
    def from_config(cls, config: YacliConfig, model: str | None = None) -> "YandexClient":
        resolved = config.resolve_model(model)
        if resolved.provider.npm == "@ai-sdk/openai-compatible":
            return cls._from_openai_compatible(resolved)
        if resolved.provider.npm == "@ai-sdk/anthropic":
            return cls._from_anthropic(resolved)
        return cls._from_yandex(resolved)

    @classmethod
    def _from_yandex(cls, resolved: ResolvedModel) -> "YandexClient":
        options = resolved.provider.options
        folder_id = _string_option(options, "folderId", "folder_id", "folderID")
        iam_token = _string_option(options, "iamToken", "iam_token")
        api_key = _string_option(options, "apiKey", "api_key")
        if not folder_id:
            raise ConfigError("Yandex provider requires options.folderId in yacli.jsonc.")
        if not iam_token and not api_key:
            raise ConfigError("Yandex provider requires options.iamToken or options.apiKey in yacli.jsonc.")
        model_uri = str(resolved.model.get("modelUri") or resolved.model_id).format(folderId=folder_id, folder_id=folder_id)
        if not model_uri.startswith("gpt://"):
            model_uri = f"gpt://{folder_id}/{model_uri}"
        base_url = _string_option(options, "baseURL", "baseUrl", default=YANDEX_BASE_URL)
        api_url = base_url if base_url.endswith("/completion") else _join_url(base_url, "completion")
        return cls(
            folder_id=folder_id,
            token=iam_token or api_key,
            model_uri=model_uri,
            api_url=api_url,
            auth_scheme="Bearer" if iam_token else "Api-Key",
            provider_id=resolved.provider.id,
            provider_name=resolved.provider.name,
            provider_npm=resolved.provider.npm,
            model_id=resolved.model_id,
            base_url=base_url,
        )

    @classmethod
    def _from_openai_compatible(cls, resolved: ResolvedModel) -> "YandexClient":
        options = resolved.provider.options
        api_key = _string_option(options, "apiKey", "api_key")
        base_url = _string_option(options, "baseURL", "baseUrl")
        if not api_key:
            raise ConfigError(f"Provider {resolved.provider.id!r} requires options.apiKey in yacli.jsonc.")
        if not base_url:
            raise ConfigError(f"Provider {resolved.provider.id!r} requires options.baseURL in yacli.jsonc.")
        return cls(
            folder_id="",
            token=api_key,
            model_uri=resolved.ref,
            api_url=_join_url(base_url, "chat/completions"),
            auth_scheme="Bearer",
            provider_id=resolved.provider.id,
            provider_name=resolved.provider.name,
            provider_npm=resolved.provider.npm,
            model_id=resolved.model_id,
            base_url=base_url,
        )

    @classmethod
    def _from_anthropic(cls, resolved: ResolvedModel) -> "YandexClient":
        options = resolved.provider.options
        api_key = _string_option(options, "apiKey", "api_key")
        base_url = _string_option(options, "baseURL", "baseUrl", default="https://api.anthropic.com")
        if not api_key:
            raise ConfigError(f"Provider {resolved.provider.id!r} requires options.apiKey in yacli.jsonc.")
        return cls(
            folder_id="",
            token=api_key,
            model_uri=resolved.ref,
            api_url=_join_url(base_url, "messages"),
            auth_scheme="x-api-key",
            provider_id=resolved.provider.id,
            provider_name=resolved.provider.name,
            provider_npm=resolved.provider.npm,
            model_id=resolved.model_id,
            base_url=base_url,
        )

    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> dict[str, Any]:
        if self.provider_npm == "@ai-sdk/openai-compatible":
            payload = _openai_payload(self.model_id, messages, tools, temperature=temperature, max_tokens=max_tokens)
            body = self._post_json(
                self.api_url,
                payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.token}",
                },
                error_label=self.provider_name,
            )
            return _openai_response_to_yandex_shape(body)
        if self.provider_npm == "@ai-sdk/anthropic":
            payload = _anthropic_payload(self.model_id, messages, tools, temperature=temperature, max_tokens=max_tokens)
            body = self._post_json(
                self.api_url,
                payload,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.token,
                    "anthropic-version": ANTHROPIC_VERSION,
                },
                error_label=self.provider_name,
            )
            return _anthropic_response_to_yandex_shape(body)
        return self._complete_yandex(messages=messages, tools=tools, temperature=temperature, max_tokens=max_tokens)

    def _complete_yandex(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": temperature,
                "maxTokens": str(max_tokens),
            },
            "messages": _yandex_messages(messages),
            "tools": tools,
        }
        return self._post_json(
            self.api_url,
            payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"{self.auth_scheme} {self.token}",
                "x-folder-id": self.folder_id,
            },
            error_label="Yandex API",
        )

    def _post_json(self, url: str, payload: dict[str, Any], *, headers: dict[str, str], error_label: str) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST", headers=headers)

        body = ""
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout, context=_ssl_context()) as response:
                    body = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", errors="replace")
                finally:
                    exc.close()
                error = YandexAPIError(f"{error_label} HTTP {exc.code}: {detail}")
                if not _retryable_http_status(exc.code) or attempt >= self.max_retries:
                    raise error from exc
                _sleep_before_retry(self.retry_delay, attempt)
            except urllib.error.URLError as exc:
                error = YandexAPIError(f"{error_label} request failed: {exc}")
                if attempt >= self.max_retries:
                    raise error from exc
                _sleep_before_retry(self.retry_delay, attempt)

        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise YandexAPIError(f"{error_label} returned invalid JSON: {body[:500]}") from exc
        if not isinstance(decoded, dict):
            raise YandexAPIError(f"{error_label} returned non-object JSON: {body[:500]}")
        return decoded


def _yandex_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for message in messages:
        item = dict(message)
        images = item.get("images")
        if isinstance(images, list):
            item["images"] = [{"base64": image.get("base64", "")} for image in images if isinstance(image, dict) and image.get("base64")]
        clean.append(item)
    return clean


def _openai_payload(
    model_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": _openai_messages(messages),
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = [{"type": "function", "function": dict(tool["function"])} for tool in tools if isinstance(tool.get("function"), dict)]
    return payload


def _openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    pending_tool_ids: list[str] = []
    for message in messages:
        tool_calls = _internal_tool_calls(message)
        if tool_calls:
            openai_calls = []
            for index, call in enumerate(tool_calls, 1):
                function_call = call.get("functionCall", {})
                name = str(function_call.get("name") or "")
                arguments = function_call.get("arguments") if isinstance(function_call, dict) else {}
                call_id = f"call_{len(pending_tool_ids) + index}"
                pending_tool_ids.append(call_id)
                openai_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments if isinstance(arguments, dict) else {}, ensure_ascii=False)},
                    }
                )
            converted.append({"role": "assistant", "content": "", "tool_calls": openai_calls})
            continue

        tool_results = _internal_tool_results(message)
        if tool_results:
            for result in tool_results:
                function_result = result.get("functionResult", {})
                call_id = pending_tool_ids.pop(0) if pending_tool_ids else "call_result"
                converted.append({"role": "tool", "tool_call_id": call_id, "content": str(function_result.get("content") or "")})
            continue

        role = _message_role(message)
        text = str(message.get("text") or "")
        images = _message_images(message)
        if images:
            content: list[dict[str, Any]] = []
            if text:
                content.append({"type": "text", "text": text})
            for image in images:
                content.append({"type": "image_url", "image_url": {"url": _data_url(image)}})
            converted.append({"role": role, "content": content})
        else:
            converted.append({"role": role, "content": text})
    return converted


def _anthropic_payload(
    model_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    anthropic_messages, system_text = _anthropic_messages(messages)
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": anthropic_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if system_text:
        payload["system"] = system_text
    if tools:
        payload["tools"] = [
            {
                "name": str(tool["function"].get("name") or ""),
                "description": str(tool["function"].get("description") or ""),
                "input_schema": tool["function"].get("parameters") or {"type": "object"},
            }
            for tool in tools
            if isinstance(tool.get("function"), dict)
        ]
    return payload


def _anthropic_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    converted: list[dict[str, Any]] = []
    system_parts: list[str] = []
    pending_tool_ids: list[str] = []
    for message in messages:
        role = _message_role(message)
        if role == "system":
            text = str(message.get("text") or "")
            if text:
                system_parts.append(text)
            continue

        tool_calls = _internal_tool_calls(message)
        if tool_calls:
            content = []
            for index, call in enumerate(tool_calls, 1):
                function_call = call.get("functionCall", {})
                name = str(function_call.get("name") or "")
                arguments = function_call.get("arguments") if isinstance(function_call, dict) else {}
                call_id = f"toolu_{len(pending_tool_ids) + index}"
                pending_tool_ids.append(call_id)
                content.append({"type": "tool_use", "id": call_id, "name": name, "input": arguments if isinstance(arguments, dict) else {}})
            converted.append({"role": "assistant", "content": content})
            continue

        tool_results = _internal_tool_results(message)
        if tool_results:
            content = []
            for result in tool_results:
                function_result = result.get("functionResult", {})
                call_id = pending_tool_ids.pop(0) if pending_tool_ids else "toolu_result"
                content.append({"type": "tool_result", "tool_use_id": call_id, "content": str(function_result.get("content") or "")})
            converted.append({"role": "user", "content": content})
            continue

        content_blocks: list[dict[str, Any]] = []
        text = str(message.get("text") or "")
        if text:
            content_blocks.append({"type": "text", "text": text})
        for image in _message_images(message):
            content_blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": str(image.get("mime_type") or "image/jpeg"),
                        "data": str(image.get("base64") or ""),
                    },
                }
            )
        converted.append({"role": "assistant" if role == "assistant" else "user", "content": content_blocks or [{"type": "text", "text": ""}]})
    return converted, "\n\n".join(system_parts)


def _openai_response_to_yandex_shape(response: dict[str, Any]) -> dict[str, Any]:
    try:
        choice = response["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise YandexAPIError(f"Unexpected OpenAI-compatible response shape: {json.dumps(response, ensure_ascii=False)[:1000]}") from exc

    tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
    if isinstance(tool_calls, list) and tool_calls:
        converted_calls = []
        for call in tool_calls:
            function = call.get("function", {}) if isinstance(call, dict) else {}
            converted_calls.append(
                {
                    "functionCall": {
                        "name": str(function.get("name") or ""),
                        "arguments": _json_object(function.get("arguments")),
                    }
                }
            )
        converted_message = {"toolCallList": {"toolCalls": converted_calls}}
    else:
        content = message.get("content", "") if isinstance(message, dict) else ""
        converted_message = {"role": "assistant", "text": _content_to_text(content)}
    return {"result": {"alternatives": [{"message": converted_message, "status": choice.get("finish_reason")}]} }


def _anthropic_response_to_yandex_shape(response: dict[str, Any]) -> dict[str, Any]:
    content = response.get("content")
    if not isinstance(content, list):
        raise YandexAPIError(f"Unexpected Anthropic response shape: {json.dumps(response, ensure_ascii=False)[:1000]}")
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text_parts.append(str(block.get("text") or ""))
        elif block.get("type") == "tool_use":
            tool_calls.append(
                {
                    "functionCall": {
                        "name": str(block.get("name") or ""),
                        "arguments": block.get("input") if isinstance(block.get("input"), dict) else {},
                    }
                }
            )
    if tool_calls:
        message = {"toolCallList": {"toolCalls": tool_calls}}
    else:
        message = {"role": "assistant", "text": "\n".join(part for part in text_parts if part)}
    return {"result": {"alternatives": [{"message": message, "status": response.get("stop_reason")}]} }


def _internal_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    container = message.get("toolCallList")
    if not isinstance(container, dict):
        return []
    calls = container.get("toolCalls")
    return calls if isinstance(calls, list) else []


def _internal_tool_results(message: dict[str, Any]) -> list[dict[str, Any]]:
    container = message.get("toolResultList")
    if not isinstance(container, dict):
        return []
    results = container.get("toolResults")
    return results if isinstance(results, list) else []


def _message_role(message: dict[str, Any]) -> str:
    role = str(message.get("role") or "user")
    if role in {"system", "assistant", "user"}:
        return role
    return "user"


def _message_images(message: dict[str, Any]) -> list[dict[str, Any]]:
    images = message.get("images")
    return [image for image in images if isinstance(image, dict) and image.get("base64")] if isinstance(images, list) else []


def _data_url(image: dict[str, Any]) -> str:
    mime_type = str(image.get("mime_type") or "image/jpeg")
    return f"data:{mime_type};base64,{image.get('base64') or ''}"


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "\n".join(parts)
    return "" if content is None else str(content)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _string_option(options: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = options.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _join_url(base_url: str, path: str) -> str:
    normalized_base = base_url.rstrip("/")
    normalized_path = path.lstrip("/")
    if normalized_base.endswith("/v1") and normalized_path.startswith("v1/"):
        normalized_path = normalized_path[3:]
    return f"{normalized_base}/{normalized_path}"


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _retryable_http_status(code: int) -> bool:
    return code in {429, 500, 502, 503, 504}


def _sleep_before_retry(base_delay: float, attempt: int) -> None:
    if base_delay <= 0:
        return
    time.sleep(base_delay * (2**attempt))
