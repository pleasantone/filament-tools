#!/usr/bin/env python3
"""
profile_diff.py

Multi-way diff for Bambu Studio / OrcaSlicer filament profiles.

Highlights
----------
- Compare any number of filament JSON profiles.
- Resolve `inherits` recursively and compare effective values.
- Auto-discover common Bambu Studio and OrcaSlicer profile locations on
  macOS, Windows, and Linux.
- Search profile names case-insensitively with --find-profile.
- Select per-profile machine/nozzle combinations with repeated --select.
- Show where effective values came from with --show-source.
- Filter parameters by semantic group with --group.
- Output terminal table, CSV, or a grouped self-contained HTML viewer.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import platform
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

META_KEYS_DEFAULT = {
    "type", "name", "inherits", "from", "setting_id", "filament_id",
    "instantiation", "description", "version",
}


@dataclass
class Profile:
    path: Path
    data: Dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.data.get("name") or self.path.stem)

    @property
    def inherits(self) -> Optional[str]:
        value = self.data.get("inherits")
        return value.strip() if isinstance(value, str) and value.strip() else None


@dataclass
class EffectiveProfile:
    profile: Profile
    values: Dict[str, Any]
    sources: Dict[str, str]
    chain: List[str]


@dataclass(frozen=True)
class ProfileSelector:
    spec: str
    machine: Optional[str] = None
    nozzle: Optional[str] = None
    label: Optional[str] = None


GROUP_LABELS = {
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


def group_for_key(key: str) -> str:
    """Return the stable semantic group slug for a profile parameter."""
    folded = key.casefold()
    if folded in META_KEYS_DEFAULT or folded.startswith(("filament_id", "setting_id")):
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


def _unique_existing(paths: Iterable[Path]) -> List[Path]:
    out: List[Path] = []
    seen: set[Path] = set()
    for p in paths:
        try:
            rp = p.expanduser().resolve()
        except Exception:
            continue
        if rp in seen or not rp.exists():
            continue
        seen.add(rp)
        out.append(rp)
    return out


def app_label_for_path(path: Path) -> str:
    s = str(path).lower()
    if "orcaslicer" in s or "orca" in s:
        return "OrcaSlicer"
    if "bambustudio" in s or "bambu studio" in s or "bambu" in s:
        return "Bambu Studio"
    return "Other"


def source_kind_for_path(path: Path) -> str:
    parts = {x.lower() for x in path.parts}
    s = str(path).lower().replace("\\", "/")
    if "user" in parts:
        return "user"
    if "system" in parts:
        return "system"
    if "resources" in parts or "/share/" in s:
        return "bundled"
    return "other"


def _possible_executable_dirs(names: Sequence[str]) -> List[Path]:
    out: List[Path] = []
    for name in names:
        found = shutil.which(name)
        if found:
            out.append(Path(found).resolve().parent)
    return _unique_existing(out)


def discover_profile_roots(include_bambu: bool = True, include_orca: bool = True) -> List[Path]:
    """Best-effort discovery of user and bundled profile trees."""
    system = platform.system()
    home = Path.home()
    candidates: List[Path] = []

    # Explicit overrides for unusual/portable installations.
    env_map = {
        "BAMBU_STUDIO_CONFIG_DIR": include_bambu,
        "BAMBUSTUDIO_CONFIG_DIR": include_bambu,
        "ORCASLICER_CONFIG_DIR": include_orca,
        "ORCA_SLICER_CONFIG_DIR": include_orca,
    }
    for var, enabled in env_map.items():
        if enabled and os.environ.get(var):
            candidates.append(Path(os.environ[var]))

    if system == "Windows":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        pfx86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))

        if include_bambu:
            candidates += [
                appdata / "BambuStudio",
                local / "BambuStudio",
                pf / "Bambu Studio" / "resources",
                pf / "BambuStudio" / "resources",
                pfx86 / "Bambu Studio" / "resources",
                local / "Programs" / "Bambu Studio" / "resources",
                local / "Programs" / "BambuStudio" / "resources",
            ]
        if include_orca:
            candidates += [
                appdata / "OrcaSlicer",
                local / "OrcaSlicer",
                pf / "OrcaSlicer" / "resources",
                pfx86 / "OrcaSlicer" / "resources",
                local / "Programs" / "OrcaSlicer" / "resources",
            ]

    elif system == "Darwin":
        if include_bambu:
            candidates += [
                home / "Library" / "Application Support" / "BambuStudio",
                Path("/Applications/BambuStudio.app/Contents/Resources"),
                Path("/Applications/Bambu Studio.app/Contents/Resources"),
                home / "Applications/BambuStudio.app/Contents/Resources",
                home / "Applications/Bambu Studio.app/Contents/Resources",
            ]
        if include_orca:
            candidates += [
                home / "Library" / "Application Support" / "OrcaSlicer",
                Path("/Applications/OrcaSlicer.app/Contents/Resources"),
                home / "Applications/OrcaSlicer.app/Contents/Resources",
            ]

    else:  # Linux and other Unix-like systems
        xdg = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        if include_bambu:
            candidates += [
                xdg / "BambuStudio",
                home / ".var" / "app" / "com.bambulab.BambuStudio" / "config" / "BambuStudio",
                Path("/usr/share/BambuStudio"),
                Path("/usr/local/share/BambuStudio"),
                home / ".local" / "share" / "BambuStudio",
            ]
        if include_orca:
            candidates += [
                xdg / "OrcaSlicer",
                home / ".var" / "app" / "com.orcaslicer.OrcaSlicer" / "config" / "OrcaSlicer",
                Path("/usr/share/OrcaSlicer"),
                Path("/usr/local/share/OrcaSlicer"),
                home / ".local" / "share" / "OrcaSlicer",
            ]

    names: List[str] = []
    if include_bambu:
        names += ["BambuStudio", "bambu-studio", "bambustudio"]
    if include_orca:
        names += ["OrcaSlicer", "orca-slicer", "orcaslicer"]
    for exe_dir in _possible_executable_dirs(names):
        candidates += [exe_dir / "data_dir", exe_dir.parent / "data_dir"]

    # Include likely descendants explicitly so we don't depend on one packaging layout.
    expanded: List[Path] = []
    for root in candidates:
        expanded += [
            root,
            root / "user",
            root / "system",
            root / "profiles",
            root / "resources",
            root / "resources" / "profiles",
            root / "profiles" / "BBL",
            root / "resources" / "profiles" / "BBL",
            root / "profiles" / "BBL" / "filament",
            root / "resources" / "profiles" / "BBL" / "filament",
        ]
    return _unique_existing(expanded)


class ProfileIndex:
    def __init__(self, search_dirs: Sequence[Path]):
        self.by_name: Dict[str, List[Path]] = {}
        self.by_stem: Dict[str, List[Path]] = {}
        self.by_path: Dict[Path, Profile] = {}
        self.search_dirs = _unique_existing(search_dirs)
        self._index()

    def _index(self) -> None:
        seen: set[Path] = set()
        for root in self.search_dirs:
            candidates = [root] if root.is_file() and root.suffix.lower() == ".json" else root.rglob("*.json")
            for path in candidates:
                try:
                    rp = path.resolve()
                    if rp in seen:
                        continue
                    seen.add(rp)
                    with rp.open("r", encoding="utf-8-sig") as f:
                        data = json.load(f)
                    if not isinstance(data, dict):
                        continue
                    # Only index objects that look at least vaguely like presets.
                    if not any(k in data for k in ("name", "type", "inherits", "filament_id", "setting_id")):
                        continue
                    prof = Profile(rp, data)
                    self.by_path[rp] = prof
                    self.by_name.setdefault(prof.name.casefold(), []).append(rp)
                    self.by_stem.setdefault(rp.stem.casefold(), []).append(rp)
                except Exception:
                    continue

    def load_path(self, path: Path) -> Profile:
        rp = path.expanduser().resolve()
        if rp in self.by_path:
            return self.by_path[rp]
        with rp.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"{rp} does not contain a JSON object")
        prof = Profile(rp, data)
        self.by_path[rp] = prof
        self.by_name.setdefault(prof.name.casefold(), []).append(rp)
        self.by_stem.setdefault(rp.stem.casefold(), []).append(rp)
        return prof

    def search_names(self, query: str, limit: int = 100) -> List[Profile]:
        q = query.strip().casefold()
        scored: List[Tuple[int, str, Path]] = []
        for rp, prof in self.by_path.items():
            name, stem = prof.name.casefold(), rp.stem.casefold()
            if name == q:
                score = 0
            elif stem == q:
                score = 1
            elif name.startswith(q) or stem.startswith(q):
                score = 2
            elif q in name or q in stem:
                score = 3
            else:
                continue
            scored.append((score, prof.name.casefold(), rp))
        scored.sort(key=lambda x: (x[0], x[1], str(x[2]).casefold()))
        return [self.by_path[p] for _, _, p in scored[:limit]]

    def _effective_value(self, profile: Profile, key: str, seen: Optional[set[Path]] = None) -> Any:
        """Resolve one key through the inheritance chain."""
        if key in profile.data:
            return profile.data[key]
        if not profile.inherits:
            return None
        if seen is None:
            seen = set()
        if profile.path in seen:
            return None
        seen = set(seen)
        seen.add(profile.path)
        try:
            parent = self.find(profile.inherits, prefer_dir=profile.path.parent)
        except Exception:
            return None
        return self._effective_value(parent, key, seen)

    @staticmethod
    def _normalize_nozzle(nozzle: str) -> str:
        s = nozzle.strip().lower().replace("mm", "").strip()
        try:
            return f"{float(s):g}"
        except ValueError:
            return s

    def compatible_with(self, profile: Profile, machine: Optional[str], nozzle: Optional[str]) -> bool:
        """Match against effective compatible_printers."""
        if not machine and not nozzle:
            return True
        compat = self._effective_value(profile, "compatible_printers")
        if not isinstance(compat, list) or not compat:
            return False
        machine_q = machine.casefold().strip() if machine else None
        nozzle_q = self._normalize_nozzle(nozzle) if nozzle else None

        for item in compat:
            if not isinstance(item, str):
                continue
            folded = item.casefold()
            if machine_q and machine_q not in folded:
                continue
            if nozzle_q:
                m = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:mm\s*)?nozzle", folded)
                if not m or self._normalize_nozzle(m.group(1)) != nozzle_q:
                    continue
            return True
        return False

    def find_filtered(
        self,
        spec: str,
        machine: Optional[str] = None,
        nozzle: Optional[str] = None,
    ) -> Profile:
        """Resolve a profile query after machine/nozzle compatibility filtering."""
        p = Path(os.path.expanduser(spec))
        if p.exists():
            prof = self.load_path(p)
            if (machine or nozzle) and not self.compatible_with(prof, machine, nozzle):
                raise RuntimeError(
                    f"{prof.name!r} is not compatible with "
                    f"machine={machine or '*'} nozzle={nozzle or '*'}"
                )
            return prof

        candidates = self.search_names(spec, limit=500)
        if machine or nozzle:
            candidates = [p for p in candidates if self.compatible_with(p, machine, nozzle)]
        if not candidates:
            raise RuntimeError(
                f"No profile matching {spec!r} for "
                f"machine={machine or '*'} nozzle={nozzle or '*'}"
            )

        q = spec.casefold().strip()
        def rank(prof: Profile):
            name = prof.name.casefold()
            stem = prof.path.stem.casefold()
            if name == q:
                r = 0
            elif stem == q:
                r = 1
            elif name.startswith(q) or stem.startswith(q):
                r = 2
            else:
                r = 3
            instantiated = str(prof.data.get("instantiation", "")).lower() == "true"
            return (r, 0 if instantiated else 1, prof.name.casefold(), str(prof.path).casefold())

        candidates.sort(key=rank)
        best_key = rank(candidates[0])[:2]
        best = [p for p in candidates if rank(p)[:2] == best_key]
        if len(best) == 1:
            return best[0]

        choices = "\n".join(
            f"  [{app_label_for_path(x.path)}/{source_kind_for_path(x.path)}] "
            f"{x.name} :: {x.path}"
            for x in best[:30]
        )
        raise RuntimeError(
            f"Profile query {spec!r} is ambiguous after filtering "
            f"machine={machine or '*'} nozzle={nozzle or '*'}:\n{choices}"
        )

    def find(self, spec: str, prefer_dir: Optional[Path] = None) -> Profile:
        p = Path(os.path.expanduser(spec))
        if p.exists():
            return self.load_path(p)

        key = spec.casefold()
        matches = list(self.by_name.get(key, [])) or list(self.by_stem.get(key, []))

        if len(matches) == 1:
            return self.load_path(matches[0])

        if prefer_dir and matches:
            pref = prefer_dir.resolve()
            preferred = [m for m in matches if pref in m.parents]
            if len(preferred) == 1:
                return self.load_path(preferred[0])

        if not matches:
            fuzzy = self.search_names(spec)
            if len(fuzzy) == 1:
                return fuzzy[0]
            if fuzzy:
                choices = "\n".join(
                    f"  [{app_label_for_path(x.path)}/{source_kind_for_path(x.path)}] {x.name}\n    {x.path}"
                    for x in fuzzy[:25]
                )
                raise RuntimeError(f"Profile query {spec!r} is ambiguous:\n{choices}")
            raise FileNotFoundError(
                f"Could not resolve profile {spec!r}. Try --find-profile {spec!r}, "
                "add --search-dir, or pass the JSON path."
            )

        choices = "\n".join(
            f"  [{app_label_for_path(m)}/{source_kind_for_path(m)}] {self.load_path(m).name}\n    {m}"
            for m in matches
        )
        raise RuntimeError(f"Profile name {spec!r} is ambiguous:\n{choices}")


def canonical(v: Any) -> str:
    if v is None:
        return "∅"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def resolve_effective(profile: Profile, index: ProfileIndex, cache: Dict[Path, EffectiveProfile], stack: Optional[List[Path]] = None) -> EffectiveProfile:
    if profile.path in cache:
        return cache[profile.path]
    stack = [] if stack is None else stack
    if profile.path in stack:
        raise RuntimeError("Inheritance cycle: " + " -> ".join(str(p) for p in stack + [profile.path]))

    values: Dict[str, Any] = {}
    sources: Dict[str, str] = {}
    chain: List[str] = []

    if profile.inherits:
        parent = index.find(profile.inherits, prefer_dir=profile.path.parent)
        eff = resolve_effective(parent, index, cache, stack + [profile.path])
        values.update(eff.values)
        sources.update(eff.sources)
        chain.extend(eff.chain)

    chain.append(profile.name)
    for key, value in profile.data.items():
        if key == "inherits":
            continue
        values[key] = value
        sources[key] = profile.name

    result = EffectiveProfile(profile, values, sources, chain)
    cache[profile.path] = result
    return result


def collect_rows(
    profiles: Sequence[Profile],
    effective: Sequence[EffectiveProfile],
    mode: str,
    include_meta: bool,
    key_pattern: Optional[re.Pattern[str]],
    only_different: bool,
    groups: Optional[set[str]] = None,
):
    all_keys: set[str] = set()
    for p, e in zip(profiles, effective):
        all_keys.update(p.data.keys() if mode == "raw" else e.values.keys())
    if not include_meta:
        all_keys -= META_KEYS_DEFAULT

    rows = []
    for key in sorted(all_keys):
        if key_pattern and not key_pattern.search(key):
            continue
        if groups and group_for_key(key) not in groups:
            continue
        vals, srcs = [], []
        for p, e in zip(profiles, effective):
            d = p.data if mode == "raw" else e.values
            if key in d:
                vals.append(canonical(d[key]))
                srcs.append(p.name if mode == "raw" else e.sources.get(key, ""))
            else:
                vals.append("∅")
                srcs.append("")
        if only_different and len(set(vals)) <= 1:
            continue
        rows.append((key, vals, srcs))
    return rows


def shorten(s: str, width: int) -> str:
    s = s.replace("\n", "\\n")
    return s if len(s) <= width else s[: max(1, width - 1)] + "…"


def terminal_table(names: Sequence[str], rows, show_source: bool, width: int) -> str:
    colw = max(12, width)
    keyw = min(max([len(r[0]) for r in rows] + [9]), 42)
    widths = [keyw] + [colw] * len(names)

    def line(parts):
        return " | ".join(shorten(str(x), w).ljust(w) for x, w in zip(parts, widths))

    out = [line(["parameter", *names]), "-+-".join("-" * w for w in widths)]
    for key, vals, srcs in rows:
        out.append(line([key, *vals]))
        if show_source:
            out.append(line(["source", *[(f"↳ {s}" if s else "") for s in srcs]]))
    return "\n".join(out)


def write_csv(path: Path, names: Sequence[str], rows, show_source: bool) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        header = ["parameter"]
        for n in names:
            header.append(n)
            if show_source:
                header.append(f"{n} source")
        w.writerow(header)
        for key, vals, srcs in rows:
            row = [key]
            for v, s in zip(vals, srcs):
                row.append(v)
                if show_source:
                    row.append(s)
            w.writerow(row)


def write_html(path: Path, names: Sequence[str], rows, effective: Sequence[EffectiveProfile], mode: str, show_source: bool) -> None:
    def esc(x: Any) -> str:
        return html.escape(str(x))

    rows_by_group = {slug: [] for slug in GROUP_LABELS}
    for row in rows:
        rows_by_group[group_for_key(row[0])].append(row)

    sections = []
    for slug, label in GROUP_LABELS.items():
        group_rows = rows_by_group[slug]
        if not group_rows:
            continue
        body = []
        for key, vals, srcs in group_rows:
            cells = [f'<th scope="row" class="parameter">{esc(key)}</th>']
            for position, (value, source, profile) in enumerate(zip(vals, srcs, effective)):
                if key in profile.profile.data:
                    status = "explicit"
                elif mode == "effective" and value != "∅":
                    status = "inherited"
                else:
                    status = "missing"
                difference = " different" if position and value != vals[0] else ""
                source_html = f'<div class="source">from {esc(source)}</div>' if source else ""
                cells.append(
                    f'<td class="value {status}{difference}" data-value="{html.escape(value, quote=True)}">'
                    f'<code>{esc(value)}</code>{source_html}</td>'
                )
            body.append(
                f'<tr class="parameter-row" data-parameter="{html.escape(key.casefold(), quote=True)}">'
                + "".join(cells)
                + "</tr>"
            )
        sections.append(
            f'<section class="group" data-group="{slug}"><details open>'
            f'<summary>{esc(label)} <span>{len(group_rows)} parameter'
            f'{"s" if len(group_rows) != 1 else ""}</span></summary>'
            '<div class="table-wrap"><table><thead><tr><th>Parameter</th>'
            + "".join(f'<th>{esc(name)}</th>' for name in names)
            + "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table></div></details></section>"
        )

    cards = []
    for name, profile in zip(names, effective):
        cards.append(
            '<article class="profile-card">'
            f'<h3>{esc(name)}</h3><div class="profile-name">{esc(profile.profile.name)}</div>'
            f'<div class="chain">{esc(" → ".join(profile.chain))}</div>'
            f'<div class="path">{esc(profile.profile.path)}</div></article>'
        )

    source_state = "sources-visible" if show_source else "sources-hidden"
    source_checked = " checked" if show_source else ""
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bambu/Orca profile diff</title>
<style>
:root {{ color-scheme: light dark; --background: #f7f8fa; --panel: #fff; --text: #18202b; --muted: #667085; --border: #d8dee8; --accent: #0b6bcb; --different: #fff3cd; --explicit: #e8f4ff; --sticky: #f2f5f9; }}
@media (prefers-color-scheme: dark) {{ :root {{ --background: #11151b; --panel: #1a2029; --text: #edf2f7; --muted: #a6b0bf; --border: #3a4554; --accent: #69b3ff; --different: #4b3b12; --explicit: #143757; --sticky: #222a35; }} }}
* {{ box-sizing: border-box; }}
body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 0; background: var(--background); color: var(--text); }}
main {{ max-width: 1800px; margin: 0 auto; padding: 28px; }}
h1 {{ margin: 0 0 6px; }} .summary {{ color: var(--muted); margin: 0 0 20px; }}
.profiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin-bottom: 18px; }}
.profile-card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px; min-width: 0; }}
.profile-card h3 {{ margin: 0 0 5px; font-size: 16px; }} .profile-name {{ font-size: 13px; }}
.chain, .path {{ color: var(--muted); font-size: 12px; margin-top: 6px; overflow-wrap: anywhere; }}
.controls {{ position: sticky; top: 0; z-index: 20; display: flex; flex-wrap: wrap; gap: 14px; align-items: center; padding: 12px; margin-bottom: 14px; background: color-mix(in srgb, var(--background) 92%, transparent); backdrop-filter: blur(8px); border: 1px solid var(--border); border-radius: 10px; }}
.controls input[type="search"] {{ flex: 1 1 260px; min-width: 180px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 7px; background: var(--panel); color: var(--text); }}
.group {{ margin: 0 0 14px; }} .group[hidden] {{ display: none; }}
details {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px; overflow: clip; }}
summary {{ cursor: pointer; padding: 13px 16px; font-weight: 700; }} summary span {{ color: var(--muted); font-size: 12px; font-weight: 500; margin-left: 6px; }}
.table-wrap {{ max-height: 72vh; overflow: auto; border-top: 1px solid var(--border); }}
table {{ border-collapse: separate; border-spacing: 0; width: 100%; table-layout: fixed; }}
th, td {{ border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); padding: 9px; vertical-align: top; overflow-wrap: anywhere; }}
thead th {{ position: sticky; top: 0; z-index: 3; background: var(--sticky); text-align: left; }}
th:first-child, td:first-child {{ position: sticky; left: 0; z-index: 2; width: min(340px, 26vw); background: var(--sticky); }}
thead th:first-child {{ z-index: 4; }} tbody tr:last-child > * {{ border-bottom: 0; }} tr > *:last-child {{ border-right: 0; }}
code {{ white-space: pre-wrap; font-size: 12px; }} .source {{ color: var(--muted); font-size: 11px; margin-top: 5px; }}
.sources-hidden .source {{ display: none; }} .value.explicit {{ background: var(--explicit); }} .value.different {{ box-shadow: inset 4px 0 var(--accent); background: var(--different); }}
.legend {{ color: var(--muted); font-size: 12px; }} .legend b {{ color: var(--text); }}
@media (max-width: 720px) {{ main {{ padding: 14px; }} th:first-child, td:first-child {{ width: 180px; }} }}
</style></head>
<body class="{source_state}"><main>
<h1>Bambu/Orca filament profile diff</h1>
<p class="summary">Mode: <b>{esc(mode)}</b> · {len(rows)} parameters · {len(names)} profiles</p>
<section class="profiles">{"".join(cards)}</section>
<div class="controls"><input id="parameter-search" type="search" placeholder="Filter parameters or values…" aria-label="Filter parameters or values">
<label><input id="toggle-sources" type="checkbox"{source_checked}> Show source profiles</label>
<span class="legend"><b>Blue tint</b> explicit · <b>left bar</b> differs from first profile</span></div>
<div id="groups">{"".join(sections)}</div>
</main><script>
const search = document.getElementById('parameter-search');
const sourceToggle = document.getElementById('toggle-sources');
function filterRows() {{
  const query = search.value.trim().toLocaleLowerCase();
  document.querySelectorAll('.group').forEach(group => {{
    let visible = 0;
    group.querySelectorAll('.parameter-row').forEach(row => {{
      const match = !query || row.textContent.toLocaleLowerCase().includes(query);
      row.hidden = !match;
      if (match) visible += 1;
    }});
    group.hidden = visible === 0;
  }});
}}
search.addEventListener('input', filterRows);
sourceToggle.addEventListener('change', () => {{
  document.body.classList.toggle('sources-visible', sourceToggle.checked);
  document.body.classList.toggle('sources-hidden', !sourceToggle.checked);
}});
</script></body></html>"""
    path.write_text(doc, encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Multi-way diff for Bambu Studio / OrcaSlicer filament profiles.")
    ap.add_argument(
        "--select",
        action="append",
        default=[],
        metavar="SELECTOR",
        help=(
            "Per-profile selection: 'PROFILE;machine=H2C;nozzle=0.4;label=Fine'. "
            "Options are optional; repeat for each comparison column."
        ),
    )
    ap.add_argument("--search-dir", action="append", default=[], help="Additional directory to index recursively. Repeatable.")
    ap.add_argument("--find-profile", metavar="TEXT", help="Search discovered profile names/filenames and exit.")
    ap.add_argument("--list-search-paths", action="store_true", help="Print auto-discovered search paths and exit.")
    ap.add_argument("--no-auto-discover", action="store_true", help="Disable standard Bambu Studio / OrcaSlicer path discovery.")
    ap.add_argument("--app", choices=["both", "bambu", "orca"], default="both", help="Limit automatic discovery (default: both).")
    ap.add_argument("--mode", choices=["effective", "raw"], default="effective")
    ap.add_argument("--only-different", action="store_true")
    ap.add_argument("--include-meta", action="store_true")
    ap.add_argument("--keys", help="Regex applied to parameter names.")
    ap.add_argument(
        "--group",
        action="append",
        choices=tuple(GROUP_LABELS),
        help="Include one semantic parameter group. Repeatable.",
    )
    ap.add_argument("--list-groups", action="store_true", help="List semantic parameter groups and exit.")
    ap.add_argument("--show-source", action="store_true")
    ap.add_argument("--width", type=int, default=28)
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--html", type=Path)
    ap.add_argument("--list-chain", action="store_true")
    args = ap.parse_args(argv)

    if args.list_groups:
        for slug, label in GROUP_LABELS.items():
            print(f"{slug:14} {label}")
        return 0

    try:
        selectors = [parse_selector(text) for text in args.select]
    except ValueError as e:
        ap.error(str(e))

    if not args.find_profile and len(selectors) < 2:
        ap.error(
            "provide at least two --select values, or use --find-profile"
        )

    search_dirs = [Path(os.path.expanduser(x)) for x in args.search_dir]
    for spec in (selector.spec for selector in selectors):
        p = Path(os.path.expanduser(spec))
        if p.exists():
            search_dirs.append(p.resolve().parent)

    if not args.no_auto_discover:
        search_dirs += discover_profile_roots(args.app in ("both", "bambu"), args.app in ("both", "orca"))

    cwd = Path.cwd()
    for p in (
        cwd / "resources" / "profiles",
        cwd / "BambuStudio" / "resources" / "profiles",
        cwd / "OrcaSlicer" / "resources" / "profiles",
    ):
        if p.exists():
            search_dirs.append(p)

    search_dirs = _unique_existing(search_dirs)

    if args.list_search_paths:
        if not search_dirs:
            print("No profile search paths found.")
        else:
            for p in search_dirs:
                print(f"[{app_label_for_path(p)}/{source_kind_for_path(p)}] {p}")
        return 0

    index = ProfileIndex(search_dirs)

    if args.find_profile:
        matches = index.search_names(args.find_profile)
        if not matches:
            print(f"No profiles matched {args.find_profile!r}.", file=sys.stderr)
            return 1
        for prof in matches:
            compat = index._effective_value(prof, "compatible_printers")
            compat_text = ""
            if isinstance(compat, list) and compat:
                compat_text = "\n  compatible: " + "; ".join(str(x) for x in compat)
            print(
                f"[{app_label_for_path(prof.path)}/{source_kind_for_path(prof.path)}] "
                f"{prof.name}\n  {prof.path}{compat_text}"
            )
        return 0

    try:
        profiles: List[Profile] = []
        selection_labels: List[str] = []

        for selector in selectors:
            machine = selector.machine
            nozzle = selector.nozzle
            prof = index.find_filtered(selector.spec, machine=machine, nozzle=nozzle)
            profiles.append(prof)
            if selector.label:
                label = selector.label
            else:
                qualifiers = []
                if machine:
                    qualifiers.append(machine)
                if nozzle is not None:
                    qualifiers.append(f"{nozzle} mm")
                suffix = f" [{' / '.join(qualifiers)}]" if qualifiers else ""
                label = prof.name + suffix
            selection_labels.append(label)

        # Remove exact duplicate files while preserving order.
        unique_profiles: List[Profile] = []
        unique_labels: List[str] = []
        seen_paths: set[Path] = set()
        for prof, label in zip(profiles, selection_labels):
            if prof.path in seen_paths:
                continue
            seen_paths.add(prof.path)
            unique_profiles.append(prof)
            unique_labels.append(label)
        profiles = unique_profiles
        selection_labels = unique_labels

        if len(profiles) < 2:
            raise RuntimeError("Selection resolved to fewer than two distinct profiles.")

        cache: Dict[Path, EffectiveProfile] = {}
        effective = [resolve_effective(p, index, cache) for p in profiles]
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.list_chain:
        for e in effective:
            print(f"{e.profile.name}: {' -> '.join(e.chain)}")
        print()

    try:
        pattern = re.compile(args.keys) if args.keys else None
    except re.error as e:
        print(f"error: invalid --keys regular expression: {e}", file=sys.stderr)
        return 2
    selected_groups = set(args.group) if args.group else None
    rows = collect_rows(
        profiles,
        effective,
        args.mode,
        args.include_meta,
        pattern,
        args.only_different,
        selected_groups,
    )
    names = selection_labels
    print(terminal_table(names, rows, args.show_source, args.width))

    if args.csv:
        write_csv(args.csv, names, rows, args.show_source)
        print(f"\nWrote CSV: {args.csv}")
    if args.html:
        write_html(args.html, names, rows, effective, args.mode, args.show_source)
        print(f"Wrote HTML: {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
