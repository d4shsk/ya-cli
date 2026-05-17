from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from yandexcli.agent import Agent
from yandexcli.safety import SafetyError, SafetyPolicy
from yandexcli.tools import ToolRunner


class FakeClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        if not self.responses:
            raise AssertionError("No fake responses left")
        return self.responses.pop(0)


def response(message: dict[str, Any], status: str = "ALTERNATIVE_STATUS_FINAL") -> dict[str, Any]:
    return {"result": {"alternatives": [{"message": message, "status": status}]}}


class AgentToolTests(unittest.TestCase):
    def test_native_tool_call_writes_file_and_returns_final_text(self) -> None:
        with TemporaryDirectory() as temp_dir:
            client = FakeClient(
                [
                    response(
                        {
                            "role": "assistant",
                            "toolCallList": {
                                "toolCalls": [
                                    {
                                        "functionCall": {
                                            "name": "write_file",
                                            "arguments": {"path": "hello.txt", "content": "hello"},
                                        }
                                    }
                                ]
                            },
                        },
                        "ALTERNATIVE_STATUS_TOOL_CALLS",
                    ),
                    response({"role": "assistant", "text": "done"}),
                ]
            )
            policy = SafetyPolicy(Path(temp_dir), assume_yes=True)
            agent = Agent(client=client, tool_runner=ToolRunner(policy), verbose=False)

            self.assertEqual(agent.run("write hello"), "done")
            self.assertEqual((Path(temp_dir) / "hello.txt").read_text(encoding="utf-8"), "hello")
            tool_result_message = client.requests[1]["messages"][-1]
            self.assertIn("toolResultList", tool_result_message)

    def test_legacy_text_tool_call_is_recovered_and_writes_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            client = FakeClient(
                [
                    response({"role": "assistant", "text": '[TOOL_CALL_START]write {"path":"index.html","content":"\\u003ch1\\u003eHi\\u003c/h1\\u003e"}'}),
                    response({"role": "assistant", "text": "done"}),
                ]
            )
            policy = SafetyPolicy(Path(temp_dir), assume_yes=True)
            agent = Agent(client=client, tool_runner=ToolRunner(policy), verbose=False)

            self.assertEqual(agent.run("create page"), "done")
            self.assertEqual((Path(temp_dir) / "index.html").read_text(encoding="utf-8"), "<h1>Hi</h1>")
            assistant_tool_message = client.requests[1]["messages"][-2]
            self.assertIn("toolCallList", assistant_tool_message)
            tool_name = assistant_tool_message["toolCallList"]["toolCalls"][0]["functionCall"]["name"]
            self.assertEqual(tool_name, "write_file")

    def test_path_escape_is_blocked(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runner = ToolRunner(SafetyPolicy(Path(temp_dir), assume_yes=True))
            with self.assertRaises(SafetyError):
                runner.run("write_file", {"path": "../outside.txt", "content": "bad"})


if __name__ == "__main__":
    unittest.main()
