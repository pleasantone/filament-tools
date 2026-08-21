"""Cross-platform profile discovery, indexing, and deterministic selection."""

from __future__ import annotations

import json
import os
import platform
import shutil
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from filament_tools.model import Profile, ProfileSelector
from filament_tools.selectors import compatible_with

WarningSink = Callable[[str], None]


def _unique_existing(paths: Iterable[Path]) -> List[Path]:
    result: List[Path] = []
    seen: set[Path] = set()
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        if resolved not in seen and resolved.exists():
            seen.add(resolved)
            result.append(resolved)
    return result


def app_label(path: Path) -> str:
    value = str(path).casefold()
    if "orcaslicer" in value or "orca" in value:
        return "OrcaSlicer"
    if "bambustudio" in value or "bambu studio" in value or "bambu" in value:
        return "Bambu Studio"
    return "Other"


def source_kind(path: Path) -> str:
    parts = {part.casefold() for part in path.parts}
    value = str(path).casefold().replace("\\", "/")
    if "user" in parts:
        return "user"
    if "system" in parts:
        return "system"
    if "resources" in parts or "/share/" in value:
        return "bundled"
    return "other"


def _managed_copy_key(profile: Profile) -> Optional[Tuple[str, Tuple[str, ...]]]:
    kind = source_kind(profile.path)
    parts = [part.casefold() for part in profile.path.parts]
    if kind == "system":
        marker = len(parts) - 1 - parts[::-1].index("system")
    elif kind == "bundled":
        marker_name = "profiles" if "profiles" in parts else "resources"
        marker = len(parts) - 1 - parts[::-1].index(marker_name)
    else:
        return None
    relative = tuple(parts[marker + 1 :])
    return (app_label(profile.path).casefold(), relative) if relative else None


def discover_profile_roots(app: str = "all") -> List[Path]:
    """Best-effort profile roots for Bambu Studio, OrcaSlicer, and app bundles."""
    include_bambu = app in {"all", "bambu"}
    include_orca = app in {"all", "orca"}
    home = Path.home()
    candidates: List[Path] = []
    env_map = {
        "BAMBU_STUDIO_CONFIG_DIR": include_bambu,
        "BAMBUSTUDIO_CONFIG_DIR": include_bambu,
        "ORCASLICER_CONFIG_DIR": include_orca,
        "ORCA_SLICER_CONFIG_DIR": include_orca,
    }
    candidates.extend(
        Path(os.environ[name])
        for name, enabled in env_map.items()
        if enabled and os.environ.get(name)
    )
    system = platform.system()
    if system == "Windows":
        appdata = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        if include_bambu:
            candidates.extend(
                (
                    appdata / "BambuStudio",
                    local / "BambuStudio",
                    program_files / "Bambu Studio/resources",
                )
            )
        if include_orca:
            candidates.extend(
                (
                    appdata / "OrcaSlicer",
                    local / "OrcaSlicer",
                    program_files / "OrcaSlicer/resources",
                )
            )
    elif system == "Darwin":
        if include_bambu:
            candidates.extend(
                (
                    home / "Library/Application Support/BambuStudio",
                    Path("/Applications/BambuStudio.app/Contents/Resources"),
                    Path("/Applications/Bambu Studio.app/Contents/Resources"),
                )
            )
        if include_orca:
            candidates.extend(
                (
                    home / "Library/Application Support/OrcaSlicer",
                    Path("/Applications/OrcaSlicer.app/Contents/Resources"),
                )
            )
    else:
        xdg = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        if include_bambu:
            candidates.extend(
                (
                    xdg / "BambuStudio",
                    home / ".var/app/com.bambulab.BambuStudio/config/BambuStudio",
                    Path("/usr/share/BambuStudio"),
                )
            )
        if include_orca:
            candidates.extend(
                (
                    xdg / "OrcaSlicer",
                    home / ".var/app/com.orcaslicer.OrcaSlicer/config/OrcaSlicer",
                    Path("/usr/share/OrcaSlicer"),
                )
            )
    executable_names: List[str] = []
    if include_bambu:
        executable_names.extend(("BambuStudio", "bambu-studio", "bambustudio"))
    if include_orca:
        executable_names.extend(("OrcaSlicer", "orca-slicer", "orcaslicer"))
    for name in executable_names:
        executable = shutil.which(name)
        if executable:
            executable_dir = Path(executable).resolve().parent
            candidates.extend((executable_dir / "data_dir", executable_dir.parent / "data_dir"))
    expanded: List[Path] = []
    for root in candidates:
        expanded.extend(
            (root, root / "user", root / "system", root / "profiles", root / "resources/profiles")
        )
    return _unique_existing(expanded)


class ProfileCatalog:
    """An immutable-on-disk index with explicit refresh semantics."""

    def __init__(self, roots: Sequence[Path], warning_sink: Optional[WarningSink] = None):
        self.roots = _unique_existing(roots)
        self.by_path: Dict[Path, Profile] = {}
        self.by_name: Dict[str, List[Path]] = {}
        self.by_stem: Dict[str, List[Path]] = {}
        self.warning_sink = warning_sink or (lambda message: None)
        self._warned: set[Tuple[Path, Path]] = set()
        self._query_values: Dict[Path, Dict[str, object]] = {}
        self.refresh()

    def refresh(self) -> None:
        self.by_path.clear()
        self.by_name.clear()
        self.by_stem.clear()
        self._query_values.clear()
        seen: set[Path] = set()
        for root in self.roots:
            candidates = (
                [root]
                if root.is_file() and root.suffix.casefold() == ".json"
                else root.rglob("*.json")
            )
            for path in candidates:
                try:
                    resolved = path.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    data = json.loads(resolved.read_text(encoding="utf-8-sig"))
                    if not isinstance(data, dict) or not any(
                        key in data
                        for key in ("name", "type", "inherits", "filament_id", "setting_id")
                    ):
                        continue
                    self._add(Profile(resolved, data))
                except (OSError, json.JSONDecodeError, UnicodeError):
                    continue

    def _add(self, profile: Profile) -> None:
        self.by_path[profile.path] = profile
        self.by_name.setdefault(profile.name.casefold(), []).append(profile.path)
        self.by_stem.setdefault(profile.path.stem.casefold(), []).append(profile.path)

    def load_path(self, path: Path) -> Profile:
        resolved = path.expanduser().resolve()
        if resolved in self.by_path:
            return self.by_path[resolved]
        data = json.loads(resolved.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError(f"{resolved} does not contain a JSON object")
        profile = Profile(resolved, data)
        self._add(profile)
        return profile

    @staticmethod
    def _rank(profile: Profile, query: str) -> tuple[int, str, str]:
        name = profile.name.casefold()
        stem = profile.path.stem.casefold()
        if not query:
            score = 4
        elif name == query:
            score = 0
        elif stem == query:
            score = 1
        elif name.startswith(query) or stem.startswith(query):
            score = 2
        else:
            score = 3
        return score, name, str(profile.path).casefold()

    def search(self, query: str = "", limit: int = 100) -> List[Profile]:
        query = query.strip().casefold()
        scored = []
        for path, profile in self.by_path.items():
            name, stem = profile.name.casefold(), path.stem.casefold()
            if not query:
                score = 4
            elif name == query:
                score = 0
            elif stem == query:
                score = 1
            elif name.startswith(query) or stem.startswith(query):
                score = 2
            elif query in name or query in stem:
                score = 3
            else:
                continue
            scored.append((score, name, str(path).casefold(), profile))
        scored.sort(key=lambda row: row[:3])
        return [row[3] for row in scored[:limit]]

    def known_printer_names(self) -> set[str]:
        """Return exact machine/printer preset names when those profiles are indexed."""
        names: set[str] = set()
        for profile in self.by_path.values():
            profile_type = str(profile.data.get("type", "")).casefold()
            if profile_type in {"machine", "printer"} or "printer_model" in profile.data:
                names.add(profile.name)
        return names

    def visible_profiles(self) -> List[Profile]:
        """Return catalog profiles after managed system/bundled copy preference."""
        return self._prefer_system(list(self.by_path.values()))

    def search_visible(self, query: str = "", limit: int = 100) -> List[Profile]:
        """Search after managed system/bundled copy preference.

        Preference must happen before limiting. Otherwise a bundled copy can
        consume a result slot even though it will subsequently be collapsed.
        """
        results, _ = self.query_visible(query=query, limit=limit)
        return results

    def query_visible(
        self,
        *,
        query: str = "",
        limit: int = 50,
        offset: int = 0,
        profile_type: Optional[str] = None,
        applications: Optional[set[str]] = None,
        source_kinds: Optional[set[str]] = None,
        vendor_or_material: Optional[str] = None,
        machine: Optional[str] = None,
        nozzle: Optional[str] = None,
    ) -> tuple[List[Profile], int]:
        """Return one ranked window from the complete preferred catalog.

        All scope filters are applied before ranking and pagination. Effective
        values are resolved only when a sparse profile does not carry the field
        needed by a filter, or when compatibility filtering is requested.
        """
        from filament_tools.resolution import ProfileResolver

        normalized_query = query.strip().casefold()
        normalized_type = profile_type.strip().casefold() if profile_type else None
        normalized_apps = {value.casefold() for value in applications or set()}
        normalized_sources = {value.casefold() for value in source_kinds or set()}
        material_query = (vendor_or_material or "").strip().casefold()
        resolver = ProfileResolver(self)
        matches: List[Profile] = []

        def effective_values(profile: Profile) -> Dict[str, object]:
            values = self._query_values.get(profile.path)
            if values is None:
                values = resolver.resolve(profile).values
                self._query_values[profile.path] = values
            return values

        for profile in self.visible_profiles():
            if normalized_apps and app_label(profile.path).casefold() not in normalized_apps:
                continue
            if (
                normalized_sources
                and source_kind(profile.path).casefold() not in normalized_sources
            ):
                continue

            resolved = None
            raw_type = profile.data.get("type")
            actual_type = str(raw_type).casefold() if raw_type is not None else ""
            if normalized_type and not actual_type:
                try:
                    resolved_values = effective_values(profile)
                    actual_type = str(resolved_values.get("type", "")).casefold()
                except Exception:
                    actual_type = ""
            if normalized_type and actual_type != normalized_type:
                continue

            searchable = " ".join(
                str(value)
                for value in (
                    profile.name,
                    profile.path.stem,
                    profile.path,
                    profile.data.get("filament_vendor", ""),
                    profile.data.get("filament_type", ""),
                    profile.data.get("material", ""),
                )
            ).casefold()
            if normalized_query and normalized_query not in searchable:
                continue
            if material_query and material_query not in searchable:
                if resolved is None:
                    try:
                        resolved_values = effective_values(profile)
                    except Exception:
                        continue
                effective_material = " ".join(
                    str(resolved_values.get(key, ""))
                    for key in ("filament_vendor", "filament_type", "material")
                ).casefold()
                if material_query not in effective_material:
                    continue

            if machine or nozzle:
                if resolved is None:
                    try:
                        resolved_values = effective_values(profile)
                    except Exception:
                        continue
                if not compatible_with(resolved_values.get("compatible_printers"), machine, nozzle):
                    continue
            matches.append(profile)

        matches.sort(key=lambda profile: self._rank(profile, normalized_query))
        total = len(matches)
        start = max(offset, 0)
        end = start + max(limit, 0)
        return matches[start:end], total

    def _prefer_system(self, profiles: Sequence[Profile]) -> List[Profile]:
        grouped: Dict[Tuple[str, Tuple[str, ...]], List[Profile]] = {}
        result: List[Profile] = []
        for profile in profiles:
            key = _managed_copy_key(profile)
            if key is None:
                result.append(profile)
            else:
                grouped.setdefault(key, []).append(profile)
        for group in grouped.values():
            system_profiles = [
                profile for profile in group if source_kind(profile.path) == "system"
            ]
            bundled_profiles = [
                profile for profile in group if source_kind(profile.path) == "bundled"
            ]
            if len(system_profiles) != 1 or not bundled_profiles:
                result.extend(group)
                continue
            system_profile = system_profiles[0]
            result.append(system_profile)
            for bundled in bundled_profiles:
                warning_key = (system_profile.path, bundled.path)
                if system_profile.data != bundled.data and warning_key not in self._warned:
                    self.warning_sink(
                        "system and bundled profile copies differ; preferring system copy:\n"
                        f"  system: {system_profile.path}\n  bundled: {bundled.path}"
                    )
                    self._warned.add(warning_key)
        return result

    def find(self, spec: str, prefer_dir: Optional[Path] = None) -> Profile:
        candidate_path = Path(os.path.expanduser(spec))
        if candidate_path.exists():
            return self.load_path(candidate_path)
        matches = list(self.by_name.get(spec.casefold(), [])) or list(
            self.by_stem.get(spec.casefold(), [])
        )
        if prefer_dir and matches:
            parent = prefer_dir.resolve()
            local = [path for path in matches if parent in path.parents]
            if len(local) == 1:
                return self.load_path(local[0])
        profiles = (
            self._prefer_system([self.load_path(path) for path in matches])
            if matches
            else self._prefer_system(self.search(spec, 500))
        )
        if len(profiles) == 1:
            return profiles[0]
        if not profiles:
            raise FileNotFoundError(
                f"could not resolve profile {spec!r}; search the catalog or pass an exact JSON path"
            )
        choices = "\n".join(
            f"  [{app_label(profile.path)}/{source_kind(profile.path)}] {profile.name} :: {profile.path}"
            for profile in profiles[:30]
        )
        raise RuntimeError(f"profile query {spec!r} is ambiguous:\n{choices}")

    def select(self, selector: ProfileSelector) -> Profile:
        path = Path(os.path.expanduser(selector.spec))
        if path.exists():
            candidates = [self.load_path(path)]
        else:
            candidates = self._prefer_system(self.search(selector.spec, 500))
        if selector.machine or selector.nozzle:
            from filament_tools.resolution import ProfileResolver

            resolver = ProfileResolver(self)
            candidates = [
                profile
                for profile in candidates
                if compatible_with(
                    resolver.resolve(profile).values.get("compatible_printers"),
                    selector.machine,
                    selector.nozzle,
                )
            ]
        if not candidates:
            raise FileNotFoundError(
                f"no profile matching {selector.spec!r} for machine={selector.machine or '*'} "
                f"nozzle={selector.nozzle or '*'}"
            )
        query = selector.spec.casefold().strip()

        def rank(profile: Profile) -> tuple:
            name, stem = profile.name.casefold(), profile.path.stem.casefold()
            value = (
                0
                if name == query
                else 1
                if stem == query
                else 2
                if name.startswith(query) or stem.startswith(query)
                else 3
            )
            instantiated = str(profile.data.get("instantiation", "")).casefold() == "true"
            return value, 0 if instantiated else 1, name, str(profile.path).casefold()

        candidates.sort(key=rank)
        best_rank = rank(candidates[0])[:2]
        best = [profile for profile in candidates if rank(profile)[:2] == best_rank]
        if len(best) == 1:
            return best[0]
        choices = "\n".join(
            f"  [{app_label(profile.path)}/{source_kind(profile.path)}] {profile.name} :: {profile.path}"
            for profile in best
        )
        raise RuntimeError(
            f"profile query {selector.spec!r} is ambiguous after filtering:\n{choices}"
        )
