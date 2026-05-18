from __future__ import annotations

import argparse
import json
import os
import readline
import sys
from dataclasses import replace
from pathlib import Path

from .agent import Agent
from .client import YandexAPIError, YandexClient
from .input import PasteAwarePrompt, disable_bracketed_paste, enable_bracketed_paste, readline_history
from .models import model_menu, resolve_model_uri
from .safety import SafetyPolicy
from .tools import ToolRunner
from .ui import ChatStatus, clear_screen, paint, prompt as ui_prompt, render_assistant, render_header, render_notice, render_shortcuts, render_thinking, supports_color


def main(argv: list[str] | None = None) -> int:
    load_dotenv(project_root() / ".env")
    load_dotenv(Path.cwd() / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).expanduser().resolve()
    policy = SafetyPolicy(
        workspace=workspace,
        assume_yes=args.yes,
        dry_run=args.dry_run,
        allow_shell=args.allow_shell,
    )
    color = supports_color() and not args.plain

    try:
        client = YandexClient.from_env(model_uri=args.model_uri)
        agent = Agent(
            client=client,
            tool_runner=ToolRunner(policy),
            max_iterations=args.max_iterations,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            verbose=args.debug_agent,
        )

        if not args.prompt or (len(args.prompt) == 1 and args.prompt[0] == "chat"):
            return run_chat(agent, color=color)

        prompt = " ".join(args.prompt).strip()
        if not prompt:
            parser.error("prompt is required unless using `chat`.")
        print(agent.run(prompt))
        return 0
    except (YandexAPIError, RuntimeError, KeyboardInterrupt) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yandexgpt", description="Terminal coding agent for YandexGPT/Alice AI.")
    parser.add_argument("prompt", nargs="*", help="Prompt to send. Omit it to open interactive mode.")
    parser.add_argument("--workspace", default=".", help="Workspace root. Tools cannot access paths outside it.")
    parser.add_argument("--model-uri", default=None, help="Yandex model URI, e.g. gpt://<folder>/aliceai-llm.")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--max-iterations", type=int, default=20)
    parser.add_argument("--yes", action="store_true", help="Approve file writes and shell commands.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write files; return intended actions.")
    parser.add_argument("--allow-shell", action="store_true", help="Enable run_shell tool.")
    parser.add_argument("--debug-agent", action="store_true", help="Show low-level agent progress logs.")
    parser.add_argument("--plain", action="store_true", help="Disable ANSI styling.")
    return parser


def run_chat(agent: Agent, *, color: bool = True) -> int:
    history_path = history_file()
    history_enabled = load_history(history_path)
    prompt_reader = PasteAwarePrompt(ui_prompt(color=color), history_enabled=history_enabled, history=readline_history())

    enable_bracketed_paste()
    try:
        clear_screen(color=color)
        render_header(chat_status(agent, history_path, history_enabled), color=color)
        if not history_enabled:
            render_notice(f"История отключена: нет доступа к {history_path}", color=color)
        while True:
            try:
                prompt = prompt_reader.read()
            except (EOFError, KeyboardInterrupt):
                print()
                if history_enabled:
                    save_history(history_path)
                return 0
            if not prompt:
                continue
            if prompt == "?":
                render_shortcuts(color=color)
                if history_enabled:
                    save_history(history_path)
                continue
            if prompt.startswith("/"):
                if handle_slash_command(prompt, agent, history_path=history_path, history_enabled=history_enabled, color=color):
                    if history_enabled:
                        save_history(history_path)
                    return 0
                if history_enabled:
                    save_history(history_path)
                continue
            if prompt in {":q", ":quit", "exit"}:
                if history_enabled:
                    save_history(history_path)
                return 0
            render_thinking(color=color)
            render_assistant(agent.run(prompt, remember=True), color=color)
            if history_enabled:
                save_history(history_path)
    finally:
        disable_bracketed_paste()


def handle_slash_command(command: str, agent: Agent, *, history_path: Path, history_enabled: bool, color: bool = True) -> bool:
    parts = command.split(maxsplit=1)
    name = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if name in {"/q", "/quit", "/exit"}:
        return True
    if name in {"/?", "?"}:
        render_shortcuts(color=color)
        return False
    if name == "/help":
        render_shortcuts(color=color)
        return False
    if name == "/env":
        print_env_status(agent)
        return False
    if name == "/clear":
        clear_screen(color=color)
        render_header(chat_status(agent, history_path, history_enabled), color=color)
        return False
    if name == "/history":
        status = "включена" if history_enabled else "отключена"
        print(f"История: {status} ({history_path})")
        return False
    if name == "/forget":
        agent.messages = None
        render_notice("Контекст диалога очищен.", color=color)
        return False
    if name == "/model":
        if not arg:
            print(paint("Текущая модель: ", enabled=color) + agent.client.model_uri)
            print(model_menu(agent.client.folder_id))
            choice = input("модель> ").strip()
        else:
            choice = arg

        if not choice:
            return False
        model_uri = resolve_model_uri(choice, agent.client.folder_id)
        if model_uri is None:
            print(f"Неизвестная модель: {choice}")
            return False
        agent.client = replace(agent.client, model_uri=model_uri)
        clear_screen(color=color)
        render_header(chat_status(agent, history_path, history_enabled), color=color)
        render_notice(f"Модель выбрана: {agent.client.model_uri}", color=color)
        return False

    print(f"Неизвестная команда: {name}. Введите /help.")
    return False


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def print_env_status(agent: Agent) -> None:
    values = {
        "YANDEX_CLOUD_FOLDER": os.getenv("YANDEX_CLOUD_FOLDER") or os.getenv("YANDEX_FOLDER_ID"),
        "YANDEX_IAM_TOKEN": os.getenv("YANDEX_IAM_TOKEN"),
        "YANDEX_API_KEY": os.getenv("YANDEX_API_KEY"),
        "YANDEX_MODEL_URI": os.getenv("YANDEX_MODEL_URI"),
    }
    print("Переменные окружения:")
    print(f"  YANDEX_CLOUD_FOLDER: {_masked_status(values['YANDEX_CLOUD_FOLDER'])}")
    print(f"  YANDEX_IAM_TOKEN: {_masked_status(values['YANDEX_IAM_TOKEN'])}")
    print(f"  YANDEX_API_KEY: {_masked_status(values['YANDEX_API_KEY'])}")
    print(f"  YANDEX_MODEL_URI: {_masked_status(values['YANDEX_MODEL_URI'])}")
    print(f"  активная модель: {agent.client.model_uri}")


def _masked_status(value: str | None) -> str:
    if not value:
        return "не задано"
    return f"задано ({len(value)} символов)"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def history_file() -> Path:
    return Path(os.getenv("YANDEXGPT_HISTORY", "~/.yandexgpt/history")).expanduser()


def load_history(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch(mode=0o600)
            return True
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            item = decode_history_line(line)
            if item:
                readline.add_history(item)
        return True
    except OSError:
        return False


def save_history(path: Path) -> None:
    try:
        readline.set_history_length(1000)
        length = readline.get_current_history_length()
        start = max(1, length - 999)
        items = [readline.get_history_item(index) for index in range(start, length + 1)]
        text = "\n".join(encode_history_item(item) for item in items if item) + "\n"
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
    except OSError:
        pass


def encode_history_item(item: str) -> str:
    return json.dumps(item, ensure_ascii=False)


def decode_history_line(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped == "_HiStOrY_V2_":
        return ""
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    return decoded if isinstance(decoded, str) else ""


def chat_status(agent: Agent, history_path: Path, history_enabled: bool) -> ChatStatus:
    policy = agent.tool_runner.policy
    return ChatStatus(
        workspace=policy.workspace,
        model_uri=agent.client.model_uri,
        history_path=history_path,
        history_enabled=history_enabled,
        allow_shell=policy.allow_shell,
        dry_run=policy.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
