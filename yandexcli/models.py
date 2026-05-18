from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelOption:
    key: str
    label: str
    uri_template: str

    def uri(self, folder_id: str) -> str:
        return self.uri_template.format(folder_id=folder_id)


MODEL_OPTIONS: list[ModelOption] = [
    ModelOption("yandexgpt-5-lite", "YandexGPT 5 Lite, актуальная версия", "gpt://{folder_id}/yandexgpt-5-lite/latest"),
    ModelOption("alice", "Alice AI LLM, актуальная версия", "gpt://{folder_id}/aliceai-llm/latest"),
    ModelOption("yandexgpt-5-pro", "YandexGPT 5 Pro, актуальная версия", "gpt://{folder_id}/yandexgpt-5-pro/latest"),
    ModelOption("yandexgpt-5.1", "YandexGPT 5.1, актуальная версия", "gpt://{folder_id}/yandexgpt-5.1/latest"),
]


def default_model_uri(folder_id: str) -> str:
    return MODEL_OPTIONS[1].uri(folder_id)


def resolve_model_uri(selection: str, folder_id: str) -> str | None:
    normalized = selection.strip()
    if not normalized:
        return None
    if normalized.startswith("gpt://"):
        return normalized

    lowered = normalized.lower()
    for index, option in enumerate(MODEL_OPTIONS, 1):
        if lowered in {option.key, str(index)}:
            return option.uri(folder_id)
    return None


def model_menu(folder_id: str) -> str:
    lines = []
    for index, option in enumerate(MODEL_OPTIONS, 1):
        lines.append(f"{index}. {option.key} - {option.label} ({option.uri(folder_id)})")
    lines.append("Или вставьте полный URI модели вида gpt://...")
    return "\n".join(lines)
