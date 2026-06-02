from __future__ import annotations

import base64
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .safety import SafetyError, SafetyPolicy


MAX_TEXT_ATTACHMENT_BYTES = 200_000
MAX_IMAGE_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_DIRECTORY_ITEMS = 100
SUPPORTED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
AT_REFERENCE_RE = re.compile(r"(?<![\w.-])@(?:\"([^\"]+)\"|'([^']+)'|(\S+))")


@dataclass(frozen=True)
class PromptAttachments:
    prompt: str
    images: list[dict[str, str]] = field(default_factory=list)
    image_descriptions: list[str] = field(default_factory=list)


def expand_at_references(prompt: str, policy: SafetyPolicy) -> PromptAttachments:
    refs = _extract_at_references(prompt)
    if not refs:
        return PromptAttachments(prompt=prompt)

    sections: list[str] = []
    images: list[dict[str, str]] = []
    image_descriptions: list[str] = []
    errors: list[str] = []

    for raw_ref in refs:
        try:
            path = policy.resolve_workspace_path(raw_ref)
            if path.is_dir():
                sections.append(_directory_section(path, policy.workspace))
                continue
            if not path.is_file():
                errors.append(f"- @{raw_ref}: file not found")
                continue
            if _is_supported_image(path):
                image = _image_attachment(path)
                images.append({"base64": str(image["base64"]), "mime_type": str(image["mime_type"])})
                image_descriptions.append(f"- @{raw_ref}: {image['mime_type']}, {image['size']} bytes")
                continue
            sections.append(_text_file_section(path, policy.workspace))
        except SafetyError as exc:
            errors.append(f"- @{raw_ref}: {exc}")

    extra_parts: list[str] = []
    if sections:
        extra_parts.append("Attached @file context:\n\n" + "\n\n".join(sections))
    if image_descriptions:
        extra_parts.append("Attached @image files sent to the model as base64:\n" + "\n".join(image_descriptions))
    if errors:
        extra_parts.append("Unresolved @ references:\n" + "\n".join(errors))

    expanded_prompt = prompt
    if extra_parts:
        expanded_prompt += "\n\n" + "\n\n".join(extra_parts)
    return PromptAttachments(prompt=expanded_prompt, images=images, image_descriptions=image_descriptions)


def message_with_attachments(role: str, text: str, images: list[dict[str, str]] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": role, "text": text}
    if images:
        message["images"] = images
    return message


def strip_images_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stripped: list[dict[str, Any]] = []
    for message in messages:
        copy = dict(message)
        images = copy.pop("images", None)
        if images:
            text = copy.get("text")
            note = f"[{len(images)} image attachment(s) omitted from saved chat context]"
            copy["text"] = f"{text}\n\n{note}" if isinstance(text, str) and text else note
        stripped.append(copy)
    return stripped


def _extract_at_references(prompt: str) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for match in AT_REFERENCE_RE.finditer(prompt):
        ref = next(group for group in match.groups() if group is not None)
        ref = ref.rstrip(".,;:)?!")
        if not ref or ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def _directory_section(path: Path, workspace: Path) -> str:
    items: list[str] = []
    for child in sorted(path.rglob("*")):
        if len(items) >= MAX_DIRECTORY_ITEMS:
            items.append("... (truncated)")
            break
        if child.is_file():
            items.append(_display(child, workspace))
    return f"### {_display(path, workspace)}/\n" + ("\n".join(items) if items else "(empty directory)")


def _text_file_section(path: Path, workspace: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise SafetyError(f"cannot stat file: {exc}") from exc
    if size > MAX_TEXT_ATTACHMENT_BYTES:
        return f"### {_display(path, workspace)}\n(file is {size} bytes; use read_file for full content)"

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SafetyError(f"cannot read file: {exc}") from exc
    if b"\x00" in data[:4096]:
        return f"### {_display(path, workspace)}\n(binary file omitted)"

    text = data.decode("utf-8", errors="replace")
    return f"### {_display(path, workspace)}\n```text\n{text}\n```"


def _image_attachment(path: Path) -> dict[str, str | int]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise SafetyError(f"cannot stat image: {exc}") from exc
    if size > MAX_IMAGE_ATTACHMENT_BYTES:
        raise SafetyError(f"image is too large to attach ({size} bytes, limit {MAX_IMAGE_ATTACHMENT_BYTES})")

    mime_type = _mime_type(path)
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise SafetyError(f"unsupported image type: {mime_type or 'unknown'}")
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as exc:
        raise SafetyError(f"cannot read image: {exc}") from exc
    return {"base64": encoded, "mime_type": mime_type, "size": size}


def _is_supported_image(path: Path) -> bool:
    return _mime_type(path) in SUPPORTED_IMAGE_MIME_TYPES


def _mime_type(path: Path) -> str | None:
    mime_type, _ = mimetypes.guess_type(path.name)
    return mime_type


def _display(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)
