"""Draft creation and sparse/root/material-family projections."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from filament_tools.identity import choose_filament_id, material_name_from_profile_name
from filament_tools.model import (
    BuildArtifact,
    OutputMode,
    ProfileDraft,
    ResolvedProfile,
    TargetVariant,
)
from filament_tools.schema import IDENTITY_KEYS, REQUIRED_SPARSE_STRUCTURAL_KEYS


def json_values_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without treating integers and floats as identical."""
    return type(left) is type(right) and left == right


def normalize_compatible_printers(values: Sequence[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        value = value.strip()
        if not value:
            raise ValueError("compatible printer cannot be empty")
        if value not in result:
            result.append(value)
    return result


def desired_values(
    source: ResolvedProfile, draft: ProfileDraft, edits: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    values = dict(source.values)
    for key in draft.removed_keys:
        values.pop(key, None)
    values.update(draft.edits)
    if edits:
        values.update(edits)
    if draft.compatible_printers is not None:
        values["compatible_printers"] = normalize_compatible_printers(draft.compatible_printers)
    return values


def _version(source: ResolvedProfile, base: Optional[ResolvedProfile] = None) -> str:
    version = source.values.get("version")
    if not isinstance(version, str) or not version.strip():
        version = base.values.get("version") if base else None
    if not isinstance(version, str) or not version.strip():
        raise ValueError("source or base must provide a nonempty profile version")
    return version.strip()


def build_sparse(
    draft: ProfileDraft,
    source: ResolvedProfile,
    base: ResolvedProfile,
) -> BuildArtifact:
    if draft.output_mode != OutputMode.SPARSE:
        raise ValueError("draft output_mode must be sparse")
    if (
        not isinstance(base.values.get("filament_id"), str)
        or not base.values["filament_id"].strip()
    ):
        raise ValueError("base profile has no effective filament_id to inherit")
    target = desired_values(source, draft)
    base_behavior = set(base.values) - IDENTITY_KEYS
    target_behavior = set(target) - IDENTITY_KEYS
    missing = sorted(base_behavior - target_behavior)
    if missing:
        shown = ", ".join(missing[:12])
        suffix = f" (+{len(missing) - 12} more)" if len(missing) > 12 else ""
        raise ValueError(
            f"an inheriting profile cannot remove settings supplied by its base: {shown}{suffix}"
        )
    overrides = {
        key: target[key]
        for key in sorted(target_behavior)
        if key not in base.values or not json_values_equal(target[key], base.values[key])
    }
    data = dict(overrides)
    structural: List[str] = []
    for key in REQUIRED_SPARSE_STRUCTURAL_KEYS:
        if key in target:
            data[key] = target[key]
            if key not in overrides:
                structural.append(key)
    data.update(
        {
            "filament_settings_id": [draft.name],
            "from": "User",
            "inherits": base.profile.name,
            "name": draft.name,
            "version": _version(source, base),
        }
    )
    return BuildArtifact(
        name=draft.name,
        data=data,
        mode=OutputMode.SPARSE,
        changed_keys=tuple(overrides),
        structural_keys=tuple(structural),
        source_fingerprint=source.fingerprint,
        base_fingerprint=base.fingerprint,
    )


def build_root(
    draft: ProfileDraft,
    source: ResolvedProfile,
    existing_identities: Optional[Dict[str, tuple[str, str]]] = None,
    variant: Optional[TargetVariant] = None,
    shared_filament_id: Optional[str] = None,
) -> BuildArtifact:
    target = desired_values(source, draft, variant.edits if variant else None)
    name = variant.name if variant else draft.name
    compatibility = variant.compatible_printers if variant else draft.compatible_printers
    if compatibility is not None:
        target["compatible_printers"] = normalize_compatible_printers(compatibility)
    compatibility = target.get("compatible_printers")
    if not isinstance(compatibility, list) or not compatibility:
        raise ValueError("an AMS root requires at least one compatible_printers entry")
    if not all(isinstance(value, str) and value.strip() for value in compatibility):
        raise ValueError("compatible_printers must contain nonempty strings")
    material_name = (draft.material_name or material_name_from_profile_name(name)).strip()
    identities = existing_identities or {}
    filament_id = shared_filament_id or choose_filament_id(
        draft.identity_mode,
        material_name,
        source,
        identities,
        explicit=draft.filament_id,
        user_id=draft.user_id,
    )
    data = {key: value for key, value in target.items() if key not in IDENTITY_KEYS}
    data.update(
        {
            "compatible_printers": normalize_compatible_printers(compatibility),
            "filament_id": filament_id,
            "filament_settings_id": [name],
            "from": "User",
            "name": name,
            "type": "filament",
            "version": _version(source),
        }
    )
    data.pop("inherits", None)
    changed = tuple(
        sorted(
            key
            for key, value in data.items()
            if key not in source.values or not json_values_equal(value, source.values[key])
        )
    )
    return BuildArtifact(
        name=name,
        data=data,
        mode=OutputMode.ROOT,
        changed_keys=changed,
        source_fingerprint=source.fingerprint,
    )


def build_family(
    draft: ProfileDraft,
    source: ResolvedProfile,
    existing_identities: Optional[Dict[str, tuple[str, str]]] = None,
) -> List[BuildArtifact]:
    if not draft.variants:
        raise ValueError("a material family requires at least one target variant")
    material_name = (draft.material_name or material_name_from_profile_name(draft.name)).strip()
    identity = choose_filament_id(
        draft.identity_mode,
        material_name,
        source,
        existing_identities or {},
        explicit=draft.filament_id,
        user_id=draft.user_id,
    )
    return [
        build_root(draft, source, existing_identities, variant, identity)
        for variant in draft.variants
    ]


def write_artifacts(artifacts: Iterable[BuildArtifact], output_directory: str) -> List[str]:
    """Write generated JSON exclusively; never create a missing directory."""
    import json
    from pathlib import Path

    directory = Path(output_directory).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"output directory does not exist: {directory}")
    written: List[str] = []
    try:
        for artifact in artifacts:
            path = directory / f"{artifact.name}.json"
            document = (
                json.dumps(artifact.data, ensure_ascii=False, indent=4, sort_keys=True) + "\n"
            )
            try:
                with path.open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write(document)
            except FileExistsError as exc:
                raise ValueError(f"refusing to overwrite existing output profile: {path}") from exc
            written.append(str(path))
    except Exception:
        for value in written:
            Path(value).unlink(missing_ok=True)
        raise
    return written


def write_artifact(artifact: BuildArtifact, output_path: str) -> str:
    import json
    from pathlib import Path

    path = Path(output_path).expanduser().resolve()
    if path.suffix.casefold() != ".json":
        raise ValueError("output profile must end in .json")
    if path.stem != artifact.name:
        raise ValueError("output filename must exactly match the generated profile name")
    if not path.parent.is_dir():
        raise ValueError(f"output directory does not exist: {path.parent}")
    document = json.dumps(artifact.data, ensure_ascii=False, indent=4, sort_keys=True) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(document)
    except FileExistsError as exc:
        raise ValueError(f"refusing to overwrite existing output profile: {path}") from exc
    return str(path)
