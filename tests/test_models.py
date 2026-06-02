from __future__ import annotations

import unittest

from yandexcli.models import default_model_uri, resolve_model_uri


class ModelTests(unittest.TestCase):
    def test_default_model_is_alice_latest(self) -> None:
        self.assertEqual(default_model_uri("folder123"), "gpt://folder123/aliceai-llm/latest")

    def test_resolve_model_by_key_number_and_uri(self) -> None:
        self.assertEqual(resolve_model_uri("1", "f"), "gpt://f/yandexgpt-5-lite/latest")
        self.assertEqual(resolve_model_uri("alice", "f"), "gpt://f/aliceai-llm/latest")
        self.assertEqual(resolve_model_uri("2", "f"), "gpt://f/aliceai-llm/latest")
        self.assertEqual(resolve_model_uri("yandexgpt-5-pro", "f"), "gpt://f/yandexgpt-5-pro/latest")
        self.assertEqual(resolve_model_uri("yandexgpt-5.1", "f"), "gpt://f/yandexgpt-5.1/latest")
        self.assertEqual(resolve_model_uri("gemma-3-27b-it", "f"), "gpt://f/gemma-3-27b-it")
        self.assertEqual(resolve_model_uri("gpt://f/custom/latest", "f"), "gpt://f/custom/latest")
        self.assertIsNone(resolve_model_uri("unknown", "f"))


if __name__ == "__main__":
    unittest.main()
