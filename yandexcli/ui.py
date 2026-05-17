from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import __version__


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
RED = "\033[31m"
YELLOW = "\033[33m"
GRAY = "\033[90m"
BG = "\033[48;5;236m"


@dataclass(frozen=True)
class ChatStatus:
    workspace: Path
    model_uri: str
    history_path: Path
    history_enabled: bool
    allow_shell: bool
    dry_run: bool


def supports_color() -> bool:
    return os.getenv("NO_COLOR") is None and os.getenv("TERM") != "dumb"


def paint(text: str, *styles: str, enabled: bool = True) -> str:
    if not enabled:
        return text
    return "".join(styles) + text + RESET


def short_home(path: Path) -> str:
    try:
        return "~/" + str(path.expanduser().resolve().relative_to(Path.home()))
    except ValueError:
        return str(path)


def model_name(model_uri: str) -> str:
    parts = model_uri.split("/")
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return model_uri


def render_header(status: ChatStatus, *, color: bool = True) -> None:
    width = shutil.get_terminal_size((100, 24)).columns
    print()
    logo = [
        "  ██╗   ██╗",
        "  ╚██╗ ██╔╝",
        "   ╚████╔╝ ",
        "    ╚██╔╝  ",
        "     ██║   ",
        "     ╚═╝   ",
    ]
    title = paint("YandexGPT CLI", BOLD, enabled=color) + " " + paint(f"v{__version__}", GRAY, enabled=color)
    auth = paint("●", GREEN, enabled=color) + " Credentials loaded " + paint("/env", GRAY, enabled=color)
    model = paint("◆", CYAN, enabled=color) + f" Model: {model_name(status.model_uri)} " + paint("/model", GRAY, enabled=color)
    hints = paint("? for shortcuts", GRAY, enabled=color)

    for index, line in enumerate(logo):
        colored = _logo_line(line, index, color=color)
        suffix = ""
        if index == 0:
            suffix = "  " + title
        elif index == 2:
            suffix = "  " + auth
        elif index == 3:
            suffix = "  " + model
        print(colored + suffix)

    print()
    print(paint("─" * max(20, width - 2), GRAY, enabled=color))
    print(_status_row(status, width, color=color))
    print(_input_hint(width, color=color))
    print(_bottom_row(status, width, color=color))
    print(paint("─" * max(20, width - 2), GRAY, enabled=color))
    print(hints.rjust(width) if color else "? for shortcuts".rjust(width))


def render_shortcuts(*, color: bool = True) -> None:
    rows = [
        ("/help", "show commands"),
        ("/model", "choose model"),
        ("/history", "show history file"),
        ("/clear", "redraw screen"),
        ("/quit", "exit"),
    ]
    for command, description in rows:
        print(f"{paint(command.ljust(10), CYAN, enabled=color)} {description}")


def prompt(*, color: bool = True) -> str:
    return paint("› ", CYAN, BOLD, enabled=color)


def render_assistant(text: str, *, color: bool = True) -> None:
    print(paint("YandexGPT", MAGENTA, BOLD, enabled=color))
    print(text)


def render_notice(text: str, *, color: bool = True) -> None:
    print(paint(text, YELLOW, enabled=color))


def render_thinking(*, color: bool = True) -> None:
    print(paint("Думаю...", CYAN, enabled=color))


def render_error(text: str, *, color: bool = True) -> None:
    print(paint(text, RED, enabled=color))


def _logo_line(line: str, index: int, *, color: bool) -> str:
    colors = [BLUE, CYAN, GREEN, GREEN, CYAN, BLUE]
    return paint(line, colors[index % len(colors)], BOLD, enabled=color)


def _status_row(status: ChatStatus, width: int, *, color: bool) -> str:
    left = paint("Shift+Tab", GRAY, enabled=color) + " to accept edits"
    right = f"{paint('history', GRAY, enabled=color)} {'on' if status.history_enabled else 'off'}"
    gap = max(1, width - len(_plain(left)) - len(_plain(right)) - 2)
    return f" {left}{' ' * gap}{right} "


def _input_hint(width: int, *, color: bool) -> str:
    hint = " Type your message or @path/to/file"
    visible = hint[: max(1, width - 4)]
    return paint("›", CYAN, BOLD, enabled=color) + paint(visible, BG, GRAY, enabled=color)


def _bottom_row(status: ChatStatus, width: int, *, color: bool) -> str:
    workspace = short_home(status.workspace)
    sandbox = "workspace"
    shell = "shell on" if status.allow_shell else "shell off"
    dry_run = "dry-run" if status.dry_run else "write mode"
    model = model_name(status.model_uri)
    left = f"{paint('workspace', GRAY, enabled=color)} {workspace}"
    mid = f"{paint('sandbox', GRAY, enabled=color)} {sandbox} · {shell} · {dry_run}"
    right = f"{paint('/model', GRAY, enabled=color)} {model}"
    plain_len = len(_plain(left)) + len(_plain(mid)) + len(_plain(right)) + 4
    if plain_len >= width:
        return f" {left}\n {mid}\n {right}"
    gap = max(2, (width - plain_len) // 2)
    return f" {left}{' ' * gap}{mid}{' ' * gap}{right}"


def _plain(text: str) -> str:
    result = ""
    in_escape = False
    for char in text:
        if char == "\033":
            in_escape = True
            continue
        if in_escape:
            if char == "m":
                in_escape = False
            continue
        result += char
    return result
