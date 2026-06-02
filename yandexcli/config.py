from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_NAME = "yacli.jsonc"
SUPPORTED_PROVIDER_NPMS = {"yandex", "@ai-sdk/openai-compatible", "@ai-sdk/anthropic"}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    id: str
    name: str
    npm: str
    options: dict[str, Any]
    models: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class ResolvedModel:
    provider: ProviderConfig
    model_id: str
    model: dict[str, Any]
    ref: str

    @property
    def display_name(self) -> str:
        name = self.model.get("name")
        return name if isinstance(name, str) and name else self.ref


@dataclass(frozen=True)
class YacliConfig:
    path: Path | None
    providers: dict[str, ProviderConfig]
    default_model: str
    permission: dict[str, Any]

    def resolve_model(self, selection: str | None = None) -> ResolvedModel:
        normalized = (selection or self.default_model).strip()
        all_models = self._all_models()
        if not all_models:
            raise ConfigError("No models are configured in yacli.jsonc.")

        if not normalized:
            return all_models[0]

        if normalized.isdigit():
            index = int(normalized) - 1
            if 0 <= index < len(all_models):
                return all_models[index]
            raise ConfigError(f"Unknown model number: {normalized}")

        if normalized.startswith("gpt://"):
            provider = self.providers.get("yandex")
            if provider is None:
                raise ConfigError("Raw gpt:// model URI requires a yandex provider in yacli.jsonc.")
            return ResolvedModel(
                provider=provider,
                model_id=normalized,
                model={"name": normalized, "modelUri": normalized},
                ref=normalized,
            )

        if "/" in normalized:
            provider_id, model_id = normalized.split("/", 1)
            provider = self.providers.get(provider_id)
            if provider is None or model_id not in provider.models:
                raise ConfigError(f"Unknown model: {normalized}")
            return ResolvedModel(provider=provider, model_id=model_id, model=provider.models[model_id], ref=normalized)

        matches = [item for item in all_models if item.model_id == normalized]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            refs = ", ".join(item.ref for item in matches)
            raise ConfigError(f"Model name {normalized!r} is ambiguous. Use one of: {refs}")
        raise ConfigError(f"Unknown model: {normalized}")

    def model_menu(self) -> str:
        lines: list[str] = []
        for index, item in enumerate(self._all_models(), 1):
            lines.append(f"{index}. {item.ref} - {item.display_name}")
        lines.append("Можно указать provider/model, уникальный id модели или полный gpt:// URI для Yandex.")
        return "\n".join(lines)

    def _all_models(self) -> list[ResolvedModel]:
        models: list[ResolvedModel] = []
        for provider in self.providers.values():
            for model_id, model in provider.models.items():
                models.append(ResolvedModel(provider=provider, model_id=model_id, model=model, ref=f"{provider.id}/{model_id}"))
        return models


def load_config(path: Path | None = None, *, cwd: Path | None = None, project_root: Path | None = None) -> YacliConfig:
    config_path = find_config_path(path, cwd=cwd, project_root=project_root)
    if config_path is None:
        raise ConfigError(
            "yacli.jsonc not found. Create it in the workspace or pass --config. "
            "See yacli.example.jsonc for a Yandex-ready template."
        )
    warn_if_config_is_too_open(config_path)
    try:
        raw = config_path.read_text(encoding="utf-8")
        data = json.loads(strip_jsonc(raw))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Could not load {config_path}: {exc}") from exc
    return parse_config(data, path=config_path)


def find_config_path(path: Path | None = None, *, cwd: Path | None = None, project_root: Path | None = None) -> Path | None:
    if path is not None:
        return path.expanduser().resolve()

    env_path = os.getenv("YACLI_CONFIG", "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()

    roots = [cwd or Path.cwd()]
    if project_root is not None:
        roots.append(project_root)
    roots.append(Path("~/.config/yandexgpt").expanduser())

    seen: set[Path] = set()
    for root in roots:
        candidate = (root / DEFAULT_CONFIG_NAME).expanduser().resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            return candidate
    return None


def parse_config(data: Any, *, path: Path | None = None) -> YacliConfig:
    if not isinstance(data, dict):
        raise ConfigError("yacli.jsonc must contain a JSON object.")
    provider_data = data.get("provider")
    if not isinstance(provider_data, dict) or not provider_data:
        raise ConfigError("yacli.jsonc must contain a non-empty provider object.")

    providers: dict[str, ProviderConfig] = {}
    for provider_id, raw_provider in provider_data.items():
        if not isinstance(provider_id, str) or not isinstance(raw_provider, dict):
            continue
        npm = str(raw_provider.get("npm") or "yandex").strip()
        if npm not in SUPPORTED_PROVIDER_NPMS:
            raise ConfigError(f"Provider {provider_id!r} uses unsupported npm value: {npm}")
        models = raw_provider.get("models")
        if not isinstance(models, dict) or not models:
            raise ConfigError(f"Provider {provider_id!r} must define at least one model.")
        clean_models = {str(model_id): dict(model) for model_id, model in models.items() if isinstance(model, dict)}
        if not clean_models:
            raise ConfigError(f"Provider {provider_id!r} must define object models.")
        options = raw_provider.get("options")
        providers[provider_id] = ProviderConfig(
            id=provider_id,
            name=str(raw_provider.get("name") or provider_id),
            npm=npm,
            options=dict(options) if isinstance(options, dict) else {},
            models=clean_models,
        )

    default_model = str(data.get("model") or "").strip()
    if not default_model:
        first_provider = next(iter(providers.values()))
        default_model = f"{first_provider.id}/{next(iter(first_provider.models))}"

    permission = data.get("permission")
    return YacliConfig(
        path=path,
        providers=providers,
        default_model=default_model,
        permission=dict(permission) if isinstance(permission, dict) else {},
    )


def warn_if_config_is_too_open(path: Path) -> None:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        print(f"warning: {path} is readable or writable by group/others; consider `chmod 600 {path}`.", file=sys.stderr)


def strip_jsonc(text: str) -> str:
    without_comments = _strip_jsonc_comments(text)
    return _strip_trailing_commas(without_comments)


def _strip_jsonc_comments(text: str) -> str:
    result: list[str] = []
    in_string = False
    escape = False
    index = 0
    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == "/" and nxt == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and nxt == "*":
            index += 2
            while index + 1 < len(text) and not (text[index] == "*" and text[index + 1] == "/"):
                result.append("\n" if text[index] in "\r\n" else " ")
                index += 1
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _strip_trailing_commas(text: str) -> str:
    result: list[str] = []
    in_string = False
    escape = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue
        result.append(char)
        index += 1
    return "".join(result)
