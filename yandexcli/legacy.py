from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


LEGACY_START = "[TOOL_CALL_START]"
LEGACY_END = "[TOOL_CALL_END]"
BRACKET_TOOL_NAMES = {"read_file", "write_file", "edit_file", "list_files", "search_files", "run_shell", "read", "write", "edit", "shell"}


@dataclass(frozen=True)
class LegacyToolCall:
    name: str
    arguments: dict[str, Any]


def parse_legacy_tool_call(text: str) -> LegacyToolCall | None:
    marker_index = text.find(LEGACY_START)
    if marker_index < 0:
        return None

    body = text[marker_index + len(LEGACY_START) :].strip()
    if LEGACY_END in body:
        body = body.split(LEGACY_END, 1)[0].strip()

    match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*", body)
    if not match:
        return None

    name = match.group(1)
    json_source = body[match.end() :].strip()
    if not json_source:
        return None

    try:
        arguments, _ = json.JSONDecoder().raw_decode(json_source)
    except json.JSONDecodeError:
        return None

    if not isinstance(arguments, dict):
        return None
    if name == "write" and "path" not in arguments:
        arguments = {"path": arguments.get("filename") or arguments.get("file") or "index.html", **arguments}
    return LegacyToolCall(name=name, arguments=arguments)


def parse_legacy_tool_calls(text: str) -> list[LegacyToolCall]:
    calls: list[LegacyToolCall] = []
    legacy_call = parse_legacy_tool_call(text)
    if legacy_call is not None:
        calls.append(legacy_call)

    for match in re.finditer(r"\[([A-Za-z_][A-Za-z0-9_]*)\]\s*", text):
        name = match.group(1)
        if name not in BRACKET_TOOL_NAMES:
            continue

        arguments = _decode_bracket_arguments(text[match.end() :])
        if arguments is None:
            continue
        calls.append(LegacyToolCall(name=name, arguments=_normalize_arguments(name, arguments)))

    return calls


def contains_pseudo_tool_call(text: str) -> bool:
    if LEGACY_START in text:
        return True
    return any(match.group(1) in BRACKET_TOOL_NAMES for match in re.finditer(r"\[([A-Za-z_][A-Za-z0-9_]*)\]", text))


def _decode_bracket_arguments(source: str) -> dict[str, Any] | None:
    stripped = source.lstrip()
    candidates = []
    if stripped.startswith("{"):
        candidates.append(stripped)

    object_source = _extract_balanced_json_object(stripped)
    if object_source:
        candidates.append(object_source)

    # Some models print a JSON object as an escaped string, e.g. {\"path\":...}.
    unescaped = stripped.replace('\\"', '"').replace("\\\\n", "\\n")
    if unescaped.startswith("{"):
        candidates.append(unescaped)
    object_unescaped = _extract_balanced_json_object(unescaped)
    if object_unescaped:
        candidates.append(object_unescaped)

    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            arguments, _ = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(arguments, dict):
            return arguments
    return None


def _extract_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _normalize_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: _decode_escaped_string(value) for key, value in arguments.items()}
    if name == "write" and "path" not in arguments:
        return {"path": normalized.get("filename") or normalized.get("file") or "index.html", **normalized}
    return normalized


def _decode_escaped_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if "\\u" not in value and "\\n" not in value and '\\"' not in value:
        return value
    decoded = re.sub(r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match.group(1), 16)), value)
    decoded = decoded.replace("\\n", "\n").replace('\\"', '"')
    return decoded
