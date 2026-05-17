from __future__ import annotations

import argparse
import os
import readline
import sys
from dataclasses import replace
from pathlib import Path

from .agent import Agent
from .client import YandexAPIError, YandexClient
from .models import model_menu, resolve_model_uri
from .safety import SafetyPolicy
from .tools import ToolRunner
from .ui import ChatStatus, paint, prompt as ui_prompt, render_assistant, render_header, render_notice, render_shortcuts, supports_color


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

    render_header(chat_status(agent, history_path, history_enabled), color=color)
    if not history_enabled:
        render_notice(f"History disabled: cannot access {history_path}", color=color)
    while True:
        try:
            prompt = input(ui_prompt(color=color)).strip()
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
        render_assistant(agent.run(prompt), color=color)
        if history_enabled:
            save_history(history_path)


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
    if name == "/clear":
        if color:
            print("\033[2J\033[H", end="")
        else:
            print()
        render_header(chat_status(agent, history_path, history_enabled), color=color)
        return False
    if name == "/history":
        status = "enabled" if history_enabled else "disabled"
        print(f"History: {status} ({history_path})")
        return False
    if name == "/model":
        if not arg:
            print(paint("Current model: ", enabled=color) + agent.client.model_uri)
            print(model_menu(agent.client.folder_id))
            choice = input("model> ").strip()
        else:
            choice = arg

        if not choice:
            return False
        model_uri = resolve_model_uri(choice, agent.client.folder_id)
        if model_uri is None:
            print(f"Unknown model selection: {choice}")
            return False
        agent.client = replace(agent.client, model_uri=model_uri)
        render_notice(f"Model set to: {agent.client.model_uri}", color=color)
        return False

    print(f"Unknown command: {name}. Type /help.")
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
            item = line.strip()
            if item and item != "_HiStOrY_V2_":
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
        text = "\n".join(item for item in items if item) + "\n"
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
    except OSError:
        pass


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
