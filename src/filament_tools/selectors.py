"""Profile selector parsing and effective compatibility matching."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from filament_tools.model import ProfileSelector


def parse_selector(text: str) -> ProfileSelector:
    """Parse PROFILE[;machine=...][;nozzle=...][;label=...]."""
    parts = [part.strip() for part in text.split(";")]
    if not parts or not parts[0]:
        raise ValueError("selector profile name/path cannot be empty")
    options: Dict[str, str] = {}
    for part in parts[1:]:
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"invalid selector option {part!r}; expected key=value")
        key, value = (item.strip() for item in part.split("=", 1))
        key = key.casefold()
        if key not in {"machine", "nozzle", "label"}:
            raise ValueError(f"unknown selector option {key!r}")
        if key in options:
            raise ValueError(f"duplicate selector option {key!r}")
        if not value:
            raise ValueError(f"selector option {key!r} cannot be empty")
        options[key] = value
    return ProfileSelector(
        spec=parts[0],
        machine=options.get("machine"),
        nozzle=options.get("nozzle"),
        label=options.get("label"),
    )


def normalize_nozzle(nozzle: str) -> str:
    value = nozzle.strip().lower().replace("mm", "").strip()
    try:
        return f"{float(value):g}"
    except ValueError:
        return value


def normalize_machine(machine: str) -> str:
    value = machine.casefold().strip()
    return {"x1c": "x1 carbon"}.get(value, value)


def compatible_with(
    compatibility: Any,
    machine: Optional[str] = None,
    nozzle: Optional[str] = None,
) -> bool:
    """Match a selector against an effective compatible_printers value."""
    if not machine and not nozzle:
        return True
    if not isinstance(compatibility, list) or not compatibility:
        return False
    machine_query = normalize_machine(machine) if machine else None
    nozzle_query = normalize_nozzle(nozzle) if nozzle else None
    for item in compatibility:
        if not isinstance(item, str):
            continue
        folded = item.casefold()
        if machine_query and machine_query not in folded:
            continue
        if nozzle_query:
            match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:mm\s*)?nozzle", folded)
            if not match or normalize_nozzle(match.group(1)) != nozzle_query:
                continue
        return True
    return False
