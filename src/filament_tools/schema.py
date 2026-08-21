"""Bambu/Orca profile key policy and semantic grouping."""

from __future__ import annotations

from typing import Dict

META_KEYS = {
    "type",
    "name",
    "inherits",
    "from",
    "setting_id",
    "filament_id",
    "instantiation",
    "description",
    "version",
}

CLOUD_KEYS = {"setting_id", "base_id", "sync_info", "updated_time", "user_id"}
IDENTITY_KEYS = (
    META_KEYS
    | CLOUD_KEYS
    | {
        "filament_settings_id",
        "print_settings_id",
        "printer_settings_id",
    }
)
REQUIRED_SPARSE_STRUCTURAL_KEYS = ("filament_extruder_variant",)

GROUP_LABELS: Dict[str, str] = {
    "identity": "Identity / metadata",
    "compatibility": "Printer compatibility",
    "temperature": "Temperature",
    "flow": "Flow / volumetric speed",
    "cooling": "Cooling",
    "retraction": "Retraction / wipe",
    "ams": "AMS / drying",
    "dimensional": "Dimensional compensation",
    "material": "Material properties",
    "gcode": "G-code",
    "other": "Other",
}

SETTING_METADATA: Dict[str, Dict[str, str]] = {
    "nozzle_temperature": {
        "name": "Nozzle temperature",
        "unit": "°C",
        "description": "Target nozzle temperature for this filament.",
        "editor": "temperature",
    },
    "filament_max_volumetric_speed": {
        "name": "Maximum volumetric speed",
        "unit": "mm³/s",
        "description": "Upper extrusion-flow limit used by the slicer.",
        "editor": "number",
    },
    "fan_max_speed": {
        "name": "Maximum fan speed",
        "unit": "%",
        "description": "Maximum part-cooling fan speed.",
        "editor": "number",
    },
}


def setting_metadata(key: str) -> Dict[str, str]:
    """Return presentation hints without changing the raw profile key."""
    metadata = SETTING_METADATA.get(key, {})
    return {
        "name": metadata.get("name", key.replace("_", " ").strip().title()),
        "unit": metadata.get("unit", ""),
        "description": metadata.get("description", ""),
        "editor": metadata.get("editor", "json"),
    }


def group_for_key(key: str) -> str:
    folded = key.casefold()
    if folded in META_KEYS or folded.startswith(("filament_id", "setting_id")):
        return "identity"
    if "compatible" in folded or folded.startswith(("printer", "nozzle_diameter")):
        return "compatibility"
    if any(token in folded for token in ("temperature", "_temp", "temp_")):
        return "temperature"
    if any(token in folded for token in ("volumetric", "flow", "pressure_advance", "k_value")):
        return "flow"
    if any(token in folded for token in ("cool", "fan")):
        return "cooling"
    if any(token in folded for token in ("retract", "wipe", "z_hop", "deretraction")):
        return "retraction"
    if any(token in folded for token in ("ams", "drying", "dry_", "spool", "tray")):
        return "ams"
    if (
        folded.startswith(("counter_", "hole_"))
        or folded in {"diameter_limit", "circle_compensation_speed"}
        or "shrink" in folded
    ):
        return "dimensional"
    if any(token in folded for token in ("filament", "material", "density", "cost", "vendor")):
        return "material"
    if "gcode" in folded or "g-code" in folded:
        return "gcode"
    return "other"
