from __future__ import annotations

import json
import os
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SESSION_VERSION = 1


@dataclass(frozen=True)
class ChatSession:
    id: int
    path: Path
    messages: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "edit"
    workspace: str = ""
    model_uri: str = ""


def sessions_dir() -> Path:
    return Path(os.getenv("YANDEXGPT_SESSIONS", "~/.yandexgpt/sessions")).expanduser()


def create_session(root: Path, *, workspace: Path, model_uri: str, mode: str = "edit") -> ChatSession:
    root.mkdir(parents=True, exist_ok=True)
    session_id = next_session_id(root)
    return ChatSession(
        id=session_id,
        path=session_path(root, session_id),
        messages=[],
        mode=mode,
        workspace=str(workspace),
        model_uri=model_uri,
    )


def load_session(root: Path, session_id: int) -> ChatSession:
    path = session_path(root, session_id)
    if not path.is_file():
        raise SessionError(f"Session {session_id} not found.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SessionError(f"Session {session_id} could not be loaded: {exc}") from exc

    messages = data.get("messages", [])
    if not isinstance(messages, list):
        messages = []
    return ChatSession(
        id=session_id,
        path=path,
        messages=[message for message in messages if isinstance(message, dict)],
        mode="plan" if data.get("mode") == "plan" else "edit",
        workspace=str(data.get("workspace") or ""),
        model_uri=str(data.get("model_uri") or ""),
    )


def save_session(session: ChatSession, *, messages: list[dict[str, Any]] | None, mode: str, workspace: Path, model_uri: str) -> ChatSession:
    session.path.parent.mkdir(parents=True, exist_ok=True)
    clean_messages = [dict(message) for message in messages or [] if isinstance(message, dict)]
    data = {
        "version": SESSION_VERSION,
        "id": session.id,
        "updated_at": int(time.time()),
        "workspace": str(workspace),
        "model_uri": model_uri,
        "mode": "plan" if mode == "plan" else "edit",
        "messages": clean_messages,
    }
    tmp_path = session.path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(session.path)
    try:
        session.path.chmod(0o600)
    except OSError:
        pass
    return ChatSession(
        id=session.id,
        path=session.path,
        messages=clean_messages,
        mode=str(data["mode"]),
        workspace=str(workspace),
        model_uri=model_uri,
    )


def next_session_id(root: Path) -> int:
    ids: list[int] = []
    if root.is_dir():
        for path in root.glob("*.json"):
            try:
                ids.append(int(path.stem))
            except ValueError:
                continue
    return (max(ids) + 1) if ids else 1


def session_path(root: Path, session_id: int) -> Path:
    if session_id < 1:
        raise SessionError("Session id must be a positive integer.")
    return root / f"{session_id}.json"


def resume_command(session_id: int, *, workspace: Path) -> str:
    return f"yandexgpt --workspace {shlex.quote(str(workspace))} --session {session_id}"


def is_empty_session(messages: list[dict[str, Any]] | None) -> bool:
    if not messages:
        return True
    for msg in messages:
        if msg.get("role") == "assistant":
            return False
        if msg.get("role") == "user":
            text = msg.get("text")
            if isinstance(text, str):
                text_clean = text.strip()
                if (text_clean and 
                    not text_clean.startswith("Снимок рабочей директории") and 
                    not text_clean.startswith("Mode: Plan Mode.") and 
                    not text_clean.startswith("Mode: Edit Mode.")):
                    return False
    return True


def delete_all_sessions(root: Path) -> None:
    if not root.is_dir():
        print("Папка сессий не существует или пуста.")
        return
    count = 0
    for path in root.glob("*.json"):
        try:
            path.unlink()
            count += 1
        except OSError as exc:
            print(f"Ошибка при удалении {path.name}: {exc}")
    print(f"Успешно удалено сессий: {count}")


class SessionError(RuntimeError):
    pass
