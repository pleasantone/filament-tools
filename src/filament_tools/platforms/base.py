"""Filesystem adapter contract shared by supported slicers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class PlatformAdapter:
    slug: str
    label: str
    config_name: str
    environment_names: tuple[str, ...]

    def data_dir_candidates(self) -> List[Path]:
        raise NotImplementedError

    def resolve_data_dir(self, explicit: Optional[Path] = None) -> Path:
        if explicit is not None:
            root = explicit.expanduser().resolve()
            if not root.is_dir():
                raise ValueError(f"install config directory does not exist: {root}")
            return root
        candidates = self.data_dir_candidates()
        configured = [path for path in candidates if (path / self.config_name).is_file()]
        if len(configured) == 1:
            return configured[0]
        if len(configured) > 1:
            choices = "\n".join(f"  {path}" for path in configured)
            raise ValueError(
                f"multiple {self.label} data directories contain {self.config_name}; "
                f"select one explicitly:\n{choices}"
            )
        existing = [path for path in candidates if path.is_dir()]
        if len(existing) == 1:
            return existing[0]
        if len(existing) > 1:
            choices = "\n".join(f"  {path}" for path in existing)
            raise ValueError(
                f"multiple {self.label} data directories exist; select one explicitly:\n{choices}"
            )
        raise ValueError(f"could not find an installed {self.label} data directory")

    def active_user_folder(self, root: Path, explicit: Optional[str] = None) -> str:
        folder = explicit.strip() if explicit else ""
        config_path = root / self.config_name
        if not folder and config_path.is_file():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"cannot read slicer config {config_path}: {exc}") from exc
            if isinstance(config, dict):
                app_config = config.get("app")
                if isinstance(app_config, dict) and isinstance(
                    app_config.get("preset_folder"), str
                ):
                    folder = app_config["preset_folder"].strip()
                if not folder and isinstance(config.get("preset_folder"), str):
                    folder = config["preset_folder"].strip()
        folder = folder or "default"
        if (
            folder in {".", ".."}
            or Path(folder).name != folder
            or any(separator in folder for separator in ("/", "\\"))
        ):
            raise ValueError(f"invalid user preset folder name: {folder!r}")
        return folder

    def filament_destination(self, root: Path, user_folder: str, is_root: bool) -> Path:
        destination = root / "user" / user_folder / "filament"
        return destination / "base" if is_root else destination
