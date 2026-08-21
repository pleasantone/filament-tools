"""Bambu-compatible user material identity generation and reuse."""

from __future__ import annotations

import hashlib
import time
from typing import Dict, Iterable, Optional, Tuple

from filament_tools.model import IdentityMode, Profile, ResolvedProfile


def material_name_from_profile_name(profile_name: str) -> str:
    """Return the material-family portion used by Bambu's custom material UI."""
    return profile_name.split(" @", 1)[0].strip()


def bambu_filament_id(material_name: str, user_id: Optional[str] = None) -> str:
    """Generate Bambu's initial P + seven-hex user filament candidate."""
    name = material_name.strip()
    if not name:
        raise ValueError("material name cannot be empty")
    digest_input = f"{name}@{user_id}" if user_id and user_id.strip() else name
    return "P" + hashlib.md5(digest_input.encode("utf-8")).hexdigest()[:7]  # noqa: S324


def existing_material_identities(profiles: Iterable[Profile]) -> Dict[str, Tuple[str, str]]:
    """Map filament ID to (material name, profile name) for explicit root IDs."""
    result: Dict[str, Tuple[str, str]] = {}
    for profile in profiles:
        filament_id = profile.data.get("filament_id")
        if profile.inherits or not isinstance(filament_id, str) or not filament_id.strip():
            continue
        material = material_name_from_profile_name(profile.name)
        result.setdefault(filament_id.strip(), (material, profile.name))
    return result


def choose_filament_id(
    mode: IdentityMode,
    material_name: str,
    source: ResolvedProfile,
    existing: Dict[str, Tuple[str, str]],
    explicit: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    """Resolve explicit/reuse/generate identity without inventing cloud IDs."""
    if mode == IdentityMode.EXPLICIT:
        value = explicit.strip() if explicit else ""
        if not value:
            raise ValueError("explicit identity mode requires filament_id")
        collision = existing.get(value)
        if collision and collision[0].casefold() != material_name.casefold():
            raise ValueError(f"filament_id {value!r} already belongs to material {collision[0]!r}")
        return value

    source_id = source.values.get("filament_id")
    if mode in {IdentityMode.INHERIT, IdentityMode.REUSE}:
        if isinstance(source_id, str) and source_id.strip():
            return source_id.strip()
        for filament_id, (known_material, _) in existing.items():
            if known_material.casefold() == material_name.casefold():
                return filament_id
        if mode == IdentityMode.INHERIT:
            raise ValueError("source has no effective filament_id to retain")

    candidate = bambu_filament_id(material_name, user_id)
    collision = existing.get(candidate)
    if collision is None or collision[0].casefold() == material_name.casefold():
        return candidate
    # Bambu Studio retries with current time when the eight-character candidate
    # belongs to another material. A nanosecond suffix avoids tight-loop repeats.
    for attempt in range(100):
        suffix = f"{material_name}{time.time_ns()}{attempt}"
        candidate = "P" + hashlib.md5(suffix.encode("utf-8")).hexdigest()[:7]  # noqa: S324
        if candidate not in existing:
            return candidate
    raise RuntimeError("could not generate a collision-free filament_id")
