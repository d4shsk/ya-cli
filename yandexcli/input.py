from __future__ import annotations

import codecs
import os
import re
import readline
import select
import sys
import termios
import tty
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


def read_char(fd: int) -> str:
    decoder = codecs.getincrementaldecoder('utf-8')()
    while True:
        try:
            b = os.read(fd, 1)
        except OSError:
            return ""
        if not b:
            return ""
        try:
            char = decoder.decode(b)
            if char:
                return char
        except Exception:
            decoder.reset()


BRACKETED_PASTE_ON = "\033[?2004h"
BRACKETED_PASTE_OFF = "\033[?2004l"
PASTE_START = "\033[200~"
PASTE_END = "\033[201~"
ANSI_RESET = "\033[0m"
SKIPPED_COMPLETION_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".pytest_cache", "node_modules",
    "library", "applications", "system", "pictures", "music", "movies", "public",
    "appdata", "local settings", "application data", "cookies", "nethood", "printhood",
    "recent", "sendto", "start menu", "templates", "searches", "links", "saved games",
    "contacts", "onedrive", ".cache", ".local", ".config", ".mozilla", ".vscode",
    ".cargo", ".rustup", ".npm", "venv", ".venv", "env", ".env"
}
ANSI_RE = re.compile(r"\033\[[0-9;?]*[A-Za-z]")


def visible_input_text(value: str, pasted_line_counts: list[int], inner_width: int) -> tuple[str, int]:
    display = _display_value(value, pasted_line_counts)
    if len(display) <= inner_width:
        return display, len(display)
    return display[len(display) - inner_width:], inner_width


@dataclass
class PasteAwarePrompt:
    prompt_text: str
    history_enabled: bool = True
    history: list[str] = field(default_factory=list)
    on_tab: Callable[[], str] | None = None
    file_completion_root: Path | None = None
    completion_limit: int = 8
    frame: object | None = None
    last_menu_height: int = 0

    def read(self) -> str:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return input(self.prompt_text)

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        buffer: list[str] = []
        pasted_line_counts: list[int] = []
        history_index = len(self.history)
        completion_index = 0
        completion_hidden = False
        self.last_menu_height = 0

        try:
            tty.setraw(fd)
            if self.frame is not None:
                self._write(self.frame.render())
            else:
                self._write(self.prompt_text)
            while True:
                char = read_char(fd)
                if char in {"\r", "\n"}:
                    choices = [] if completion_hidden else self._completion_choices("".join(buffer))
                    if choices:
                        buffer = [self._apply_completion("".join(buffer), choices[completion_index % len(choices)])]
                        pasted_line_counts = []
                        completion_index = 0
                        completion_hidden = True
                        self._redraw_completion(buffer, pasted_line_counts, completion_index, completion_hidden)
                        continue
                    self._write(ANSI_RESET + "\r\n")
                    value = "".join(buffer).strip()
                    if value and self.history_enabled:
                        self.history.append(value)
                        readline.add_history(value)
                    return value
                if char == "\x03":
                    raise KeyboardInterrupt
                if char == "\x04":
                    if not buffer:
                        raise EOFError
                    continue
                if char in {"\x7f", "\b"}:
                    if buffer:
                        buffer.pop()
                        completion_index = 0
                        completion_hidden = False
                        self._redraw_completion(buffer, pasted_line_counts, completion_index, completion_hidden)
                    continue
                if char == "\t":
                    if self.on_tab is not None:
                        self.prompt_text = self.on_tab()
                        self._redraw_completion(buffer, pasted_line_counts, completion_index, completion_hidden)
                    continue
                if char == "\x1b":
                    sequence = self._read_escape_sequence(fd)
                    if sequence == PASTE_START:
                        pasted = self._read_paste(fd)
                        if pasted:
                            buffer.append(pasted)
                            pasted_line_counts.append(_line_count(pasted))
                            completion_index = 0
                            completion_hidden = False
                            self._redraw_completion(buffer, pasted_line_counts, completion_index, completion_hidden)
                        continue
                    choices = [] if completion_hidden else self._completion_choices("".join(buffer))
                    if sequence == "\033[A":
                        if choices:
                            completion_index = (completion_index - 1) % len(choices)
                            self._redraw(buffer, pasted_line_counts, choices, completion_index)
                        elif self.history:
                            history_index = max(0, history_index - 1)
                            buffer = [self.history[history_index]]
                            pasted_line_counts = []
                            completion_index = 0
                            completion_hidden = False
                            self._redraw_completion(buffer, pasted_line_counts, completion_index, completion_hidden)
                        continue
                    if sequence == "\033[B":
                        if choices:
                            completion_index = (completion_index + 1) % len(choices)
                            self._redraw(buffer, pasted_line_counts, choices, completion_index)
                        elif self.history:
                            history_index = min(len(self.history), history_index + 1)
                            buffer = [] if history_index == len(self.history) else [self.history[history_index]]
                            pasted_line_counts = []
                            completion_index = 0
                            completion_hidden = False
                            self._redraw_completion(buffer, pasted_line_counts, completion_index, completion_hidden)
                        continue
                    if sequence == "\033[C" and choices:
                        buffer = [self._apply_completion("".join(buffer), choices[completion_index % len(choices)])]
                        pasted_line_counts = []
                        completion_index = 0
                        completion_hidden = True
                        self._redraw_completion(buffer, pasted_line_counts, completion_index, completion_hidden)
                        continue
                    if sequence == "\033":
                        completion_hidden = True
                        self._redraw_completion(buffer, pasted_line_counts, completion_index, completion_hidden)
                    continue
                if char >= " ":
                    buffer.append(char)
                    completion_index = 0
                    completion_hidden = False
                    self._redraw_completion(buffer, pasted_line_counts, completion_index, completion_hidden)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _read_escape_sequence(self, fd: int) -> str:
        sequence = "\033"
        while len(sequence) < len(PASTE_START):
            ready, _, _ = select.select([fd], [], [], 0.05)
            if not ready:
                return sequence
            try:
                b = os.read(fd, 1)
            except OSError:
                return sequence
            if not b:
                return sequence
            sequence += b.decode('ascii', errors='ignore')
            if sequence in {PASTE_START, PASTE_END, "\033[A", "\033[B", "\033[C", "\033[D"}:
                return sequence
            if not any(candidate.startswith(sequence) for candidate in (PASTE_START, PASTE_END, "\033[A", "\033[B", "\033[C", "\033[D")):
                return sequence
        return sequence

    def _read_paste(self, fd: int) -> str:
        data: list[str] = []
        window = ""
        while True:
            char = read_char(fd)
            if not char:
                break
            window += char
            if window.endswith(PASTE_END):
                pasted = window[: -len(PASTE_END)]
                data.append(pasted)
                return "".join(data)
            if len(window) > len(PASTE_END):
                data.append(window[0])
                window = window[1:]
        return "".join(data)

    def _redraw_completion(self, buffer: list[str], pasted_line_counts: list[int], completion_index: int, completion_hidden: bool) -> None:
        choices = [] if completion_hidden else self._completion_choices("".join(buffer))
        self._redraw(buffer, pasted_line_counts, choices, completion_index)

    def _redraw(self, buffer: list[str], pasted_line_counts: list[int], choices: list[str] | None = None, completion_index: int = 0) -> None:
        width = os.get_terminal_size().columns
        frame = self.frame
        if frame is not None:
            # 1. Move up by last_menu_height to the top of the previous block
            if self.last_menu_height > 0:
                self._write(f"\033[{self.last_menu_height}A")
            
            # 2. Clear all rows below
            self._write(f"\r\033[J")
            
            # 3. Compute menu (if any) and get its height
            menu_lines = []
            if choices:
                val = "".join(buffer)
                token_info = _active_at_token(val)
                indent = frame.left + 2
                if token_info:
                    start_idx, _ = token_info
                    display_val = _display_value(val, pasted_line_counts)
                    offset = max(0, len(display_val) - frame.inner_width)
                    relative_token_start = max(0, start_idx - offset)
                    indent = frame.left + 2 + relative_token_start
                menu_lines = _completion_menu(choices, completion_index, width, indent)
            
            self.last_menu_height = len(menu_lines)
            
            # 4. Draw the menu above the prompt
            if menu_lines:
                self._write("\r\n".join(menu_lines) + "\r\n")
                
            # 5. Draw the prompt frame
            vis, cur = visible_input_text("".join(buffer), pasted_line_counts, frame.inner_width)
            block = frame.render(vis, cursor_col=cur)
            self._write(block)
            return
        # Legacy path for non-frame prompts
        self.last_menu_height = 0
        display = _display_value("".join(buffer), pasted_line_counts)
        line = self.prompt_text + display
        top_offset = _prompt_top_offset(self.prompt_text)
        if top_offset:
            self._write(f"\033[{top_offset}A")
        self._write("\r\033[J")
        self._write(line + ANSI_RESET)
        if choices:
            menu = _completion_menu(choices, completion_index, width)
            self._write("\r\n" + "\r\n".join(menu))
            self._write(f"\033[{len(menu)}A\r")
            column = _last_visual_column(line)
            if column:
                self._write(f"\033[{column}C")

    def _write(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    def _completion_choices(self, value: str) -> list[str]:
        token = _active_at_token(value)
        if self.file_completion_root is None or token is None:
            return []
        _, query = token
        return file_completion_choices(self.file_completion_root, query, limit=self.completion_limit)

    def _apply_completion(self, value: str, replacement: str) -> str:
        token = _active_at_token(value)
        if token is None:
            return value
        start, _ = token
        return value[:start] + replacement


def enable_bracketed_paste() -> None:
    try:
        readline.parse_and_bind("set enable-bracketed-paste off")
    except Exception:
        pass
    if sys.stdin.isatty() and sys.stdout.isatty():
        sys.stdout.write(BRACKETED_PASTE_OFF)
        sys.stdout.flush()


def disable_bracketed_paste() -> None:
    pass


def readline_history() -> list[str]:
    return [
        item
        for item in (readline.get_history_item(index) for index in range(1, readline.get_current_history_length() + 1))
        if item
    ]


def _line_count(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines()) or 1


def _display_value(value: str, pasted_line_counts: list[int]) -> str:
    if not pasted_line_counts:
        return value
    total = sum(pasted_line_counts)
    return f"[Вставлено строк: {total}]"


def _active_at_token(value: str) -> tuple[int, str] | None:
    stripped = value.rstrip()
    if stripped != value:
        return None
    start = max(value.rfind(" "), value.rfind("\t"), value.rfind("\n")) + 1
    token = value[start:]
    if not token.startswith("@"):
        return None
    return start, token[1:].strip("\"'")


def file_completion_choices(root: Path, query: str, *, limit: int = 8) -> list[str]:
    cleaned_query = query.lstrip("./")
    
    if "/" in cleaned_query:
        dir_part, file_query = cleaned_query.rsplit("/", 1)
        search_root = root / dir_part
    else:
        dir_part, file_query = "", cleaned_query
        search_root = root
        
    file_query_lower = file_query.lower()
        
    if not search_root.exists() or not search_root.is_dir():
        return []
        
    matches: list[tuple[int, int, str]] = []
    max_visits = 5000
    visited_count = 0
    
    try:
        for dirpath, dirs, files in os.walk(search_root, followlinks=False):
            # Prune ignored directories in-place to avoid descending into them
            dirs[:] = [
                d for d in dirs
                if d.lower() not in SKIPPED_COMPLETION_DIRS
                and not d.startswith(".")
            ]
            
            for file in files:
                if file.startswith("."):
                    continue
                
                visited_count += 1
                if visited_count > max_visits:
                    break
                
                full_path = Path(dirpath) / file
                try:
                    relative = full_path.relative_to(root)
                except ValueError:
                    continue
                
                display = relative.as_posix()
                lowered = display.lower()
                name = file.lower()
                
                if file_query_lower and file_query_lower not in name and file_query_lower not in lowered:
                    continue
                
                rank = 0 if name.startswith(file_query_lower) else 1 if file_query_lower in name else 2
                matches.append((rank, len(display), display))
                
            if visited_count > max_visits:
                break
    except OSError:
        return []
        
    matches.sort()
    return [_at_reference(display) for _, _, display in matches[:limit]]


def _skip_completion_path(path: Path) -> bool:
    return any(part.lower() in SKIPPED_COMPLETION_DIRS or part.startswith(".") for part in path.parts)


def _at_reference(path: str) -> str:
    if not any(char.isspace() for char in path) and "\"" not in path and "'" not in path:
        return f"@{path}"
    if "'" not in path:
        return f"@'{path}'"
    if "\"" not in path:
        return f'@"{path}"'
    return f"@{path}"


def _completion_menu(choices: list[str], index: int, width: int, indent: int = 0) -> list[str]:
    rows = []
    prefix = " " * indent
    available_width = max(10, width - indent - 1)
    for offset, choice in enumerate(choices):
        marker = "›" if offset == index % len(choices) else " "
        rows.append(prefix + (f"  {marker} {choice}")[:available_width])
    rows.append(prefix + ("   ↑/↓ выбрать  Enter/→ вставить  Esc закрыть"[:available_width]))
    return rows


def _strip_ansi(value: str) -> str:
    return ANSI_RE.sub("", value)


def _prompt_top_offset(prompt_text: str) -> int:
    moves = [int(match) for match in re.findall(r"\033\[(\d+)A", prompt_text)]
    cursor_up = moves[-1] if moves else 0
    return max(0, prompt_text.count("\n") - cursor_up)


def _last_visual_column(value: str) -> int:
    plain = _strip_ansi(value)
    return len(plain.rsplit("\n", 1)[-1])
