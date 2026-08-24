"""Application service used by both the CLI and local editor."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from filament_tools.catalog import ProfileCatalog, app_label, source_kind
from filament_tools.comparison import compare_overrides, compare_profiles
from filament_tools.composition import LOCKED_COMPOSITION_KEYS, materialize_recipe
from filament_tools.identity import existing_material_identities
from filament_tools.lineage import inheritance_graph, lineage_context, lineage_descendants
from filament_tools.model import (
    BuildArtifact,
    ChoiceKind,
    CompositionRecipe,
    OutputMode,
    ProfileDraft,
    ValidationIssue,
)
from filament_tools.resolution import ProfileResolver
from filament_tools.schema import GROUP_LABELS, group_for_key, setting_metadata
from filament_tools.selectors import parse_selector
from filament_tools.transforms import (
    build_family,
    build_root,
    build_sparse,
    desired_values,
    json_values_equal,
)
from filament_tools.validation import validate_artifact, validate_sparse_roundtrip


class ProfileWorkbench:
    def __init__(self, catalog: ProfileCatalog):
        self.catalog = catalog
        self.resolver = ProfileResolver(catalog)

    def reload_catalog(self) -> int:
        """Reload profile files and invalidate every cached effective resolution."""
        self.catalog.refresh()
        self.resolver.clear()
        return len(self.catalog.by_path)

    def catalog_query(
        self,
        query: str = "",
        *,
        limit: int = 50,
        offset: int = 0,
        profile_type: Optional[str] = "filament",
        applications: Optional[set[str]] = None,
        source_kinds: Optional[set[str]] = None,
        vendor_or_material: Optional[str] = None,
        machine: Optional[str] = None,
        machines: Optional[set[str]] = None,
        nozzle: Optional[str] = None,
    ) -> Dict[str, Any]:
        profiles, total = self.catalog.query_visible(
            query=query,
            limit=limit,
            offset=offset,
            profile_type=profile_type,
            applications=applications,
            source_kinds=source_kinds,
            vendor_or_material=vendor_or_material,
            machine=machine,
            machines=machines,
            nozzle=nozzle,
        )
        entries: List[Dict[str, Any]] = []
        for profile in profiles:
            entry: Dict[str, Any] = {
                "name": profile.name,
                "path": str(profile.path),
                "inherits": profile.inherits,
                "app": app_label(profile.path),
                "source_kind": source_kind(profile.path),
            }
            try:
                resolved = self.resolver.resolve(profile)
                entry.update(
                    {
                        "type": resolved.values.get("type"),
                        "compatible_printers": resolved.values.get("compatible_printers", []),
                        "chain_length": len(resolved.chain),
                        "status": "ok",
                    }
                )
            except Exception as exc:
                entry.update(
                    {"type": profile.data.get("type"), "status": "broken", "error": str(exc)}
                )
            entries.append(entry)
        return {
            "results": entries,
            "total": total,
            "offset": max(offset, 0),
            "limit": max(limit, 0),
        }

    def catalog_entries(self, query: str = "") -> List[Dict[str, Any]]:
        """Compatibility wrapper for the default filament result window."""
        return self.catalog_query(query)["results"]

    def printer_options(self, query: str = "", *, limit: int = 50) -> Dict[str, Any]:
        """Return a small ranked window of exact machine preset names."""
        normalized = query.strip().casefold()
        names = [
            name
            for name in self.catalog.known_printer_names()
            if not normalized or normalized in name.casefold()
        ]

        def rank(name: str) -> tuple[int, str]:
            folded = name.casefold()
            if not normalized:
                score = 2
            elif folded == normalized:
                score = 0
            elif folded.startswith(normalized):
                score = 1
            else:
                score = 2
            return score, folded

        names.sort(key=rank)
        return {"results": names[:limit], "total": len(names), "limit": limit}

    def profile_view(self, selector: str) -> Dict[str, Any]:
        selected = parse_selector(selector)
        profile = self.catalog.select(selected)
        resolved = self.resolver.resolve(profile)
        override_report = compare_overrides(
            [profile], [profile.name], self.catalog, include_meta=True
        )[0]
        return {
            "name": profile.name,
            "path": str(profile.path),
            "inherits": profile.inherits,
            "raw": profile.data,
            "effective": resolved.values,
            "sources": resolved.sources,
            "source_paths": {key: str(path) for key, path in resolved.source_paths.items()},
            "element_sources": {
                key: list(sources) for key, sources in resolved.element_sources.items()
            },
            "element_source_paths": {
                key: [str(path) for path in paths]
                for key, paths in resolved.element_source_paths.items()
            },
            "chain": list(resolved.chain),
            "fingerprint": resolved.fingerprint,
            "summary": {
                "type": resolved.values.get("type"),
                "vendor": resolved.values.get("filament_vendor"),
                "material": resolved.values.get("filament_type"),
                "application": app_label(profile.path),
                "source_kind": source_kind(profile.path),
                "compatible_printers": resolved.values.get("compatible_printers", []),
                "inheritance_depth": max(len(resolved.chain) - 1, 0),
                "explicit_override_count": len(override_report.rows),
                "validation_state": "resolves",
            },
            "overrides": [
                {
                    "key": row.key,
                    "metadata": setting_metadata(row.key),
                    "explicit_value": row.explicit_value,
                    "parent_value": row.parent_value,
                    "difference": row.difference,
                    "parent_source": row.parent_source,
                }
                for row in override_report.rows
            ],
        }

    def create_draft(
        self,
        source: str,
        name: Optional[str] = None,
        base: Optional[str] = None,
        output_mode: OutputMode = OutputMode.SPARSE,
    ) -> ProfileDraft:
        source_profile = self.resolver.resolve_selector(source)
        base_profile = self.resolver.resolve_selector(base) if base else None
        return ProfileDraft(
            name=name or f"{source_profile.profile.name} copy",
            source=source,
            base=base,
            output_mode=output_mode,
            source_fingerprint=source_profile.fingerprint,
            base_fingerprint=base_profile.fingerprint if base_profile else None,
        )

    def comparison_view(
        self,
        selectors: List[str],
        *,
        mode: str = "effective",
        include_meta: bool = False,
        key_pattern: Optional[str] = None,
        groups: Optional[set[str]] = None,
        only_different: bool = False,
    ) -> Dict[str, Any]:
        selected = [parse_selector(selector) for selector in selectors]
        profiles = [self.catalog.select(selector) for selector in selected]
        labels = [
            selector.label or profile.name
            for selector, profile in zip(selected, profiles, strict=True)
        ]
        if mode == "overrides":
            reports = compare_overrides(
                profiles,
                labels,
                self.catalog,
                include_meta=include_meta,
                key_pattern=key_pattern,
                groups=groups,
                only_different=only_different,
            )
            rows_by_key: Dict[str, Dict[str, Any]] = {}
            for index, override_report in enumerate(reports):
                for row in override_report.rows:
                    item = rows_by_key.setdefault(
                        row.key,
                        {
                            "key": row.key,
                            "metadata": setting_metadata(row.key),
                            "group": group_for_key(row.key),
                            "group_label": GROUP_LABELS[group_for_key(row.key)],
                            "cells": [
                                {
                                    "value": None,
                                    "source": None,
                                    "explicit": False,
                                    "present": False,
                                    "source_path": None,
                                    "element_sources": [],
                                    "difference": "not explicit",
                                }
                                for _ in profiles
                            ],
                        },
                    )
                    item["cells"][index] = {
                        "value": row.explicit_value,
                        "source": row.parent_source,
                        "explicit": True,
                        "present": True,
                        "source_path": None,
                        "element_sources": [],
                        "difference": row.difference,
                    }
            rows = [rows_by_key[key] for key in sorted(rows_by_key)]
            if only_different:
                rows = [
                    row
                    for row in rows
                    if any(
                        row["cells"][0]["present"] != cell["present"]
                        or (
                            row["cells"][0]["present"]
                            and cell["present"]
                            and not json_values_equal(row["cells"][0]["value"], cell["value"])
                        )
                        for cell in row["cells"][1:]
                    )
                ]
            return {
                "mode": "overrides",
                "labels": labels,
                "profiles": [
                    {"name": profile.name, "path": str(profile.path)} for profile in profiles
                ],
                "rows": rows,
            }
        report = compare_profiles(
            profiles,
            self.resolver,
            labels,
            mode=mode,
            include_meta=include_meta,
            key_pattern=key_pattern,
            groups=groups,
            only_different=only_different,
        )
        return {
            "mode": report.mode,
            "labels": list(report.labels),
            "profiles": [
                {
                    "name": resolved.profile.name,
                    "path": str(resolved.profile.path),
                    "chain": list(resolved.chain),
                    "fingerprint": resolved.fingerprint,
                }
                for resolved in report.profiles
            ],
            "rows": [
                {
                    "key": row.key,
                    "metadata": setting_metadata(row.key),
                    "group": row.group,
                    "group_label": GROUP_LABELS[row.group],
                    "cells": [
                        {
                            "value": cell.value,
                            "source": cell.source,
                            "explicit": cell.explicit,
                            "present": cell.present,
                            "source_path": str(report.profiles[index].source_paths[row.key])
                            if mode == "effective"
                            and row.key in report.profiles[index].source_paths
                            else None,
                            "element_sources": list(
                                report.profiles[index].element_sources.get(row.key, ())
                            ),
                        }
                        for index, cell in enumerate(row.cells)
                    ],
                }
                for row in report.rows
            ],
        }

    def lineage_view(self) -> Dict[str, Any]:
        return inheritance_graph(self.catalog)

    def lineage_context(self, selector: str, *, child_limit: int = 50) -> Dict[str, Any]:
        profile = self.catalog.select(parse_selector(selector))
        return lineage_context(self.catalog, profile, child_limit=child_limit)

    def lineage_descendants(self, selector: str, *, limit: int = 500) -> Dict[str, Any]:
        profile = self.catalog.select(parse_selector(selector))
        return lineage_descendants(self.catalog, profile, limit=limit)

    def composition_view(self, recipe: CompositionRecipe) -> Dict[str, Any]:
        materialized = materialize_recipe(recipe, self.resolver)
        redundant_selections = set(materialized.redundant_selections)
        selectors = [recipe.starting_source, *recipe.reference_sources]
        sources = [self.resolver.resolve_selector(selector) for selector in selectors]
        keys = set(materialized.values)
        for source in sources:
            keys.update(source.values)
        keys -= LOCKED_COMPOSITION_KEYS
        rows = []
        for key in sorted(keys, key=lambda value: (group_for_key(value), value)):
            cells = []
            starting_value = sources[0].values.get(key)
            starting_present = key in sources[0].values
            for selector, source in zip(selectors, sources, strict=True):
                present = key in source.values
                cells.append(
                    {
                        "selector": selector,
                        "name": source.profile.name,
                        "value": source.values.get(key),
                        "present": present,
                        "source": source.sources.get(key),
                        "source_path": str(source.source_paths[key])
                        if key in source.source_paths
                        else None,
                        "explicit": key in source.profile.data,
                        "element_sources": list(source.element_sources.get(key, ())),
                        "matches_starting": starting_present == present
                        and (
                            not present or json_values_equal(starting_value, source.values.get(key))
                        ),
                    }
                )
            result_present = key in materialized.values
            result_value = materialized.values.get(key)
            sources_differ = any(not cell["matches_starting"] for cell in cells[1:])
            result_differs = starting_present != result_present or (
                starting_present
                and result_present
                and not json_values_equal(starting_value, result_value)
            )
            if not sources_differ and not result_differs:
                continue
            choice = None if key in redundant_selections else recipe.selections.get(key)
            selection_kind = choice.kind if choice else ChoiceKind.SOURCE
            selected_selector = (
                choice.source
                if choice and choice.kind == ChoiceKind.SOURCE
                else recipe.starting_source
                if choice is None
                else None
            )
            selected_via = materialized.selection_sources.get(key)
            if selection_kind == ChoiceKind.SOURCE and selected_via is None:
                selected_via = next(
                    source.profile.name
                    for selector, source in zip(selectors, sources, strict=True)
                    if selector == selected_selector
                )
            rows.append(
                {
                    "key": key,
                    "metadata": setting_metadata(key),
                    "group": group_for_key(key),
                    "group_label": GROUP_LABELS[group_for_key(key)],
                    "cells": cells,
                    "result": {
                        "value": result_value,
                        "present": result_present,
                        "selected_via": selected_via,
                        "selection_kind": selection_kind.value,
                        "selected_selector": selected_selector,
                        "source": materialized.value_sources.get(key),
                        "source_path": materialized.value_source_paths.get(key),
                        "element_sources": list(materialized.element_sources.get(key, ())),
                    },
                }
            )
        return {
            "sources": [
                {
                    "selector": selector,
                    "name": source.profile.name,
                    "path": str(source.profile.path),
                    "fingerprint": source.fingerprint,
                    "chain": list(source.chain),
                }
                for selector, source in zip(selectors, sources, strict=True)
            ],
            "rows": rows,
            "redundant_selections": list(materialized.redundant_selections),
            "issues": [issue.model_dump(mode="json") for issue in materialized.issues],
        }

    def build_recipe(self, recipe: CompositionRecipe) -> List[BuildArtifact]:
        return self.build(materialize_recipe(recipe, self.resolver).draft)

    def validate_recipe(
        self, recipe: CompositionRecipe, artifacts: List[BuildArtifact]
    ) -> List[ValidationIssue]:
        materialized = materialize_recipe(recipe, self.resolver)
        return [*materialized.issues, *self.validate(materialized.draft, artifacts)]

    def build(self, draft: ProfileDraft) -> List[BuildArtifact]:
        source = self.resolver.resolve_selector(draft.source)
        if draft.variants:
            return build_family(
                draft,
                source,
                existing_material_identities(self.catalog.by_path.values()),
            )
        if draft.output_mode == OutputMode.ROOT:
            return [
                build_root(
                    draft,
                    source,
                    existing_material_identities(self.catalog.by_path.values()),
                )
            ]
        if not draft.base:
            raise ValueError("sparse output requires a base profile")
        base = self.resolver.resolve_selector(draft.base)
        return [build_sparse(draft, source, base)]

    def validate(
        self, draft: ProfileDraft, artifacts: List[BuildArtifact]
    ) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        known_printers = self.catalog.known_printer_names()
        for artifact in artifacts:
            issues.extend(validate_artifact(artifact, known_printers or None))
        source = self.resolver.resolve_selector(draft.source)
        if draft.source_fingerprint and draft.source_fingerprint != source.fingerprint:
            from filament_tools.model import Severity

            issues.append(
                ValidationIssue(
                    severity=Severity.WARNING,
                    code="draft.source_drift",
                    message="source effective settings changed since this draft was created",
                )
            )
        if draft.output_mode == OutputMode.SPARSE and draft.base and artifacts:
            base = self.resolver.resolve_selector(draft.base)
            source_id = source.values.get("filament_id")
            base_id = base.values.get("filament_id")
            if (
                isinstance(source_id, str)
                and isinstance(base_id, str)
                and source_id.strip()
                and base_id.strip()
                and source_id.strip() != base_id.strip()
            ):
                from filament_tools.model import Severity

                issues.append(
                    ValidationIssue(
                        severity=Severity.WARNING,
                        code="sparse.material_identity_changed",
                        message=(
                            "modified source has a different effective filament_id; "
                            "the sparse child will inherit the base material identity"
                        ),
                        key="filament_id",
                    )
                )
            issues.extend(
                validate_sparse_roundtrip(
                    artifacts[0],
                    base.values,
                    desired_values(source, draft),
                )
            )
            if draft.base_fingerprint and draft.base_fingerprint != base.fingerprint:
                from filament_tools.model import Severity

                issues.append(
                    ValidationIssue(
                        severity=Severity.WARNING,
                        code="draft.base_drift",
                        message="base effective settings changed since this draft was created",
                    )
                )
        return issues
