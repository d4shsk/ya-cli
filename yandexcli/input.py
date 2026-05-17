from __future__ import annotations

import os
import readline
import sys
import termios
import tty
from dataclasses import dataclass, field


BRACKETED_PASTE_ON = "\033[?2004h"
BRACKETED_PASTE_OFF = "\033[?2004l"
PASTE_START = "\033[200~"
PASTE_END = "\033[201~"


@dataclass
class PasteAwarePrompt:
    prompt_text: str
    history_enabled: bool = True
    history: list[str] = field(default_factory=list)

    def read(self) -> str:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return input(self.prompt_text)

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        buffer: list[str] = []
        pasted_line_counts: list[int] = []
        history_index = len(self.history)

        try:
            tty.setraw(fd)
            self._write(self.prompt_text)
            while True:
                char = sys.stdin.read(1)
                if char in {"\r", "\n"}:
                    self._write("\r\n")
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
                        self._redraw(buffer, pasted_line_counts)
                    continue
                if char == "\x1b":
                    sequence = self._read_escape_sequence()
                    if sequence == PASTE_START:
                        pasted = self._read_paste()
                        if pasted:
                            buffer.append(pasted)
                            pasted_line_counts.append(_line_count(pasted))
                            self._redraw(buffer, pasted_line_counts)
                        continue
                    if sequence == "\033[A":
                        if self.history:
                            history_index = max(0, history_index - 1)
                            buffer = [self.history[history_index]]
                            pasted_line_counts = []
                            self._redraw(buffer, pasted_line_counts)
                        continue
                    if sequence == "\033[B":
                        if self.history:
                            history_index = min(len(self.history), history_index + 1)
                            buffer = [] if history_index == len(self.history) else [self.history[history_index]]
                            pasted_line_counts = []
                            self._redraw(buffer, pasted_line_counts)
                        continue
                    continue
                if char >= " ":
                    buffer.append(char)
                    self._write(char)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _read_escape_sequence(self) -> str:
        sequence = "\033"
        while len(sequence) < len(PASTE_START):
            char = sys.stdin.read(1)
            sequence += char
            if sequence in {PASTE_START, PASTE_END, "\033[A", "\033[B", "\033[C", "\033[D"}:
                return sequence
            if not any(candidate.startswith(sequence) for candidate in (PASTE_START, PASTE_END, "\033[A", "\033[B", "\033[C", "\033[D")):
                return sequence
        return sequence

    def _read_paste(self) -> str:
        data: list[str] = []
        window = ""
        while True:
            char = sys.stdin.read(1)
            window += char
            if window.endswith(PASTE_END):
                pasted = window[: -len(PASTE_END)]
                data.append(pasted)
                return "".join(data)
            if len(window) > len(PASTE_END):
                data.append(window[0])
                window = window[1:]

    def _redraw(self, buffer: list[str], pasted_line_counts: list[int]) -> None:
        display = _display_value("".join(buffer), pasted_line_counts)
        width = os.get_terminal_size().columns
        self._write("\r\033[K")
        self._write((self.prompt_text + display)[: max(1, width - 1)])

    def _write(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()


def enable_bracketed_paste() -> None:
    if sys.stdin.isatty() and sys.stdout.isatty():
        sys.stdout.write(BRACKETED_PASTE_ON)
        sys.stdout.flush()


def disable_bracketed_paste() -> None:
    if sys.stdin.isatty() and sys.stdout.isatty():
        sys.stdout.write(BRACKETED_PASTE_OFF)
        sys.stdout.flush()


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
