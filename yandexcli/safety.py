from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class SafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class SafetyPolicy:
    workspace: Path
    assume_yes: bool = False
    assume_yes_shell: bool = False
    dry_run: bool = False
    allow_shell: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace", self.workspace.expanduser().resolve())

    def resolve_workspace_path(self, path: str) -> Path:
        if not path or "\x00" in path:
            raise SafetyError("Invalid path.")

        raw = Path(path).expanduser()
        candidate = raw if raw.is_absolute() else self.workspace / raw
        resolved = candidate.resolve(strict=False)

        try:
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise SafetyError(f"Path escapes workspace: {path}") from exc

        return resolved

    def confirm_file_write(self, prompt: str) -> bool:
        if self.assume_yes:
            return True
        return _confirm(prompt)

    def confirm_shell(self, prompt: str) -> bool:
        if self.assume_yes_shell:
            return True
        return _confirm(prompt)


def _confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer in {"y", "yes", "д", "да"}
