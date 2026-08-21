"""Portable ProfileDraft project persistence."""

from __future__ import annotations

import json
from pathlib import Path

from filament_tools.model import CompositionRecipe, ProfileDraft

PROJECT_FORMAT = "filament-tools-draft-v1"
COMPOSITION_PROJECT_FORMAT = "filament-tools-composition-v1"


def save_project(path: Path, draft: ProfileDraft) -> Path:
    output = path.expanduser().resolve()
    if output.suffix.casefold() not in {".json", ".ftdraft"}:
        raise ValueError("draft project filename must end in .json or .ftdraft")
    if not output.parent.is_dir():
        raise ValueError(f"project directory does not exist: {output.parent}")
    document = {
        "format": PROJECT_FORMAT,
        "draft": draft.model_dump(mode="json"),
    }
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return output


def load_project(path: Path) -> ProfileDraft:
    source = path.expanduser().resolve()
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("format") != PROJECT_FORMAT:
        raise ValueError(f"unsupported or missing project format in {source}")
    return ProfileDraft.model_validate(data.get("draft"))


def save_composition_project(path: Path, recipe: CompositionRecipe) -> Path:
    output = path.expanduser().resolve()
    if output.suffix.casefold() not in {".json", ".ftdraft"}:
        raise ValueError("composition project filename must end in .json or .ftdraft")
    if not output.parent.is_dir():
        raise ValueError(f"project directory does not exist: {output.parent}")
    document = {
        "format": COMPOSITION_PROJECT_FORMAT,
        "recipe": recipe.model_dump(mode="json"),
    }
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return output


def load_composition_project(path: Path) -> CompositionRecipe:
    source = path.expanduser().resolve()
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("format") != COMPOSITION_PROJECT_FORMAT:
        raise ValueError(f"unsupported or missing composition project format in {source}")
    return CompositionRecipe.model_validate(data.get("recipe"))
