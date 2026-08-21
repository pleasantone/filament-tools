"""Structured validation for source, generated, and installable profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from filament_tools.model import (
    BuildArtifact,
    OutputMode,
    Severity,
    ValidationIssue,
    validate_profile_name,
)
from filament_tools.schema import CLOUD_KEYS, IDENTITY_KEYS
from filament_tools.transforms import json_values_equal


def validate_profile_data(
    data: Dict[str, Any],
    path: Optional[Path] = None,
    known_printers: Optional[Set[str]] = None,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    path_value = str(path) if path else None

    def add(severity: Severity, code: str, message: str, key: Optional[str] = None) -> None:
        issues.append(
            ValidationIssue(
                severity=severity,
                code=code,
                message=message,
                key=key,
                path=path_value,
            )
        )

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        add(
            Severity.ERROR, "profile.name_missing", "profile name must be a nonempty string", "name"
        )
    else:
        try:
            validate_profile_name(name)
        except ValueError as exc:
            add(Severity.ERROR, "profile.unsafe_name", str(exc), "name")
        if path and path.suffix.casefold() == ".json" and path.stem != name:
            add(
                Severity.ERROR,
                "profile.filename_mismatch",
                "JSON name must exactly match the filename stem",
                "name",
            )
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        add(
            Severity.ERROR,
            "profile.version_missing",
            "profile version must be a nonempty string",
            "version",
        )
    if data.get("from") != "User":
        add(
            Severity.ERROR, "profile.not_user", "generated profile must declare from='User'", "from"
        )
    settings_id = data.get("filament_settings_id")
    if isinstance(name, str) and not (
        isinstance(settings_id, list) and settings_id and settings_id[0] == name
    ):
        add(
            Severity.ERROR,
            "profile.settings_id_mismatch",
            "filament_settings_id[0] must equal the profile name",
            "filament_settings_id",
        )
    for key in sorted(CLOUD_KEYS & data.keys()):
        add(
            Severity.ERROR,
            "profile.cloud_metadata",
            "cloud/.info metadata must be assigned by the slicer",
            key,
        )
    inherits = data.get("inherits")
    is_root = not isinstance(inherits, str) or not inherits.strip()
    if is_root:
        filament_id = data.get("filament_id")
        if not isinstance(filament_id, str) or not filament_id.strip():
            add(
                Severity.ERROR,
                "root.filament_id_missing",
                "AMS root requires filament_id",
                "filament_id",
            )
        compatibility = data.get("compatible_printers")
        if not (
            isinstance(compatibility, list)
            and compatibility
            and all(isinstance(item, str) and item.strip() for item in compatibility)
        ):
            add(
                Severity.ERROR,
                "root.compatibility_missing",
                "AMS root requires nonempty compatible_printers strings",
                "compatible_printers",
            )
        elif known_printers is not None:
            for printer in compatibility:
                if printer not in known_printers:
                    add(
                        Severity.WARNING,
                        "compatibility.unknown_printer",
                        f"printer preset was not found in the current catalog: {printer}",
                        "compatible_printers",
                    )
    elif "filament_id" in data:
        add(
            Severity.WARNING,
            "sparse.explicit_filament_id",
            "a sparse child should normally inherit filament_id from its base",
            "filament_id",
        )
    return issues


def validate_artifact(
    artifact: BuildArtifact, known_printers: Optional[Set[str]] = None
) -> List[ValidationIssue]:
    return validate_profile_data(artifact.data, known_printers=known_printers)


def validate_sparse_roundtrip(
    artifact: BuildArtifact,
    base_values: Dict[str, Any],
    desired: Dict[str, Any],
) -> List[ValidationIssue]:
    if artifact.mode != OutputMode.SPARSE:
        return []
    reconstructed = dict(base_values)
    reconstructed.update({key: value for key, value in artifact.data.items() if key != "inherits"})
    issues: List[ValidationIssue] = []
    keys = (set(base_values) | set(desired)) - IDENTITY_KEYS
    for key in sorted(keys):
        if key not in desired:
            issues.append(
                ValidationIssue(
                    severity=Severity.ERROR,
                    code="roundtrip.unrepresentable_removal",
                    message="desired state removes a key supplied by the base",
                    key=key,
                )
            )
        elif key not in reconstructed or not json_values_equal(reconstructed[key], desired[key]):
            issues.append(
                ValidationIssue(
                    severity=Severity.ERROR,
                    code="roundtrip.value_mismatch",
                    message="generated sparse profile does not reconstruct the desired effective value",
                    key=key,
                )
            )
    return issues


def has_errors(issues: Iterable[ValidationIssue]) -> bool:
    return any(issue.severity == Severity.ERROR for issue in issues)
