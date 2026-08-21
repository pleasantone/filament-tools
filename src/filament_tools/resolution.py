"""Inheritance resolution with complete per-setting provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

from filament_tools.catalog import ProfileCatalog
from filament_tools.model import Profile, ResolvedProfile
from filament_tools.vectors import NIL_SENTINEL, merge_nullable_vector


def fingerprint(values: dict) -> str:
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ProfileResolver:
    def __init__(self, catalog: ProfileCatalog):
        self.catalog = catalog
        self._cache: Dict[Path, ResolvedProfile] = {}

    def clear(self) -> None:
        self._cache.clear()

    def resolve(self, profile: Profile, stack: Optional[List[Path]] = None) -> ResolvedProfile:
        if profile.path in self._cache:
            return self._cache[profile.path]
        stack = [] if stack is None else stack
        if profile.path in stack:
            chain = " -> ".join(str(path) for path in stack + [profile.path])
            raise RuntimeError(f"inheritance cycle: {chain}")
        values: dict = {}
        sources: Dict[str, str] = {}
        source_paths: Dict[str, Path] = {}
        element_sources: Dict[str, tuple[str, ...]] = {}
        element_source_paths: Dict[str, tuple[Path, ...]] = {}
        chain: List[str] = []
        if profile.inherits:
            parent = self.catalog.find(profile.inherits, prefer_dir=profile.path.parent)
            resolved_parent = self.resolve(parent, stack + [profile.path])
            values.update(resolved_parent.values)
            sources.update(resolved_parent.sources)
            source_paths.update(resolved_parent.source_paths)
            element_sources.update(resolved_parent.element_sources)
            element_source_paths.update(resolved_parent.element_source_paths)
            chain.extend(resolved_parent.chain)
        chain.append(profile.name)
        for key, value in profile.data.items():
            if key == "inherits":
                continue
            parent_value = values.get(key)
            if isinstance(value, list) and isinstance(parent_value, list) and NIL_SENTINEL in value:
                parent_element_sources = element_sources.get(
                    key, tuple(sources.get(key, profile.name) for _ in parent_value)
                )
                parent_element_paths = element_source_paths.get(
                    key, tuple(source_paths.get(key, profile.path) for _ in parent_value)
                )
                merged, merged_sources, merged_paths = merge_nullable_vector(
                    value,
                    parent_value,
                    profile.name,
                    profile.path,
                    parent_element_sources,
                    parent_element_paths,
                )
                values[key] = merged
                element_sources[key] = merged_sources
                element_source_paths[key] = merged_paths
                sources[key] = " / ".join(dict.fromkeys(merged_sources))
                source_paths[key] = profile.path
                continue
            values[key] = value
            sources[key] = profile.name
            source_paths[key] = profile.path
            if isinstance(value, list):
                element_sources[key] = tuple(profile.name for _ in value)
                element_source_paths[key] = tuple(profile.path for _ in value)
            else:
                element_sources.pop(key, None)
                element_source_paths.pop(key, None)
        result = ResolvedProfile(
            profile=profile,
            values=values,
            sources=sources,
            source_paths=source_paths,
            element_sources=element_sources,
            element_source_paths=element_source_paths,
            chain=tuple(chain),
            fingerprint=fingerprint(values),
        )
        self._cache[profile.path] = result
        return result

    def resolve_selector(self, selector: str) -> ResolvedProfile:
        from filament_tools.selectors import parse_selector

        return self.resolve(self.catalog.select(parse_selector(selector)))
