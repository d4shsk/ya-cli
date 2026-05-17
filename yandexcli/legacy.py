from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


LEGACY_START = "[TOOL_CALL_START]"
LEGACY_END = "[TOOL_CALL_END]"


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
