"""Previewable and rollback-safe slicer profile installation."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from filament_tools.model import (
    BuildArtifact,
    InstallAction,
    InstallOperation,
    InstallPlan,
    Severity,
    ValidationIssue,
)
from filament_tools.platforms import platform_adapter
from filament_tools.validation import validate_profile_data


def _load_profile(path: Path) -> dict:
    source = path.expanduser().resolve()
    if not source.is_file() or source.suffix.casefold() != ".json":
        raise ValueError(f"install input is not a JSON file: {source}")
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid profile JSON {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"install profile must contain a JSON object: {source}")
    return data


def _file_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _backup_path(destination: Path) -> Path:
    base = destination.with_name(f"{destination.name}.bak")
    candidate = base
    index = 2
    while candidate.exists():
        candidate = destination.with_name(f"{destination.name}.bak.{index}")
        index += 1
    return candidate


def plan_install(
    paths: Sequence[Path] = (),
    artifacts: Sequence[BuildArtifact] = (),
    app: str = "bambu",
    app_data_dir: Optional[Path] = None,
    user_folder: Optional[str] = None,
    action: InstallAction = InstallAction.CREATE,
) -> InstallPlan:
    adapter = platform_adapter(app)
    root = adapter.resolve_data_dir(app_data_dir)
    active_folder = adapter.active_user_folder(root, user_folder)
    plan = InstallPlan(app=app, app_data_dir=root, user_folder=active_folder, action=action)
    inputs = [(path.expanduser().resolve(), _load_profile(path)) for path in paths]
    inputs.extend((None, artifact.data) for artifact in artifacts)
    destinations: set[Path] = set()
    for source, data in inputs:
        source_path = source if isinstance(source, Path) else None
        issues = validate_profile_data(data, path=source_path)
        plan.issues.extend(issues)
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        inherits = data.get("inherits")
        is_root = not isinstance(inherits, str) or not inherits.strip()
        destination = adapter.filament_destination(root, active_folder, is_root) / f"{name}.json"
        if destination in destinations:
            plan.issues.append(
                ValidationIssue(
                    severity=Severity.ERROR,
                    code="install.duplicate_destination",
                    message=f"multiple inputs target {destination}",
                    path=str(destination),
                )
            )
        destinations.add(destination)
        destination_exists = destination.is_file()
        sync_exists = destination.with_suffix(".info").exists()
        if action == InstallAction.CREATE and (destination_exists or sync_exists):
            plan.issues.append(
                ValidationIssue(
                    severity=Severity.ERROR,
                    code="install.destination_exists",
                    message="refusing to overwrite an installed profile or sync metadata",
                    path=str(destination),
                )
            )
        elif action in {InstallAction.UPDATE, InstallAction.UNINSTALL}:
            if not destination_exists:
                plan.issues.append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        code="install.destination_missing",
                        message=f"cannot {action.value} a profile that is not installed",
                        path=str(destination),
                    )
                )
            if sync_exists:
                plan.issues.append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        code="install.sync_metadata_exists",
                        message=(
                            f"refusing to {action.value} a profile managed by slicer sync metadata"
                        ),
                        path=str(destination.with_suffix(".info")),
                    )
                )
        plan.operations.append(
            InstallOperation(
                source=source_path,
                destination=destination,
                data=data,
                is_root=is_root,
                action=action,
                backup=_backup_path(destination)
                if destination_exists and action != InstallAction.CREATE
                else None,
                existing_fingerprint=(
                    _file_fingerprint(destination)
                    if destination_exists and action != InstallAction.CREATE
                    else None
                ),
            )
        )
    return plan


def _write_backup(source: Path, backup: Path) -> None:
    try:
        with source.open("rb") as input_handle, backup.open("xb") as output_handle:
            while chunk := input_handle.read(1024 * 1024):
                output_handle.write(chunk)
            output_handle.flush()
            os.fsync(output_handle.fileno())
    except Exception:
        backup.unlink(missing_ok=True)
        raise


def _replace_json(path: Path, data: dict) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=4, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_install_plan(plan: InstallPlan) -> List[Path]:
    if not plan.valid:
        raise ValueError("install plan has validation errors")
    applied: List[InstallOperation] = []
    try:
        for operation in plan.operations:
            operation.destination.parent.mkdir(parents=True, exist_ok=True)
            sync_path = operation.destination.with_suffix(".info")
            if sync_path.exists():
                raise ValueError(
                    f"refusing to {operation.action.value} beside sync metadata: {sync_path}"
                )
            if operation.action == InstallAction.CREATE:
                document = (
                    json.dumps(operation.data, ensure_ascii=False, indent=4, sort_keys=True) + "\n"
                )
                try:
                    with operation.destination.open("x", encoding="utf-8", newline="\n") as handle:
                        handle.write(document)
                except FileExistsError as exc:
                    raise ValueError(
                        f"refusing to overwrite installed profile: {operation.destination}"
                    ) from exc
            else:
                if not operation.destination.is_file():
                    raise ValueError(
                        f"installed profile changed after planning: {operation.destination}"
                    )
                if (
                    not operation.existing_fingerprint
                    or _file_fingerprint(operation.destination) != operation.existing_fingerprint
                ):
                    raise ValueError(
                        f"installed profile changed after planning: {operation.destination}"
                    )
                if operation.backup is None:
                    raise ValueError("maintenance operation has no reviewed backup path")
                _write_backup(operation.destination, operation.backup)
                if operation.action == InstallAction.UPDATE:
                    _replace_json(operation.destination, operation.data)
                else:
                    operation.destination.unlink()
            applied.append(operation)
    except Exception:
        for operation in reversed(applied):
            if operation.action == InstallAction.CREATE:
                operation.destination.unlink(missing_ok=True)
            elif operation.backup and operation.backup.is_file():
                operation.destination.unlink(missing_ok=True)
                os.replace(operation.backup, operation.destination)
        raise
    return [operation.destination for operation in applied]


def plan_lines(plan: InstallPlan) -> Iterable[str]:
    yield f"Application: {plan.app}"
    yield f"Data directory: {plan.app_data_dir}"
    yield f"User folder: {plan.user_folder}"
    yield f"Action: {plan.action.value}"
    for operation in plan.operations:
        kind = "AMS root" if operation.is_root else "sparse child"
        backup = f" (backup: {operation.backup})" if operation.backup else ""
        yield f"{operation.action.value} {kind}: {operation.destination}{backup}"
