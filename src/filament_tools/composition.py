"""Materialize deterministic multi-source composition recipes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

from filament_tools.model import (
    ChoiceKind,
    CompositionRecipe,
    OutputMode,
    ProfileDraft,
    ResolvedProfile,
    Severity,
    ValidationIssue,
)
from filament_tools.resolution import ProfileResolver
from filament_tools.schema import IDENTITY_KEYS
from filament_tools.transforms import desired_values

LOCKED_COMPOSITION_KEYS = IDENTITY_KEYS | {"compatible_printers"}


@dataclass(frozen=True)
class MaterializedComposition:
    recipe: CompositionRecipe
    draft: ProfileDraft
    values: Dict[str, Any]
    selection_sources: Dict[str, str]
    value_sources: Dict[str, str]
    value_source_paths: Dict[str, str]
    element_sources: Dict[str, Tuple[str, ...]]
    issues: Tuple[ValidationIssue, ...]


def materialize_recipe(
    recipe: CompositionRecipe,
    resolver: ProfileResolver,
) -> MaterializedComposition:
    """Resolve donor choices and compile them into the normal build draft."""
    starting = resolver.resolve_selector(recipe.starting_source)
    allowed = {recipe.starting_source, *recipe.reference_sources}
    fingerprint_selectors = set(allowed)
    if recipe.output_mode == OutputMode.SPARSE:
        fingerprint_selectors.add(recipe.sparse_parent or recipe.starting_source)
    resolved: Dict[str, ResolvedProfile] = {recipe.starting_source: starting}
    issues: list[ValidationIssue] = []

    for selector in fingerprint_selectors:
        profile = (
            starting if selector == recipe.starting_source else resolver.resolve_selector(selector)
        )
        resolved[selector] = profile
        expected = recipe.fingerprints.get(selector)
        if expected and expected != profile.fingerprint:
            issues.append(
                ValidationIssue(
                    severity=Severity.WARNING,
                    code="composition.source_drift",
                    message=f"source effective settings changed: {profile.profile.name}",
                    path=str(profile.profile.path),
                )
            )

    edits: Dict[str, Any] = {}
    removed: list[str] = []
    selection_sources = {
        key: starting.profile.name for key in starting.values if key not in LOCKED_COMPOSITION_KEYS
    }
    value_sources = dict(starting.sources)
    value_source_paths = {key: str(path) for key, path in starting.source_paths.items()}
    element_sources = dict(starting.element_sources)

    for key, choice in recipe.selections.items():
        if key in LOCKED_COMPOSITION_KEYS:
            raise ValueError(f"{key} is managed by output controls and cannot be composed")
        if choice.kind == ChoiceKind.REMOVE:
            removed.append(key)
            selection_sources.pop(key, None)
            value_sources.pop(key, None)
            value_source_paths.pop(key, None)
            element_sources.pop(key, None)
            continue
        if choice.kind == ChoiceKind.CUSTOM:
            edits[key] = choice.value
            selection_sources[key] = "Custom value"
            value_sources[key] = "Custom value"
            value_source_paths.pop(key, None)
            element_sources.pop(key, None)
            continue
        selector = choice.source or ""
        if selector not in allowed:
            raise ValueError(f"setting {key} selects a profile that is not in this recipe")
        donor = resolved[selector]
        if key not in donor.values:
            raise ValueError(f"setting {key} is not available from {donor.profile.name}")
        edits[key] = donor.values[key]
        selection_sources[key] = donor.profile.name
        value_sources[key] = donor.sources.get(key, donor.profile.name)
        if key in donor.source_paths:
            value_source_paths[key] = str(donor.source_paths[key])
        else:
            value_source_paths.pop(key, None)
        if key in donor.element_sources:
            element_sources[key] = donor.element_sources[key]
        else:
            element_sources.pop(key, None)

    sparse_parent = recipe.sparse_parent or recipe.starting_source
    draft = ProfileDraft(
        name=recipe.name,
        source=recipe.starting_source,
        base=sparse_parent if recipe.output_mode == OutputMode.SPARSE else None,
        output_mode=recipe.output_mode,
        edits=edits,
        removed_keys=removed,
        compatible_printers=recipe.compatible_printers,
        identity_mode=recipe.identity_mode,
        filament_id=recipe.filament_id,
        material_name=recipe.material_name,
        user_id=recipe.user_id,
        variants=recipe.variants,
        source_fingerprint=recipe.fingerprints.get(recipe.starting_source),
        base_fingerprint=recipe.fingerprints.get(sparse_parent),
    )
    values = desired_values(starting, draft)
    return MaterializedComposition(
        recipe=recipe,
        draft=draft,
        values=values,
        selection_sources=selection_sources,
        value_sources=value_sources,
        value_source_paths=value_source_paths,
        element_sources=element_sources,
        issues=tuple(issues),
    )
