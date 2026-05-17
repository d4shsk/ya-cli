from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .models import default_model_uri


YANDEX_COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


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

    @classmethod
    def from_env(cls, model_uri: str | None = None) -> "YandexClient":
        folder_id = (os.getenv("YANDEX_CLOUD_FOLDER") or os.getenv("YANDEX_FOLDER_ID") or "").strip()
        iam_token = os.getenv("YANDEX_IAM_TOKEN", "").strip()
        api_key = os.getenv("YANDEX_API_KEY", "").strip()

        if not folder_id:
            raise YandexAPIError("YANDEX_CLOUD_FOLDER or YANDEX_FOLDER_ID is required.")
        if not iam_token and not api_key:
            raise YandexAPIError("YANDEX_IAM_TOKEN or YANDEX_API_KEY is required.")

        resolved_model_uri = model_uri or os.getenv("YANDEX_MODEL_URI") or default_model_uri(folder_id)
        token = iam_token or api_key
        auth_scheme = "Bearer" if iam_token else "Api-Key"
        return cls(folder_id=folder_id, token=token, model_uri=resolved_model_uri, auth_scheme=auth_scheme)

    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> dict[str, Any]:
        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": temperature,
                "maxTokens": str(max_tokens),
            },
            "messages": messages,
            "tools": tools,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.api_url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"{self.auth_scheme} {self.token}",
                "x-folder-id": self.folder_id,
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=_ssl_context()) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise YandexAPIError(f"Yandex API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise YandexAPIError(f"Yandex API request failed: {exc}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise YandexAPIError(f"Yandex API returned invalid JSON: {body[:500]}") from exc


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())
