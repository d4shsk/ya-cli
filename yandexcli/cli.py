from __future__ import annotations

import argparse
import json
import os
import readline
import sys
from pathlib import Path

from .agent import EDIT_MODE_PROMPT, PLAN_MODE_PROMPT, Agent, AgentMode
from .client import YandexAPIError, YandexClient
from .config import ConfigError, YacliConfig, load_config
from .input import PasteAwarePrompt, disable_bracketed_paste, enable_bracketed_paste, readline_history
from .safety import SafetyPolicy
from .sessions import ChatSession, SessionError, create_session, delete_all_sessions, is_empty_session, load_session, resume_command, save_session, sessions_dir
from .tools import ToolRunner
from .ui import ChatStatus, PromptFrame, build_prompt_frame, clear_screen, mode_label, model_picker_prompt, paint, prompt as ui_prompt, render_assistant, render_header, render_model_picker, render_notice, render_shortcuts, render_thinking, render_user, render_welcome, supports_color


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.clear_sessions:
        delete_all_sessions(sessions_dir())
        return 0

    try:
        config = load_config(Path(args.config) if args.config else None, cwd=Path.cwd(), project_root=project_root())
        session: ChatSession | None = None
        if args.session is not None:
            session = load_session(sessions_dir(), args.session)

        workspace_arg = session.workspace if session is not None and args.workspace == "." and session.workspace else args.workspace
        workspace = Path(workspace_arg).expanduser().resolve()
        permission_bash = str(config.permission.get("bash") or "").lower()
        policy = SafetyPolicy(
            workspace=workspace,
            assume_yes=args.yes,
            assume_yes_shell=args.yes_shell,
            dry_run=args.dry_run,
            allow_shell=args.allow_shell or permission_bash == "allow",
        )
        color = supports_color() and not args.plain
        selected_model = args.model or args.model_uri
        if session is not None and not selected_model and session.model_uri:
            selected_model = session.model_uri
        client = YandexClient.from_config(config, model=selected_model)
        agent = Agent(
            client=client,
            tool_runner=ToolRunner(policy),
            max_iterations=args.max_iterations,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            verbose=args.debug_agent,
        )

        if session is not None:
            if session.messages:
                agent.messages = session.messages
            return run_chat(agent, color=color, session=session, config=config)

        if not args.prompt or (len(args.prompt) == 1 and args.prompt[0] == "chat"):
            return run_chat(agent, color=color, config=config)

        prompt = " ".join(args.prompt).strip()
        if not prompt:
            parser.error("prompt is required unless using `chat`.")
        print(agent.run(prompt))
        return 0
    except (YandexAPIError, RuntimeError, SessionError, ConfigError, KeyboardInterrupt) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yandexgpt", description="Terminal coding agent for YandexGPT/Alice AI.")
    parser.add_argument("prompt", nargs="*", help="Prompt to send. Omit it to open interactive mode.")
    parser.add_argument("--config", default=None, help="Path to yacli.jsonc.")
    parser.add_argument("--workspace", default=".", help="Workspace root. Tools cannot access paths outside it.")
    parser.add_argument("--model", default=None, help="Model ref from yacli.jsonc, e.g. yandex/alice or vibecode/gpt-5.5.")
    parser.add_argument("--model-uri", default=None, help="Compatibility alias for a raw Yandex gpt:// model URI.")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--max-iterations", type=int, default=20)
    parser.add_argument("--yes", action="store_true", help="Approve file writes.")
    parser.add_argument("--yes-shell", action="store_true", help="Approve shell commands when --allow-shell is enabled.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write files; return intended actions.")
    parser.add_argument("--allow-shell", action="store_true", help="Enable run_shell tool. yacli.jsonc permission.bash=allow also enables it.")
    parser.add_argument("--debug-agent", action="store_true", help="Show low-level agent progress logs.")
    parser.add_argument("--plain", action="store_true", help="Disable ANSI styling.")
    parser.add_argument("--session", type=int, default=None, help="Resume an interactive chat session by numeric id.")
    parser.add_argument("--clear-sessions", action="store_true", help="Delete all saved chat sessions.")
    return parser


def run_chat(agent: Agent, *, color: bool = True, session: ChatSession | None = None, config: YacliConfig | None = None) -> int:
    history_path = history_file()
    history_enabled = load_history(history_path)
    session = session or create_session(sessions_dir(), workspace=agent.tool_runner.policy.workspace, model_uri=agent.client.model_uri)
    mode: AgentMode = "plan" if session.mode == "plan" else "edit"
    current_frame: PromptFrame | None = None

    def current_prompt() -> str:
        nonlocal current_frame
        current_frame = build_prompt_frame(mode, color=color)
        return ui_prompt(mode=mode, color=color)

    def toggle_mode() -> str:
        nonlocal mode
        mode = "plan" if mode == "edit" else "edit"
        result = current_prompt()
        prompt_reader.frame = current_frame
        return result

    prompt_reader = PasteAwarePrompt(
        current_prompt(),
        history_enabled=history_enabled,
        history=readline_history(),
        on_tab=toggle_mode,
        file_completion_root=agent.tool_runner.policy.workspace,
        frame=current_frame,
    )

    def finish() -> int:
        nonlocal session
        if history_enabled:
            save_history(history_path)
        if is_empty_session(agent.messages):
            return 0
        session = save_session(
            session,
            messages=agent.messages,
            mode=mode,
            workspace=agent.tool_runner.policy.workspace,
            model_uri=agent.client.model_uri,
        )
        print(f"Сессия {session.id} сохранена. Продолжить: {resume_command(session.id, workspace=agent.tool_runner.policy.workspace)}")
        return 0

    enable_bracketed_paste()
    try:
        clear_screen(color=color)
        intro_visible = not bool(session.messages)
        if intro_visible:
            render_welcome(chat_status(agent, history_path, history_enabled, mode=mode, session_id=session.id), color=color)
        else:
            render_saved_messages(session.messages, color=color)
        if not history_enabled:
            render_notice(f"История отключена: нет доступа к {history_path}", color=color)
        while True:
            try:
                prompt = prompt_reader.read()
            except (EOFError, KeyboardInterrupt):
                print()
                return finish()
            if not prompt:
                continue
            if prompt == "?":
                render_shortcuts(color=color)
                if history_enabled:
                    save_history(history_path)
                continue
            if prompt.startswith("/"):
                handled, new_mode = handle_slash_command(
                    prompt,
                    agent,
                    history_path=history_path,
                    history_enabled=history_enabled,
                    mode=mode,
                    session_id=session.id,
                    config=config,
                    color=color,
                )
                mode = new_mode
                prompt_reader.prompt_text = current_prompt()
                prompt_reader.frame = current_frame
                if handled:
                    return finish()
                if history_enabled:
                    save_history(history_path)
                continue
            if prompt in {":q", ":quit", "exit"}:
                return finish()
            if intro_visible:
                clear_screen(color=color)
                intro_visible = False
            render_user(prompt, mode=mode, color=color)
            render_thinking(color=color)
            render_assistant(agent.run(prompt, remember=True, mode=mode), color=color)
            if history_enabled:
                save_history(history_path)
    finally:
        disable_bracketed_paste()


def handle_slash_command(
    command: str,
    agent: Agent,
    *,
    history_path: Path,
    history_enabled: bool,
    mode: AgentMode = "edit",
    session_id: int | None = None,
    config: YacliConfig | None = None,
    color: bool = True,
) -> tuple[bool, AgentMode]:
    parts = command.split(maxsplit=1)
    name = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if name in {"/q", "/quit", "/exit"}:
        return True, mode
    if name in {"/?", "?"}:
        render_shortcuts(color=color)
        return False, mode
    if name == "/help":
        render_shortcuts(color=color)
        return False, mode
    if name in {"/env", "/config"}:
        print_config_status(agent, config)
        return False, mode
    if name == "/session":
        if session_id is None:
            print("Сессия: текущая")
        else:
            print(f"Сессия: {session_id}")
            print(f"Продолжить: {resume_command(session_id, workspace=agent.tool_runner.policy.workspace)}")
        return False, mode
    if name in {"/plan", "/edit", "/mode"}:
        new_mode: AgentMode
        if name == "/plan":
            new_mode = "plan"
        elif name == "/edit":
            new_mode = "edit"
        else:
            choice = arg.strip().lower()
            if choice in {"plan", "план"}:
                new_mode = "plan"
            elif choice in {"edit", "редактирование"}:
                new_mode = "edit"
            else:
                new_mode = "plan" if mode == "edit" else "edit"
        render_notice(f"Режим: {mode_label(new_mode)}", color=color)
        return False, new_mode
    if name == "/clear":
        clear_screen(color=color)
        render_header(chat_status(agent, history_path, history_enabled, mode=mode, session_id=session_id), color=color)
        return False, mode
    if name == "/history":
        status = "включена" if history_enabled else "отключена"
        print(f"История: {status} ({history_path})")
        return False, mode
    if name == "/forget":
        agent.messages = None
        render_notice("Контекст диалога очищен.", color=color)
        return False, mode
    if name in {"/clear-sessions", "/delete-sessions"}:
        delete_all_sessions(sessions_dir())
        agent.messages = None
        return False, mode
    if name == "/model":
        if config is None:
            print("Конфиг недоступен: /model требует yacli.jsonc.")
            return False, mode
        if not arg:
            clear_screen(color=color)
            render_model_picker(agent.client.model_uri, config.model_menu(), color=color)
            choice = input(model_picker_prompt(color=color)).strip()
        else:
            choice = arg

        if not choice:
            clear_screen(color=color)
            render_header(chat_status(agent, history_path, history_enabled, mode=mode, session_id=session_id), color=color)
            return False, mode
        try:
            agent.client = YandexClient.from_config(config, model=choice)
        except ConfigError as exc:
            print(str(exc))
            return False, mode
        clear_screen(color=color)
        render_header(chat_status(agent, history_path, history_enabled, mode=mode, session_id=session_id), color=color)
        render_notice(f"Модель выбрана: {agent.client.model_uri}", color=color)
        return False, mode

    print(f"Неизвестная команда: {name}. Введите /help.")
    return False, mode


def print_config_status(agent: Agent, config: YacliConfig | None) -> None:
    print("Конфиг:")
    if config is None:
        print("  yacli.jsonc: недоступен")
    else:
        print(f"  yacli.jsonc: {config.path}")
        print(f"  default model: {config.default_model}")
        print(f"  permission.bash: {config.permission.get('bash', 'ask')}")
        print("  providers:")
        for provider in config.providers.values():
            api_key = provider.options.get("apiKey") or provider.options.get("api_key")
            iam_token = provider.options.get("iamToken") or provider.options.get("iam_token")
            folder_id = provider.options.get("folderId") or provider.options.get("folder_id")
            print(f"    {provider.id}: {provider.name} ({provider.npm})")
            if folder_id:
                print(f"      folderId: {_masked_status(str(folder_id))}")
            if api_key:
                print(f"      apiKey: {_masked_status(str(api_key))}")
            if iam_token:
                print(f"      iamToken: {_masked_status(str(iam_token))}")
            print(f"      models: {', '.join(provider.models)}")
    print(f"  активная модель: {agent.client.model_uri}")


def render_saved_messages(messages: list[dict[str, object]], *, color: bool = True) -> None:
    mode: AgentMode = "edit"
    printed = False
    for message in messages:
        role = message.get("role")
        text = message.get("text")
        if role == "user" and isinstance(text, str):
            prompt_mode = _saved_mode_prompt(text)
            if prompt_mode:
                mode = prompt_mode
                continue
            if _is_internal_saved_user_message(text):
                continue
            render_user(_saved_user_text(text), mode=mode, color=color)
            printed = True
        elif role == "assistant" and isinstance(text, str) and text.strip():
            render_assistant(text, color=color)
            printed = True
    if printed:
        print()


def _saved_mode_prompt(text: str) -> AgentMode | None:
    if text == PLAN_MODE_PROMPT:
        return "plan"
    if text == EDIT_MODE_PROMPT:
        return "edit"
    return None


def _is_internal_saved_user_message(text: str) -> bool:
    return text.startswith("Снимок рабочей директории") or text == ""


def _saved_user_text(text: str) -> str:
    markers = (
        "\n\nAttached @file context:",
        "\n\nAttached @image files sent to the model as base64:",
        "\n\nUnresolved @ references:",
    )
    end = len(text)
    for marker in markers:
        index = text.find(marker)
        if index != -1:
            end = min(end, index)
    return text[:end].strip()


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


def chat_status(agent: Agent, history_path: Path, history_enabled: bool, *, mode: AgentMode = "edit", session_id: int | None = None) -> ChatStatus:
    policy = agent.tool_runner.policy
    return ChatStatus(
        workspace=policy.workspace,
        model_uri=agent.client.model_uri,
        history_path=history_path,
        history_enabled=history_enabled,
        allow_shell=policy.allow_shell,
        dry_run=policy.dry_run,
        mode=mode,
        session_id=session_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
