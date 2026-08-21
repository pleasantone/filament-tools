"""Previewable and rollback-safe slicer profile installation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from filament_tools.model import (
    BuildArtifact,
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


def plan_install(
    paths: Sequence[Path] = (),
    artifacts: Sequence[BuildArtifact] = (),
    app: str = "bambu",
    app_data_dir: Optional[Path] = None,
    user_folder: Optional[str] = None,
) -> InstallPlan:
    adapter = platform_adapter(app)
    root = adapter.resolve_data_dir(app_data_dir)
    active_folder = adapter.active_user_folder(root, user_folder)
    plan = InstallPlan(app=app, app_data_dir=root, user_folder=active_folder)
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
        if destination.exists() or destination.with_suffix(".info").exists():
            plan.issues.append(
                ValidationIssue(
                    severity=Severity.ERROR,
                    code="install.destination_exists",
                    message="refusing to overwrite an installed profile or sync metadata",
                    path=str(destination),
                )
            )
        plan.operations.append(
            InstallOperation(
                source=source_path, destination=destination, data=data, is_root=is_root
            )
        )
    return plan


def apply_install_plan(plan: InstallPlan) -> List[Path]:
    if not plan.valid:
        raise ValueError("install plan has validation errors")
    created: List[Path] = []
    try:
        for operation in plan.operations:
            operation.destination.parent.mkdir(parents=True, exist_ok=True)
            sync_path = operation.destination.with_suffix(".info")
            if sync_path.exists():
                raise ValueError(
                    f"refusing to install beside sync metadata created after planning: {sync_path}"
                )
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
            created.append(operation.destination)
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return created


def plan_lines(plan: InstallPlan) -> Iterable[str]:
    yield f"Application: {plan.app}"
    yield f"Data directory: {plan.app_data_dir}"
    yield f"User folder: {plan.user_folder}"
    for operation in plan.operations:
        kind = "AMS root" if operation.is_root else "sparse child"
        yield f"{kind}: {operation.destination}"
