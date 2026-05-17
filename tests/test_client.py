from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from yandexcli.client import YandexClient


class ClientConfigTests(unittest.TestCase):
    def test_default_model_uri_uses_alice_latest_and_cloud_folder_env(self) -> None:
        env = {
            "YANDEX_CLOUD_FOLDER": "folder123",
            "YANDEX_IAM_TOKEN": "token123",
        }
        with patch.dict(os.environ, env, clear=True):
            client = YandexClient.from_env()

        self.assertEqual(client.folder_id, "folder123")
        self.assertEqual(client.model_uri, "gpt://folder123/aliceai-llm/latest")
        self.assertEqual(client.auth_scheme, "Bearer")


if __name__ == "__main__":
    unittest.main()
