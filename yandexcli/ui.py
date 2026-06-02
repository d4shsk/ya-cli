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
PURPLE = "\033[38;5;135m"
PINK = "\033[38;5;205m"
ORANGE = "\033[38;5;214m"
RED = "\033[31m"
YELLOW = "\033[33m"
GRAY = "\033[90m"
WHITE = "\033[37m"
BG = "\033[48;5;236m"
BLACK_BG = "\033[48;5;16m"
PANEL_BG = "\033[48;5;235m"
PANEL_BG_SOFT = "\033[48;5;234m"


@dataclass(frozen=True)
class ChatStatus:
    workspace: Path
    model_uri: str
    history_path: Path
    history_enabled: bool
    allow_shell: bool
    dry_run: bool
    mode: str = "edit"
    session_id: int | None = None


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
    render_welcome(status, color=color)


def render_welcome(status: ChatStatus, *, color: bool = True) -> None:
    width, height = shutil.get_terminal_size((100, 28))
    logo = [
        "██╗   ██╗ █████╗  ██████╗ ",
        "╚██╗ ██╔╝██╔══██╗██╔════╝ ",
        " ╚████╔╝ ███████║██║  ███╗",
        "  ╚██╔╝  ██╔══██║██║   ██║",
        "   ██║   ██║  ██║╚██████╔╝",
        "   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ",
    ]
    top_padding = max(2, (height - 17) // 2)
    print("\n" * top_padding, end="")
    for index, line in enumerate(logo):
        print(_center(_welcome_logo_line(line, index, color=color), width))

    model = model_name(status.model_uri)
    session = f"session {status.session_id}" if status.session_id is not None else "session -"
    service = (
        paint("YandexGPT CLI", BOLD, enabled=color)
        + paint(f" v{__version__}", GRAY, enabled=color)
        + paint(" · ", GRAY, enabled=color)
        + paint(session, GRAY, enabled=color)
    )
    info = (
        paint("папка ", GRAY, enabled=color)
        + short_home(status.workspace)
        + paint(" · модель ", GRAY, enabled=color)
        + model
    )
    print()
    print(_center(service, width))
    print(_center(info, width))
    print("\n")


def render_shortcuts(*, color: bool = True) -> None:
    rows = [
        ("/help", "показать команды"),
        ("/config", "показать статус конфига"),
        ("/session", "показать текущую сессию"),
        ("/model", "выбрать модель"),
        ("Tab", "переключить План/Код"),
        ("/forget", "очистить контекст диалога"),
        ("/history", "показать файл истории"),
        ("/clear", "перерисовать экран"),
        ("/quit", "выйти"),
    ]
    for command, description in rows:
        print(f"{paint(command.ljust(10), CYAN, enabled=color)} {description}")


PROMPT_ROWS = 3


@dataclass(frozen=True)
class PromptFrame:
    left: int
    box_width: int
    inner_width: int
    bar: str
    bar_plain: str
    meta_content: str
    hint_line: str
    bg: str
    color: bool
    mode: str

    def render(self, visible_text: str = "", *, cursor_col: int = 0) -> str:
        iw = self.inner_width
        padded = visible_text[:iw].ljust(iw)
        row1 = self._row(self.bg + " " + padded + " " + RESET if self.color else " " + padded)
        row2 = self._row(self.meta_content)
        row3 = self._row(self.hint_line) if self.color else (" " * self.left + self.bar_plain + self.hint_line)
        abs_col = self.left + 1 + 1 + min(cursor_col, iw)
        return (
            row1 + "\r\n"
            + row2 + "\r\n"
            + row3 + "\r\n"
            + f"\033[{PROMPT_ROWS}A\r"
            + (f"\033[{abs_col}C" if abs_col > 0 else "")
        )

    def _row(self, content: str) -> str:
        return " " * self.left + self.bar + content


def build_prompt_frame(mode: str = "edit", *, color: bool = True) -> PromptFrame:
    style = mode_style(mode)
    width = shutil.get_terminal_size((100, 24)).columns
    box_width = min(78, max(34, width - 12))
    left = max(0, (width - box_width) // 2)
    inner_width = box_width - 3
    if color:
        bar = paint("▌", style, BOLD, enabled=True)
        bg = PANEL_BG
        meta_text = _prompt_meta(mode)
        meta_plain_len = len(_plain(meta_text)) + 2
        meta_content = bg + " " + meta_text + " " * max(0, inner_width - meta_plain_len + 1) + " " + RESET
        hint_parts = (
            paint("Tab", WHITE, BOLD, enabled=True) + paint(" режим   ", GRAY, enabled=True)
            + paint("@", WHITE, BOLD, enabled=True) + paint(" файлы   ", GRAY, enabled=True)
            + paint("?", WHITE, BOLD, enabled=True) + paint(" команды   ", GRAY, enabled=True)
            + paint("/model", WHITE, BOLD, enabled=True) + paint(" модель", GRAY, enabled=True)
        )
        hint_plain_len = len(_plain(hint_parts))
        pad_r = max(0, inner_width + 1 - hint_plain_len)
        hint_line = bg + " " + hint_parts + " " * pad_r + " " + RESET
    else:
        bar = "|"
        bg = ""
        meta_text_plain = _plain(_prompt_meta(mode))
        meta_content = (" " + meta_text_plain).ljust(inner_width + 2)[:inner_width + 2]
        hint_line = (" Tab режим   @ файлы   ? команды   /model модель").ljust(inner_width + 2)[:inner_width + 2]

    return PromptFrame(
        left=left, box_width=box_width, inner_width=inner_width,
        bar=bar, bar_plain="|" if not color else bar,
        meta_content=meta_content, hint_line=hint_line,
        bg=bg, color=color, mode=mode,
    )


def prompt(*, mode: str = "edit", color: bool = True) -> str:
    frame = build_prompt_frame(mode, color=color)
    return frame.render()


def mode_label(mode: str) -> str:
    return "План" if mode == "plan" else "Код"


def mode_style(mode: str) -> str:
    return PINK if mode == "plan" else PURPLE


def render_assistant(text: str, *, color: bool = True) -> None:
    if not text:
        return
    print(paint("Ответ", GRAY, enabled=color))
    print(text)
    print()


def render_user(text: str, *, mode: str = "edit", color: bool = True) -> None:
    if not text:
        return
    style = mode_style(mode)
    label = paint(mode_label(mode), style, BOLD, enabled=color)
    for index, line in enumerate(text.splitlines() or [""]):
        marker = label if index == 0 else " " * len(mode_label(mode))
        print(paint("▌ ", style, BOLD, enabled=color) + marker + paint("  ", GRAY, enabled=color) + line)
    print()


def render_notice(text: str, *, color: bool = True) -> None:
    print(paint(text, YELLOW, enabled=color))


def render_thinking(*, color: bool = True) -> None:
    print(paint("Думаю...", PURPLE, enabled=color))


def render_error(text: str, *, color: bool = True) -> None:
    print(paint(text, RED, enabled=color))


def clear_screen(*, color: bool = True) -> None:
    if color:
        print("\033[2J\033[H", end="")
    else:
        print()


def render_model_picker(current_model: str, menu: str, *, color: bool = True) -> None:
    width, height = shutil.get_terminal_size((100, 28))
    raw_lines = menu.splitlines()
    max_width = min(max([len("Выбор модели"), len(f"Текущая: {model_name(current_model)}"), *(len(line) for line in raw_lines)] + [42]) + 4, max(44, width - 8))
    visible_rows = max(6, min(len(raw_lines), height - 10))
    window_height = visible_rows + 7 + (1 if len(raw_lines) > visible_rows else 0)
    top = max(1, (height - window_height) // 2)
    left = max(0, (width - max_width) // 2)
    indent = " " * left
    border = "─" * (max_width - 2)

    print("\n" * top, end="")
    print(indent + paint("╭" + border + "╮", PURPLE, enabled=color))
    print(indent + paint("│", PURPLE, enabled=color) + _pad(" Выбор модели", max_width - 2) + paint("│", PURPLE, enabled=color))
    print(indent + paint("│", PURPLE, enabled=color) + _pad(f" Текущая: {model_name(current_model)}", max_width - 2) + paint("│", PURPLE, enabled=color))
    print(indent + paint("├" + border + "┤", PURPLE, enabled=color))
    for line in raw_lines[:visible_rows]:
        print(indent + paint("│", PURPLE, enabled=color) + _pad(" " + line, max_width - 2) + paint("│", PURPLE, enabled=color))
    if len(raw_lines) > visible_rows:
        print(indent + paint("│", PURPLE, enabled=color) + _pad(f" ... ещё {len(raw_lines) - visible_rows}", max_width - 2) + paint("│", PURPLE, enabled=color))
    print(indent + paint("├" + border + "┤", PURPLE, enabled=color))
    print(indent + paint("│", PURPLE, enabled=color) + _pad(" Введите номер, provider/model или Enter для отмены", max_width - 2) + paint("│", PURPLE, enabled=color))
    print(indent + paint("╰" + border + "╯", PURPLE, enabled=color))


def model_picker_prompt(*, color: bool = True) -> str:
    width = shutil.get_terminal_size((100, 28)).columns
    prompt_width = min(62, max(34, width - 10))
    left = max(0, (width - prompt_width) // 2)
    return " " * left + paint("модель> ", PURPLE, BOLD, enabled=color)


def _logo_line(line: str, index: int, *, color: bool) -> str:
    colors = [PURPLE, PURPLE, MAGENTA, MAGENTA, PINK, BLUE, BLUE]
    if "▲" not in line:
        return paint(line, colors[index % len(colors)], BOLD, enabled=color)
    result = ""
    for char in line:
        if char == "▲":
            result += paint(char, WHITE, BOLD, enabled=color)
        else:
            result += paint(char, colors[index % len(colors)], BOLD, enabled=color)
    return result


def _input_hint(width: int, *, color: bool) -> str:
    hint = " Введите промпт, вставьте текст или используйте /help"
    visible = hint[: max(1, width - 4)]
    return paint("›", CYAN, BOLD, enabled=color) + paint(visible, BG, GRAY, enabled=color)


def _bottom_row(status: ChatStatus, width: int, *, color: bool) -> str:
    workspace = short_home(status.workspace)
    model = model_name(status.model_uri)
    mode = mode_label(status.mode)
    session = f"session {status.session_id}" if status.session_id is not None else "session -"
    left = f"{paint('папка', GRAY, enabled=color)} {workspace}"
    right = f"{paint(session, GRAY, enabled=color)}  {paint(mode, mode_style(status.mode), enabled=color)}  {paint('/model', GRAY, enabled=color)} {model}"
    plain_len = len(_plain(left)) + len(_plain(right)) + 4
    if plain_len >= width:
        return f" {left}\n {right}"
    gap = max(2, width - plain_len)
    return f" {left}{' ' * gap}{right}"


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


def _center(text: str, width: int) -> str:
    visible = len(_plain(text))
    if visible >= width:
        return text
    return " " * ((width - visible) // 2) + text


def _input_mode_row(status: ChatStatus, width: int, *, color: bool) -> str:
    box_width = min(78, max(34, width - 12))
    inner_width = max(24, box_width - 4)
    label = paint(mode_label(status.mode), mode_style(status.mode), BOLD, enabled=color)
    model = paint(model_name(status.model_uri), WHITE, BOLD, enabled=color)
    text = label + paint(" · ", GRAY, enabled=color) + model
    filler = " " * max(1, inner_width - len(_plain(text)))
    if color:
        return " " + PANEL_BG + " " + text + filler + " " + RESET
    return "  " + _plain(text) + filler


def _prompt_meta(mode: str) -> str:
    label = paint(mode_label(mode), mode_style(mode), BOLD, enabled=True)
    return label + paint(" · ", GRAY, enabled=True)


def _welcome_logo_line(line: str, index: int, *, color: bool) -> str:
    styles = [PURPLE, PURPLE, MAGENTA, MAGENTA, PINK, PINK]
    return paint(line, styles[index % len(styles)], BOLD, enabled=color)


def _pad(text: str, width: int) -> str:
    visible = len(_plain(text))
    if visible > width:
        plain = _plain(text)
        return plain[: max(0, width - 1)] + "…"
    return text + " " * (width - visible)
