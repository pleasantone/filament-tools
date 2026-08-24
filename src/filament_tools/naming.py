"""User-facing profile, project, and output destination suggestions."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def suggest_profile_name(source_name: str, existing_names: Iterable[str] = ()) -> str:
    source = source_name.strip()
    material, separator, target = source.partition(" @")
    material_base = f"{material} Custom" if separator else f"{source} Custom"

    def candidate(index: int | None = None) -> str:
        numbered = f"{material_base} {index}" if index is not None else material_base
        return f"{numbered}{separator}{target}"

    base = candidate()
    existing = {name.strip().casefold() for name in existing_names}
    if base.casefold() not in existing:
        return base
    index = 2
    while candidate(index).casefold() in existing:
        index += 1
    return candidate(index)


def suggest_project_name(profile_name: str) -> str:
    return profile_name.split(" @", 1)[0].strip()


def default_document_directory() -> Path:
    documents = Path.home() / "Documents"
    return documents if documents.is_dir() else Path.home()


def suggest_project_path(project_name: str, directory: Path) -> Path:
    return directory.expanduser().resolve() / f"{project_name.strip()}.ftdraft"


def suggest_output_path(profile_name: str, directory: Path, *, family: bool = False) -> Path:
    root = directory.expanduser().resolve()
    return root if family else root / f"{profile_name.strip()}.json"
