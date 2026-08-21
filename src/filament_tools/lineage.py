"""Scoped and catalog-wide inheritance graph construction."""

from __future__ import annotations

from collections import Counter, deque
from typing import Any, Dict, List

from filament_tools.catalog import ProfileCatalog, app_label, source_kind
from filament_tools.model import Profile


def _node(profile: Profile) -> Dict[str, Any]:
    return {
        "id": str(profile.path),
        "name": profile.name,
        "path": str(profile.path),
        "parent_name": profile.inherits,
        "app": app_label(profile.path),
        "source_kind": source_kind(profile.path),
        "raw_override_count": len(profile.data),
        "status": "root" if not profile.inherits else "ok",
        "error": None,
    }


def lineage_context(
    catalog: ProfileCatalog, profile: Profile, *, child_limit: int = 50
) -> Dict[str, Any]:
    """Return ancestors and immediate dependents without building the forest."""
    visible = catalog.visible_profiles()
    child_counts = Counter(
        candidate.inherits.casefold() for candidate in visible if candidate.inherits
    )
    ancestors: List[Dict[str, Any]] = []
    active = {profile.path}
    current = profile
    problem: str | None = None
    while current.inherits:
        try:
            parent = catalog.find(current.inherits, prefer_dir=current.path.parent)
        except Exception as exc:
            problem = str(exc)
            break
        if parent.path in active:
            problem = f"inheritance cycle reaches {parent.name}"
            break
        active.add(parent.path)
        ancestors.append(_node(parent))
        current = parent
    ancestors.reverse()

    children: List[Dict[str, Any]] = []
    for candidate in visible:
        if not candidate.inherits or candidate.inherits.casefold() != profile.name.casefold():
            continue
        try:
            parent = catalog.find(candidate.inherits, prefer_dir=candidate.path.parent)
        except Exception:
            continue
        if parent.path != profile.path:
            continue
        child = _node(candidate)
        child["child_count"] = child_counts[candidate.name.casefold()]
        children.append(child)
    children.sort(key=lambda item: (item["name"].casefold(), item["path"]))
    total_children = len(children)
    selected = _node(profile)
    if problem:
        selected["status"] = "broken"
        selected["error"] = problem
    return {
        "selected": selected,
        "ancestors": ancestors,
        "children": children[:child_limit],
        "children_total": total_children,
        "children_truncated": total_children > child_limit,
    }


def lineage_descendants(
    catalog: ProfileCatalog, profile: Profile, *, limit: int = 500
) -> Dict[str, Any]:
    """Return a bounded descendant graph after an explicit user request."""
    visible = catalog.visible_profiles()
    candidates_by_parent: Dict[str, List[Profile]] = {}
    for candidate in visible:
        if candidate.inherits:
            candidates_by_parent.setdefault(candidate.inherits.casefold(), []).append(candidate)

    nodes = {str(profile.path): _node(profile)}
    edges: List[Dict[str, Any]] = []
    queue = deque([profile])
    seen = {profile.path}
    truncated = False
    while queue:
        parent = queue.popleft()
        for child in candidates_by_parent.get(parent.name.casefold(), []):
            try:
                resolved_parent = catalog.find(child.inherits or "", prefer_dir=child.path.parent)
            except Exception:
                continue
            if resolved_parent.path != parent.path or child.path in seen:
                continue
            if len(nodes) >= limit:
                truncated = True
                queue.clear()
                break
            seen.add(child.path)
            nodes[str(child.path)] = _node(child)
            edges.append({"parent": str(parent.path), "child": str(child.path)})
            queue.append(child)
    return {
        "nodes": sorted(nodes.values(), key=lambda item: (item["name"].casefold(), item["path"])),
        "edges": edges,
        "truncated": truncated,
        "limit": limit,
    }


def inheritance_graph(catalog: ProfileCatalog) -> Dict[str, List[Dict[str, Any]]]:
    """Return flat nodes and parent-to-child edges with broken links preserved."""
    profiles = catalog.visible_profiles()
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    for profile in profiles:
        node = _node(profile)
        nodes[str(profile.path)] = node

    for profile in profiles:
        if not profile.inherits:
            continue
        child_id = str(profile.path)
        try:
            parent = catalog.find(profile.inherits, prefer_dir=profile.path.parent)
            parent_id = str(parent.path)
            if parent_id not in nodes:
                nodes[parent_id] = _node(parent)
            edges.append({"parent": parent_id, "child": child_id})
        except Exception as exc:
            nodes[child_id]["status"] = "broken"
            nodes[child_id]["error"] = str(exc)

    for profile in profiles:
        try:
            catalog_profile = catalog.by_path.get(profile.path, profile)
            from filament_tools.resolution import ProfileResolver

            ProfileResolver(catalog).resolve(catalog_profile)
        except Exception as exc:
            node = nodes[str(profile.path)]
            node["status"] = "broken"
            node["error"] = str(exc)

    return {
        "nodes": sorted(nodes.values(), key=lambda node: (node["name"].casefold(), node["path"])),
        "edges": sorted(edges, key=lambda edge: (edge["parent"], edge["child"])),
    }
