"""Nullable per-extruder vector semantics used by slicer sparse profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Sequence, Tuple

NIL_SENTINEL = "nil"


def merge_nullable_vector(
    child: Sequence[Any],
    parent: Sequence[Any],
    child_source: str,
    child_path: Path,
    parent_sources: Sequence[str],
    parent_paths: Sequence[Path],
) -> Tuple[List[Any], Tuple[str, ...], Tuple[Path, ...]]:
    """Replace child `"nil"` positions with the corresponding parent element."""
    values: List[Any] = []
    sources: List[str] = []
    paths: List[Path] = []
    for position, value in enumerate(child):
        if value == NIL_SENTINEL and position < len(parent):
            values.append(parent[position])
            sources.append(
                parent_sources[position] if position < len(parent_sources) else child_source
            )
            paths.append(parent_paths[position] if position < len(parent_paths) else child_path)
        else:
            values.append(value)
            sources.append(child_source)
            paths.append(child_path)
    return values, tuple(sources), tuple(paths)
