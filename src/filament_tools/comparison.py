"""Comparison collection independent of terminal, CSV, and HTML rendering."""

from __future__ import annotations

import re
from typing import List, Optional, Sequence, Set

from filament_tools.catalog import ProfileCatalog
from filament_tools.model import (
    ComparisonCell,
    ComparisonReport,
    OverrideReport,
    OverrideRow,
    Profile,
    ResolvedProfile,
)
from filament_tools.resolution import ProfileResolver
from filament_tools.schema import META_KEYS, group_for_key
from filament_tools.transforms import json_values_equal


def compare_profiles(
    profiles: Sequence[Profile],
    resolver: ProfileResolver,
    labels: Optional[Sequence[str]] = None,
    mode: str = "effective",
    include_meta: bool = False,
    key_pattern: Optional[str] = None,
    groups: Optional[Set[str]] = None,
    only_different: bool = False,
) -> ComparisonReport:
    if mode not in {"effective", "raw"}:
        raise ValueError("comparison mode must be effective or raw")
    if len(profiles) < 2:
        raise ValueError("comparison requires at least two profiles")
    resolved = [resolver.resolve(profile) for profile in profiles]
    pattern = re.compile(key_pattern) if key_pattern else None
    keys: set[str] = set()
    for profile, effective in zip(profiles, resolved, strict=True):
        keys.update(profile.data if mode == "raw" else effective.values)
    if not include_meta:
        keys -= META_KEYS
    rows = []
    for key in sorted(keys):
        if pattern and not pattern.search(key):
            continue
        group = group_for_key(key)
        if groups and group not in groups:
            continue
        cells = []
        for profile, effective in zip(profiles, resolved, strict=True):
            values = profile.data if mode == "raw" else effective.values
            cells.append(
                ComparisonCell(
                    value=values.get(key),
                    source=profile.name
                    if mode == "raw" and key in values
                    else effective.sources.get(key),
                    explicit=key in profile.data,
                    present=key in values,
                )
            )
        if only_different and all(
            cells[0].present == cell.present and json_values_equal(cells[0].value, cell.value)
            for cell in cells[1:]
        ):
            continue
        from filament_tools.model import ComparisonRow

        rows.append(ComparisonRow(key=key, group=group, cells=tuple(cells)))
    return ComparisonReport(
        labels=tuple(labels or [profile.name for profile in profiles]),
        profiles=tuple(resolved),
        rows=tuple(rows),
        mode=mode,
    )


def compare_overrides(
    profiles: Sequence[Profile],
    labels: Sequence[str],
    catalog: ProfileCatalog,
    include_meta: bool = False,
    key_pattern: Optional[str] = None,
    groups: Optional[Set[str]] = None,
    only_different: bool = False,
) -> List[OverrideReport]:
    resolver = ProfileResolver(catalog)
    pattern = re.compile(key_pattern) if key_pattern else None
    reports: List[OverrideReport] = []
    for profile, label in zip(profiles, labels, strict=True):
        parent: Optional[ResolvedProfile] = None
        parent_error: Optional[str] = None
        if not profile.inherits:
            parent_status = "NO PARENT"
        else:
            try:
                parent = resolver.resolve(catalog.find(profile.inherits, profile.path.parent))
                parent_status = f"{parent.profile.name} ({' -> '.join(parent.chain)})"
            except Exception as exc:  # Report remains useful when the parent is broken.
                parent_error = str(exc)
                parent_status = f"UNAVAILABLE: {exc}"
        keys = set(profile.data)
        if not include_meta:
            keys -= META_KEYS
        rows = []
        for key in sorted(keys):
            if pattern and not pattern.search(key):
                continue
            if groups and group_for_key(key) not in groups:
                continue
            if parent_error:
                parent_value, source, difference = None, None, "unavailable"
            elif parent is None:
                parent_value, source, difference = None, None, "no parent"
            elif key not in parent.values:
                parent_value, source, difference = None, None, "added"
            else:
                parent_value = parent.values[key]
                source = parent.sources.get(key)
                difference = (
                    "same" if json_values_equal(profile.data[key], parent_value) else "changed"
                )
            if only_different and difference == "same":
                continue
            rows.append(
                OverrideRow(
                    key=key,
                    explicit_value=profile.data[key],
                    parent_value=parent_value,
                    difference=difference,
                    parent_source=source,
                )
            )
        reports.append(
            OverrideReport(
                profile=profile,
                label=label,
                parent_status=parent_status,
                rows=tuple(rows),
                parent_error=parent_error,
            )
        )
    return reports
