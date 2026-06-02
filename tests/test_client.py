from __future__ import annotations

import urllib.error
import unittest
from unittest.mock import patch

from yandexcli.client import YandexAPIError, YandexClient
from yandexcli.config import parse_config


class FakeResponse:
    def __init__(self, body: str) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body.encode("utf-8")

    def close(self) -> None:
        return None


class ClientConfigTests(unittest.TestCase):
    def test_default_model_uri_uses_alice_latest_from_yacli_config(self) -> None:
        config = parse_config(
            {
                "model": "yandex/alice",
                "provider": {
                    "yandex": {
                        "npm": "yandex",
                        "options": {"folderId": "folder123", "iamToken": "token123"},
                        "models": {"alice": {"modelUri": "gpt://{folderId}/aliceai-llm/latest"}},
                    }
                },
            }
        )
        client = YandexClient.from_config(config)

        self.assertEqual(client.folder_id, "folder123")
        self.assertEqual(client.model_uri, "gpt://folder123/aliceai-llm/latest")
        self.assertEqual(client.auth_scheme, "Bearer")

    def test_payload_keeps_vision_images_in_messages(self) -> None:
        client = YandexClient(folder_id="folder123", token="token123", model_uri="gpt://folder123/gemma-3-27b-it", max_retries=0)
        captured = {}

        def fake_urlopen(request: object, **kwargs: object) -> FakeResponse:
            captured["body"] = request.data.decode("utf-8")  # type: ignore[attr-defined]
            return FakeResponse('{"result":{"alternatives":[]}}')

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.complete(messages=[{"role": "user", "text": "see", "images": [{"base64": "abc"}]}], tools=[])

        self.assertIn('"images": [{"base64": "abc"}]', captured["body"])

    def test_openai_compatible_payload_and_response_are_adapted(self) -> None:
        config = parse_config(
            {
                "model": "vibecode/gpt-5.5",
                "provider": {
                    "vibecode": {
                        "npm": "@ai-sdk/openai-compatible",
                        "name": "vibecode",
                        "options": {"baseURL": "https://example.test/v1", "apiKey": "key"},
                        "models": {"gpt-5.5": {"name": "GPT 5.5"}},
                    }
                },
            }
        )
        client = YandexClient.from_config(config)
        captured = {}

        def fake_urlopen(request: object, **kwargs: object) -> FakeResponse:
            captured["url"] = request.full_url  # type: ignore[attr-defined]
            captured["headers"] = dict(request.header_items())  # type: ignore[attr-defined]
            captured["body"] = request.data.decode("utf-8")  # type: ignore[attr-defined]
            return FakeResponse('{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}')

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.complete(
                messages=[{"role": "user", "text": "see", "images": [{"base64": "abc", "mime_type": "image/png"}]}],
                tools=[],
            )

        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertIn("Bearer key", captured["headers"]["Authorization"])
        self.assertIn('"model": "gpt-5.5"', captured["body"])
        self.assertIn("data:image/png;base64,abc", captured["body"])
        self.assertEqual(result["result"]["alternatives"][0]["message"]["text"], "ok")

    def test_anthropic_payload_and_tool_response_are_adapted(self) -> None:
        config = parse_config(
            {
                "model": "claude/sonnet",
                "provider": {
                    "claude": {
                        "npm": "@ai-sdk/anthropic",
                        "options": {"baseURL": "https://example.test/v1", "apiKey": "key"},
                        "models": {"sonnet": {"name": "Sonnet"}},
                    }
                },
            }
        )
        client = YandexClient.from_config(config)
        captured = {}

        def fake_urlopen(request: object, **kwargs: object) -> FakeResponse:
            captured["url"] = request.full_url  # type: ignore[attr-defined]
            captured["headers"] = dict(request.header_items())  # type: ignore[attr-defined]
            captured["body"] = request.data.decode("utf-8")  # type: ignore[attr-defined]
            return FakeResponse('{"content":[{"type":"tool_use","name":"read_file","input":{"path":"README.md"}}],"stop_reason":"tool_use"}')

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.complete(messages=[{"role": "system", "text": "sys"}, {"role": "user", "text": "read"}], tools=[])

        self.assertEqual(captured["url"], "https://example.test/v1/messages")
        self.assertEqual(captured["headers"]["X-api-key"], "key")
        self.assertIn('"system": "sys"', captured["body"])
        tool_calls = result["result"]["alternatives"][0]["message"]["toolCallList"]["toolCalls"]
        self.assertEqual(tool_calls[0]["functionCall"]["name"], "read_file")
        self.assertEqual(tool_calls[0]["functionCall"]["arguments"], {"path": "README.md"})

    def test_retries_transient_url_errors(self) -> None:
        client = YandexClient(folder_id="folder123", token="token123", model_uri="gpt://folder/model/latest", max_retries=1, retry_delay=0)
        calls = [
            urllib.error.URLError("temporary"),
            FakeResponse('{"result":{"alternatives":[]}}'),
        ]

        def fake_urlopen(*args: object, **kwargs: object) -> object:
            item = calls.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.complete(messages=[], tools=[])

        self.assertEqual(result, {"result": {"alternatives": []}})
        self.assertEqual(calls, [])

    def test_does_not_retry_non_transient_http_errors(self) -> None:
        client = YandexClient(folder_id="folder123", token="token123", model_uri="gpt://folder/model/latest", max_retries=2, retry_delay=0)
        error = urllib.error.HTTPError("https://example.test", 400, "bad request", {}, FakeResponse("bad"))

        with patch("urllib.request.urlopen", side_effect=error) as urlopen:
            with self.assertRaises(YandexAPIError):
                client.complete(messages=[], tools=[])

        self.assertEqual(urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
