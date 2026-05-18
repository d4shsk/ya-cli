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


def find_assistant_tool_message(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in messages:
        if message.get("role") == "assistant" and "toolCallList" in message:
            return message
    raise AssertionError("No assistant toolCallList message found")


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
            assistant_tool_message = find_assistant_tool_message(client.requests[1]["messages"])
            self.assertIn("toolCallList", assistant_tool_message)
            tool_name = assistant_tool_message["toolCallList"]["toolCalls"][0]["functionCall"]["name"]
            self.assertEqual(tool_name, "write_file")

    def test_bracket_text_tool_calls_are_recovered_and_not_printed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            client = FakeClient(
                [
                    response(
                        {
                            "role": "assistant",
                            "text": (
                                "Создам файлы.\n\n"
                                "[write_file]\n"
                                '{"path":"landing-doors/index.html","content":"\\u003ch1\\u003eДвери\\u003c/h1\\u003e"}\n\n'
                                "[write_file]\n"
                                '{"path":"landing-doors/css/style.css","content":"body { color: #333; }"}'
                            ),
                        }
                    ),
                    response({"role": "assistant", "text": "Файлы созданы."}),
                ]
            )
            policy = SafetyPolicy(Path(temp_dir), assume_yes=True)
            agent = Agent(client=client, tool_runner=ToolRunner(policy), verbose=False)

            self.assertEqual(agent.run("сделай лендинг"), "Файлы созданы.")
            self.assertEqual((Path(temp_dir) / "landing-doors/index.html").read_text(encoding="utf-8"), "<h1>Двери</h1>")
            self.assertEqual((Path(temp_dir) / "landing-doors/css/style.css").read_text(encoding="utf-8"), "body { color: #333; }")
            assistant_tool_message = find_assistant_tool_message(client.requests[1]["messages"])
            tool_calls = assistant_tool_message["toolCallList"]["toolCalls"]
            self.assertEqual([call["functionCall"]["name"] for call in tool_calls], ["write_file", "write_file"])

    def test_escaped_bracket_text_tool_call_is_recovered(self) -> None:
        with TemporaryDirectory() as temp_dir:
            client = FakeClient(
                [
                    response(
                        {
                            "role": "assistant",
                            "text": '[write_file]\n{\\"path\\":\\"index.html\\",\\"content\\":\\"\\\\u003ch1\\\\u003eHi\\\\u003c/h1\\\\u003e\\"}',
                        }
                    ),
                    response({"role": "assistant", "text": "Готово."}),
                ]
            )
            policy = SafetyPolicy(Path(temp_dir), assume_yes=True)
            agent = Agent(client=client, tool_runner=ToolRunner(policy), verbose=False)

            self.assertEqual(agent.run("create page"), "Готово.")
            self.assertEqual((Path(temp_dir) / "index.html").read_text(encoding="utf-8"), "<h1>Hi</h1>")

    def test_unparseable_pseudo_tool_call_is_not_returned_to_user(self) -> None:
        with TemporaryDirectory() as temp_dir:
            client = FakeClient(
                [
                    response({"role": "assistant", "text": "[write_file]\n{broken json"}),
                    response({"role": "assistant", "text": "Использую инструменты правильно."}),
                ]
            )
            policy = SafetyPolicy(Path(temp_dir), assume_yes=True)
            agent = Agent(client=client, tool_runner=ToolRunner(policy), verbose=False)

            self.assertEqual(agent.run("create page"), "Использую инструменты правильно.")
            retry_message = client.requests[1]["messages"][-1]["text"]
            self.assertIn("native toolCallList", retry_message)

    def test_path_escape_is_blocked(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runner = ToolRunner(SafetyPolicy(Path(temp_dir), assume_yes=True))
            with self.assertRaises(SafetyError):
                runner.run("write_file", {"path": "../outside.txt", "content": "bad"})

    def test_remember_keeps_previous_assistant_answer(self) -> None:
        with TemporaryDirectory() as temp_dir:
            client = FakeClient(
                [
                    response({"role": "assistant", "text": "Сначала сделаем index.html. Продолжить?"}),
                    response({"role": "assistant", "text": "Продолжаю."}),
                ]
            )
            policy = SafetyPolicy(Path(temp_dir), assume_yes=True)
            agent = Agent(client=client, tool_runner=ToolRunner(policy), verbose=False)

            self.assertIn("Продолжить", agent.run("сделай лендинг", remember=True))
            self.assertEqual(agent.run("да", remember=True), "Продолжаю.")

            second_messages = client.requests[1]["messages"]
            self.assertIn({"role": "assistant", "text": "Сначала сделаем index.html. Продолжить?"}, second_messages)
            self.assertEqual(second_messages[-1], {"role": "user", "text": "да"})

    def test_workspace_snapshot_is_sent_before_first_prompt(self) -> None:
        with TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "existing.txt").write_text("already here", encoding="utf-8")
            client = FakeClient([response({"role": "assistant", "text": "ok"})])
            policy = SafetyPolicy(Path(temp_dir), assume_yes=True)
            agent = Agent(client=client, tool_runner=ToolRunner(policy), verbose=False)

            self.assertEqual(agent.run("что есть в папке?"), "ok")
            messages = client.requests[0]["messages"]
            self.assertTrue(messages[1]["text"].startswith("Снимок рабочей директории"))
            self.assertIn("existing.txt", messages[1]["text"])

    def test_frontend_write_triggers_qa_prompt(self) -> None:
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
                                            "arguments": {"path": "index.html", "content": "<img src='missing.png'>"},
                                        }
                                    }
                                ]
                            },
                        },
                        "ALTERNATIVE_STATUS_TOOL_CALLS",
                    ),
                    response({"role": "assistant", "text": "Проверил."}),
                ]
            )
            policy = SafetyPolicy(Path(temp_dir), assume_yes=True)
            agent = Agent(client=client, tool_runner=ToolRunner(policy), verbose=False)

            self.assertEqual(agent.run("создай страницу"), "Проверил.")
            qa_message = client.requests[1]["messages"][-1]
            self.assertEqual(qa_message["role"], "user")
            self.assertIn("Проверь только что записанные HTML/CSS", qa_message["text"])


if __name__ == "__main__":
    unittest.main()
