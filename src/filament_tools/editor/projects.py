"""Portable ProfileDraft project persistence."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filament_tools.model import CompositionRecipe, ProfileDraft

PROJECT_FORMAT = "filament-tools-draft-v1"
COMPOSITION_PROJECT_FORMAT = "filament-tools-composition-v2"
LEGACY_COMPOSITION_PROJECT_FORMAT = "filament-tools-composition-v1"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_output(path: Path, label: str) -> Path:
    output = path.expanduser().resolve()
    if output.suffix.casefold() not in {".json", ".ftdraft"}:
        raise ValueError(f"{label} project filename must end in .json or .ftdraft")
    if not output.parent.is_dir():
        raise ValueError(f"project directory does not exist: {output.parent}")
    return output


def _write_document(path: Path, document: dict[str, Any], *, replace: bool) -> None:
    if not replace:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_project(path: Path, draft: ProfileDraft, *, replace: bool = False) -> Path:
    output = _validate_output(path, "draft")
    document = {
        "format": PROJECT_FORMAT,
        "draft": draft.model_dump(mode="json"),
    }
    _write_document(output, document, replace=replace)
    return output


def load_project(path: Path) -> ProfileDraft:
    source = path.expanduser().resolve()
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("format") != PROJECT_FORMAT:
        raise ValueError(f"unsupported or missing project format in {source}")
    return ProfileDraft.model_validate(data.get("draft"))


def save_composition_project(
    path: Path,
    recipe: CompositionRecipe,
    *,
    replace: bool = False,
    project_name: str | None = None,
) -> Path:
    output = _validate_output(path, "composition")
    created_at = _timestamp()
    if replace and output.is_file():
        try:
            existing = _load_composition_document(output)
            created_at = str(existing["project"].get("created_at") or created_at)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            pass
    modified_at = _timestamp()
    metadata_name = (project_name or recipe.name).strip()
    if not metadata_name:
        raise ValueError("project name cannot be empty")
    document = {
        "format": COMPOSITION_PROJECT_FORMAT,
        "project": {
            "name": metadata_name,
            "created_at": created_at,
            "modified_at": modified_at,
        },
        "recipe": recipe.model_dump(mode="json"),
    }
    _write_document(output, document, replace=replace)
    return output


def _load_composition_document(path: Path) -> dict[str, Any]:
    source = path.expanduser().resolve()
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("format") not in {
        COMPOSITION_PROJECT_FORMAT,
        LEGACY_COMPOSITION_PROJECT_FORMAT,
    }:
        raise ValueError(f"unsupported or missing composition project format in {source}")
    if data.get("format") == LEGACY_COMPOSITION_PROJECT_FORMAT:
        recipe = CompositionRecipe.model_validate(data.get("recipe"))
        return {
            **data,
            "project": {"name": recipe.name, "created_at": None, "modified_at": None},
        }
    project = data.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("name"), str):
        raise ValueError(f"missing composition project metadata in {source}")
    return data


def load_composition_project_document(path: Path) -> tuple[CompositionRecipe, dict[str, Any]]:
    data = _load_composition_document(path)
    return CompositionRecipe.model_validate(data.get("recipe")), dict(data["project"])


def load_composition_project(path: Path) -> CompositionRecipe:
    recipe, _ = load_composition_project_document(path)
    return recipe
