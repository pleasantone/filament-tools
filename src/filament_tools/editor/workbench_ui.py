"""NiceGUI workbench backed exclusively by ProfileWorkbench services."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from fastapi import FastAPI
from nicegui import core, events, ui

from filament_tools.comparison import compare_profiles as collect_comparison
from filament_tools.editor.projects import (
    load_composition_project_document,
    save_composition_project,
)
from filament_tools.installation import apply_install_plan, plan_install
from filament_tools.model import (
    ChoiceKind,
    ComparisonCell,
    ComparisonReport,
    ComparisonRow,
    CompositionChoice,
    CompositionRecipe,
    IdentityMode,
    InstallAction,
    OutputMode,
    TargetVariant,
)
from filament_tools.naming import (
    default_document_directory,
    suggest_output_path,
    suggest_project_name,
    suggest_project_path,
)
from filament_tools.reporting.csv_report import write_csv
from filament_tools.reporting.html_report import write_html
from filament_tools.schema import GROUP_LABELS
from filament_tools.selectors import parse_selector
from filament_tools.service import ProfileWorkbench
from filament_tools.transforms import write_artifact, write_artifacts
from filament_tools.validation import has_errors

CATALOG_FILTERS_STORAGE_KEY = "filament-tools-catalog-filters-v1"
DESTINATION_DIRECTORIES_STORAGE_KEY = "filament-tools-destination-directories-v1"
WORKBENCH_DARK_MODE = False
DEFAULT_MACHINE_FILTERS = ("H2C", "X1C")


def _display(value: Any, present: bool = True) -> str:
    if not present:
        return "∅"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _variant_edits_json(value: str) -> Dict[str, Any]:
    text = value.strip()
    if not text:
        return {}
    edits = json.loads(text)
    if not isinstance(edits, dict):
        raise ValueError("variant setting edits must be a JSON object")
    return edits


def _setting_label(row: Dict[str, Any]) -> str:
    metadata = row.get("metadata", {})
    name = str(metadata.get("name") or row["key"])
    unit = str(metadata.get("unit") or "")
    heading = f"{name} ({unit})" if unit else name
    return f"{heading}\n{row['key']}"


def _numeric_delta(baseline: Any, value: Any) -> Optional[str]:
    def number(candidate: Any) -> Optional[float]:
        if isinstance(candidate, list) and len(candidate) == 1:
            candidate = candidate[0]
        if isinstance(candidate, bool):
            return None
        try:
            return float(candidate)
        except (TypeError, ValueError):
            return None

    before, after = number(baseline), number(value)
    if before is None or after is None or before == after:
        return None
    return f"{after - before:+g}"


def _inherited_source_names(
    profile_name: str,
    source: str | None,
    element_sources: Sequence[str] = (),
) -> List[str]:
    inherited = list(
        dict.fromkeys(name for name in element_sources if name and name != profile_name)
    )
    if inherited:
        return inherited
    return [source] if source and source != profile_name else []


def _comparison_cell_text(
    cell: Dict[str, Any],
    *,
    baseline_value: Any,
    index: int,
    mode: str,
    profile_name: str = "",
) -> str:
    rendered = _display(cell["value"], cell["present"])
    delta = _numeric_delta(baseline_value, cell["value"])
    if index and delta:
        rendered += f" · Δ {delta}"

    displayed_profile = profile_name or (str(cell.get("source") or "") if cell["explicit"] else "")
    inherited_sources = _inherited_source_names(
        displayed_profile,
        cell.get("source"),
        cell.get("element_sources", ()),
    )
    source = f"\n↳ {', '.join(inherited_sources)}" if inherited_sources else ""
    if mode == "overrides":
        difference = f" · {cell.get('difference')}"
        return rendered + difference
    if not cell["present"] or not inherited_sources:
        return rendered
    qualifier = "inherited elements" if cell.get("explicit") else "inherited"
    return rendered + source + f" · {qualifier}"


def _composition_source_text(cell: Dict[str, Any]) -> str:
    inherited_sources = _inherited_source_names(
        cell["name"],
        cell.get("source"),
        cell.get("element_sources", ()),
    )
    inherited = f"\n↳ inherited from {', '.join(inherited_sources)}" if inherited_sources else ""
    return _display(cell["value"], cell["present"]) + inherited


def _composition_source_column(name: str, index: int) -> Dict[str, Any]:
    selected_field = f"_source_selected_{index}"
    return {
        "headerName": name,
        "field": f"source_{index}",
        "minWidth": 210,
        "wrapText": True,
        "autoHeight": True,
        ":cellClass": (f"params => params.data?.{selected_field} ? 'ft-value-source' : ''"),
        ":tooltipValueGetter": (
            f"params => params.data?.{selected_field} ? 'Value source for composed result' : null"
        ),
    }


def _composition_result_column() -> Dict[str, Any]:
    return {
        "headerName": "Composed result",
        "field": "result",
        "minWidth": 210,
        "wrapText": True,
        "autoHeight": True,
        ":cellClass": (
            "params => params.data?._result_state === 'remove' "
            "? 'ft-value-removed' : params.data?._result_state === 'custom' "
            "? 'ft-value-source' : ''"
        ),
        ":tooltipValueGetter": (
            "params => params.data?._result_state === 'remove' "
            "? 'Setting removed from composed result' "
            ": params.data?._result_state === 'custom' "
            "? 'Custom value source for composed result' : null"
        ),
    }


def _composition_scroll_capture_handler(grid_id: int) -> str:
    return f"""params => {{
      const root = params.event?.target?.closest?.('.nicegui-aggrid')
        ?? document.getElementById('c{grid_id}');
      const viewport = root?.querySelector('.ag-body-viewport');
      window.__filamentToolsGridScroll ??= {{}};
      window.__filamentToolsGridScroll[{grid_id}] = {{
        top: viewport?.scrollTop ?? 0,
        left: viewport?.scrollLeft ?? 0,
        pageX: window.scrollX,
        pageY: window.scrollY,
        capturedAt: performance.now(),
      }};
    }}"""


def _update_composition_grid(
    grid: Any,
    columns: List[Dict[str, Any]],
    rows: List[Dict[str, Any]],
    *,
    reset: bool,
) -> None:
    columns_changed = grid.options.get("columnDefs") != columns
    previous_rows = grid.options.get("rowData", [])
    same_row_ids = [row.get("key") for row in previous_rows] == [row.get("key") for row in rows]
    previous_by_key = {row.get("key"): row for row in previous_rows}
    changed_rows = [row for row in rows if previous_by_key.get(row.get("key")) != row]
    grid.options.update(
        {
            "columnDefs": columns,
            "rowData": rows,
            "animateRows": False,
            "defaultColDef": {"resizable": True, "sortable": True},
        }
    )
    if reset or columns_changed:
        grid.update()
    elif same_row_ids:
        if changed_rows:
            transaction = json.dumps({"update": changed_rows})
            grid.client.run_javascript(
                f"""
                const component = getElement({grid.id});
                const root = getHtmlElement({grid.id});
                const viewport = root?.querySelector('.ag-body-viewport');
                const pendingCapture = window.__filamentToolsGridScroll?.[{grid.id}];
                const captured = pendingCapture
                  && performance.now() - pendingCapture.capturedAt < 1500
                  ? pendingCapture
                  : null;
                if (window.__filamentToolsGridScroll) {{
                  delete window.__filamentToolsGridScroll[{grid.id}];
                }}
                const scrollTop = captured?.top ?? viewport?.scrollTop ?? 0;
                const scrollLeft = captured?.left ?? viewport?.scrollLeft ?? 0;
                const pageX = captured?.pageX ?? window.scrollX;
                const pageY = captured?.pageY ?? window.scrollY;
                component.api.applyTransaction({transaction});
                let remainingRestores = 6;
                const restoreViewport = () => {{
                  const liveRoot = getHtmlElement({grid.id});
                  const liveViewport = liveRoot?.querySelector('.ag-body-viewport');
                  const verticalRail = liveRoot?.querySelector(
                    '.ag-body-vertical-scroll-viewport'
                  );
                  const horizontalRail = liveRoot?.querySelector(
                    '.ag-body-horizontal-scroll-viewport'
                  );
                  if (liveViewport) {{
                    liveViewport.scrollTop = scrollTop;
                    liveViewport.scrollLeft = scrollLeft;
                  }}
                  if (verticalRail) verticalRail.scrollTop = scrollTop;
                  if (horizontalRail) horizontalRail.scrollLeft = scrollLeft;
                  window.scrollTo(pageX, pageY);
                  if (--remainingRestores > 0) requestAnimationFrame(restoreViewport);
                }};
                requestAnimationFrame(restoreViewport);
                """
            )
    else:
        grid.run_grid_method("setGridOption", "rowData", rows)


class CompatibilitySeedState:
    """Track source-derived compatibility without overwriting user choices."""

    def __init__(self) -> None:
        self.seeded_values: Optional[tuple[str, ...]] = None

    def accept_source_values(
        self, current: Sequence[str], source_values: Sequence[str]
    ) -> Optional[List[str]]:
        current_values = tuple(str(value) for value in current)
        if self.seeded_values is None:
            if current_values:
                return None
        elif current_values != self.seeded_values:
            return None
        values = list(
            dict.fromkeys(str(value).strip() for value in source_values if str(value).strip())
        )
        self.seeded_values = tuple(values)
        return values

    def reset(self) -> None:
        self.seeded_values = None


class SeededStringState:
    """Distinguish an automatic string value from an explicit user value."""

    def __init__(self) -> None:
        self.seeded_value: Optional[str] = None

    def should_replace(self, current: str) -> bool:
        return not current or (self.seeded_value is not None and current == self.seeded_value)

    def record(self, value: str) -> None:
        self.seeded_value = value

    def reset(self) -> None:
        self.seeded_value = None


@dataclass(frozen=True)
class CatalogFilterState:
    """Serializable library filters with explicit first-run and cleared states."""

    search: str = ""
    applications: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    material: str = ""
    machines: tuple[str, ...] = DEFAULT_MACHINE_FILTERS
    nozzle: str = ""
    profile_type: str = "filament"

    @classmethod
    def cleared(cls) -> CatalogFilterState:
        return cls(machines=(), profile_type="")

    @classmethod
    def from_json(cls, value: str | None) -> CatalogFilterState:
        default = cls()
        if not value:
            return default
        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default
        if not isinstance(payload, dict):
            return default

        def text(key: str, fallback: str) -> str:
            candidate = payload.get(key, fallback)
            return candidate if isinstance(candidate, str) else fallback

        def choices(key: str, fallback: tuple[str, ...], allowed: set[str] | None = None):
            candidate = payload.get(key, list(fallback))
            if not isinstance(candidate, list):
                return fallback
            values = tuple(
                dict.fromkeys(
                    item.strip()
                    for item in candidate
                    if isinstance(item, str)
                    and item.strip()
                    and (allowed is None or item.strip() in allowed)
                )
            )
            return values

        profile_type = text("profile_type", default.profile_type)
        if profile_type not in {"", "filament"}:
            profile_type = default.profile_type
        return cls(
            search=text("search", default.search),
            applications=choices(
                "applications",
                default.applications,
                {"Bambu Studio", "OrcaSlicer"},
            ),
            sources=choices("sources", default.sources, {"user", "system", "bundled"}),
            material=text("material", default.material),
            machines=choices("machines", default.machines),
            nozzle=text("nozzle", default.nozzle),
            profile_type=profile_type,
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "search": self.search,
                "applications": list(self.applications),
                "sources": list(self.sources),
                "material": self.material,
                "machines": list(self.machines),
                "nozzle": self.nozzle,
                "profile_type": self.profile_type,
            },
            separators=(",", ":"),
            sort_keys=True,
        )


class WorkbenchSession:
    def __init__(
        self,
        workbench: ProfileWorkbench,
        catalog_filters: CatalogFilterState | None = None,
    ):
        self.workbench = workbench
        filters = catalog_filters or CatalogFilterState()
        catalog_page = workbench.catalog_query(
            filters.search,
            limit=50,
            profile_type=filters.profile_type or None,
            applications=set(filters.applications) or None,
            source_kinds=set(filters.sources) or None,
            vendor_or_material=filters.material or None,
            machines=set(filters.machines) or None,
            nozzle=filters.nozzle or None,
        )
        self.entries = catalog_page["results"]
        self.catalog_total = int(catalog_page["total"])
        self.options = {
            entry["path"]: (
                f"{entry['name']} · {entry['app']}/{entry['source_kind']}"
                + (" · broken" if entry.get("status") == "broken" else "")
            )
            for entry in self.entries
        }
        self.selected_profiles: List[str] = []
        self.selections: Dict[str, CompositionChoice] = {}
        self.fingerprints: Dict[str, str] = {}
        self.composition: Optional[Dict[str, Any]] = None
        self.active_key: Optional[str] = None
        self.undo_stack: List[Dict[str, CompositionChoice]] = []
        self.redo_stack: List[Dict[str, CompositionChoice]] = []
        self.revision = 0
        self.preview_revision: Optional[int] = None
        self.install_plan_revision: Optional[int] = None
        self.preview_valid = False
        self.preview_artifacts: List[Any] = []
        self.saved_revision = 0
        self.pending_plan: Any = None
        self.current_project_path: Optional[Path] = None
        self.project_directory = default_document_directory()
        self.output_directory = default_document_directory()
        self.last_action = ""

    def checkpoint(self, action: str) -> None:
        self.undo_stack.append(copy.deepcopy(self.selections))
        self.redo_stack.clear()
        self.last_action = action

    @property
    def dirty(self) -> bool:
        return self.revision != self.saved_revision

    @staticmethod
    def recipe_fingerprint(recipe: CompositionRecipe) -> str:
        payload = json.dumps(recipe.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _add_global_styles() -> None:
    ui.add_css(
        """
        :root { --ft-ink:#19231f; --ft-muted:#66736d; --ft-line:#d9e0dc;
          --ft-green:#0d7652; --ft-green-soft:#e8f5ef; --ft-amber:#a95e13;
          --ft-canvas:#f4f7f5; --ft-panel:#ffffff; }
        body { background:var(--ft-canvas); color:var(--ft-ink); }
        .ft-header { background:#12372b; color:white; }
        .ft-shell { max-width:1800px; margin:0 auto; width:100%; }
        .ft-card { background:var(--ft-panel); border:1px solid var(--ft-line);
          border-radius:14px; box-shadow:0 1px 2px rgba(24,35,31,.04); }
        .ft-kicker { color:var(--ft-green); font-size:.72rem; font-weight:800;
          letter-spacing:.09em; text-transform:uppercase; }
        .ft-muted { color:var(--ft-muted); }
        .ft-stat { background:var(--ft-green-soft); color:var(--ft-green);
          border-radius:999px; padding:.25rem .65rem; font-weight:700; }
        .ft-code { max-height:52vh; overflow:auto; border:1px solid var(--ft-line);
          border-radius:10px; }
        .ft-grid { min-height:360px; height:min(62vh,720px); width:100%; }
        .ft-grid .ag-body-horizontal-scroll { min-height:16px !important; }
        .ft-grid .ag-cell.ft-value-source {
          background:#ddf3e8 !important; color:#12372b;
          box-shadow:inset 4px 0 #0d7652; transition:background-color .12s ease;
        }
        .ft-grid .ag-cell.ft-value-source:hover { background:#cdebdc !important; }
        .ft-grid .ag-cell.ft-value-removed {
          background:#fff3d6 !important; color:#6f4309;
          box-shadow:inset 4px 0 #a95e13; transition:background-color .12s ease;
        }
        .ft-grid .ag-cell.ft-value-removed:hover { background:#f9e8bd !important; }
        .ft-status { border:1px solid var(--ft-line); border-radius:999px;
          padding:.2rem .6rem; font-size:.78rem; font-weight:700; }
        .ft-danger { color:#9f2d24; background:#fff0ee; }
        .ft-warning { color:#7a4a08; background:#fff7e8; }
        .ft-ok { color:var(--ft-green); background:var(--ft-green-soft); }
        .q-btn.bg-primary { background:var(--ft-green) !important; }
        :focus-visible { outline:3px solid #2c8c68 !important; outline-offset:2px; }
        @media (max-width:1100px) {
          .ft-grid { height:55vh; }
          .ft-responsive-row { flex-direction:column; }
          .ft-responsive-row > * { width:100% !important; max-width:none !important; }
        }
        .q-tab--active { color:#0d7652 !important; }
        """
    )


def render_workbench(workbench: ProfileWorkbench) -> None:
    initial_catalog_filters = CatalogFilterState()
    state = WorkbenchSession(workbench, initial_catalog_filters)
    compatibility_seed = CompatibilitySeedState()
    output_name_seed = SeededStringState()
    project_name_seed = SeededStringState()
    project_path_seed = SeededStringState()
    output_path_seed = SeededStringState()
    material_name_seed = SeededStringState()
    install_app_seed = SeededStringState()
    install_app_seed.record("bambu")
    variant_rows: List[Dict[str, Any]] = []
    printer_option_map: Dict[str, str] = {}
    _add_global_styles()
    ui.page_title("Filament Tools Workbench")

    with ui.header().classes("ft-header items-center px-6 py-3"):
        with ui.row().classes("ft-shell items-center justify-between"):
            with ui.column().classes("gap-0"):
                ui.label("FILAMENT TOOLS").classes("text-xs tracking-widest opacity-75")
                ui.label("Profile Workbench").classes("text-xl font-bold").props(
                    'role="heading" aria-level="1"'
                )
            with ui.row().classes("items-center gap-3"):
                quick_start_button = ui.button("Quick start", icon="help_outline").props(
                    "flat color=white"
                )
                status_label = ui.label(
                    f"{state.catalog_total} filament profiles available"
                ).classes("text-sm")

    with ui.tabs().classes("w-full bg-white border-b") as tabs:
        profiles_tab = ui.tab("Library", icon="inventory_2")
        compare_tab = ui.tab("Compare", icon="difference")
        compose_tab = ui.tab("Create profile", icon="tune")
        build_tab = ui.tab("Review & install", icon="build_circle")
        lineage_tab = ui.tab("Lineage explorer", icon="account_tree")

    with ui.tab_panels(tabs, value=profiles_tab).classes("ft-shell w-full bg-transparent p-4"):
        with ui.tab_panel(profiles_tab):
            with ui.row().classes("w-full gap-4 items-start ft-responsive-row"):
                with ui.column().classes("ft-card p-4 w-full max-w-md"):
                    ui.label("PROFILE CATALOG").classes("ft-kicker")
                    catalog_search = ui.input(
                        label="Search installed profiles",
                        placeholder="Name, material, vendor, or exact JSON path",
                        value=initial_catalog_filters.search,
                    ).classes("w-full")
                    with ui.expansion("Filters", icon="filter_alt").classes("w-full"):
                        catalog_app = ui.select(
                            {"Bambu Studio": "Bambu Studio", "OrcaSlicer": "OrcaSlicer"},
                            value=list(initial_catalog_filters.applications),
                            label="Application",
                            multiple=True,
                        ).classes("w-full")
                        catalog_source = ui.select(
                            {"user": "User", "system": "System", "bundled": "Bundled"},
                            value=list(initial_catalog_filters.sources),
                            label="Source",
                            multiple=True,
                        ).classes("w-full")
                        catalog_material = ui.input(
                            label="Vendor or material",
                            value=initial_catalog_filters.material,
                        ).classes("w-full")
                        with ui.row().classes("w-full gap-2"):
                            catalog_machine = (
                                ui.select(
                                    {"H2C": "H2C", "X1C": "X1C"},
                                    value=list(initial_catalog_filters.machines),
                                    label="Machines (any match)",
                                    multiple=True,
                                    with_input=True,
                                    new_value_mode="add-unique",
                                )
                                .classes("flex-grow")
                                .props('data-testid="catalog-machines"')
                            )
                            catalog_nozzle = ui.input(
                                label="Nozzle",
                                value=initial_catalog_filters.nozzle,
                            ).classes("w-32")
                        ui.label(
                            "Matching profiles and their generic inheritance parents are shown."
                        ).classes("ft-muted text-xs")
                        catalog_scope = ui.select(
                            {"filament": "Filaments", "": "All preset types (Advanced)"},
                            value=initial_catalog_filters.profile_type,
                            label="Preset scope",
                        ).classes("w-full")
                        with ui.row().classes("w-full gap-2"):
                            clear_catalog_filters = ui.button(
                                "Clear all filters", icon="filter_alt_off"
                            ).props('outline data-testid="clear-catalog-filters"')
                            reload_catalog_button = ui.button(
                                "Reload profiles", icon="refresh"
                            ).props('outline data-testid="reload-catalog"')
                    catalog_count = ui.label(
                        f"Showing {len(state.entries)} of {state.catalog_total}"
                    ).classes("ft-muted text-sm")
                    catalog_filters_summary = ui.label(
                        "Active filters: Filaments · Machines: H2C, X1C"
                    ).classes("ft-muted text-xs")
                    catalog_select = (
                        ui.select(
                            state.options,
                            label="Profile",
                            with_input=True,
                            new_value_mode="add-unique",
                        )
                        .classes("w-full")
                        .props('data-testid="catalog-profile"')
                    )
                    inspect_mode = ui.toggle(
                        {"effective": "Effective", "overrides": "Overrides", "raw": "Raw"},
                        value="effective",
                    ).classes("w-full")
                    ui.label(
                        "Effective values include inheritance. Inherited from identifies only ancestor-provided values."
                    ).classes("ft-muted text-sm")
                    add_compare_button = ui.button("Add to comparison", icon="add_chart").classes(
                        "w-full"
                    )
                with ui.column().classes("ft-card p-4 flex-grow min-w-0"):
                    profile_heading = ui.label("Choose a profile").classes("text-lg font-bold")
                    profile_meta = ui.label().classes("ft-muted text-sm")
                    profile_chain = ui.label().classes("ft-stat self-start")
                    profile_summary = ui.row().classes("w-full gap-2 flex-wrap")
                    profile_grid = ui.aggrid(
                        {"columnDefs": [], "rowData": []}, theme="quartz", auto_size_columns=False
                    ).classes("ft-grid")
                    with ui.expansion("Raw JSON (Advanced)", icon="data_object").classes("w-full"):
                        profile_json = ui.code("{}", language="json").classes("ft-code w-full")

            catalog_filter_events_suspended = False

            def current_catalog_filters() -> CatalogFilterState:
                return CatalogFilterState(
                    search=str(catalog_search.value or ""),
                    applications=tuple(str(value) for value in catalog_app.value or []),
                    sources=tuple(str(value) for value in catalog_source.value or []),
                    material=str(catalog_material.value or ""),
                    machines=tuple(str(value) for value in catalog_machine.value or []),
                    nozzle=str(catalog_nozzle.value or ""),
                    profile_type=str(catalog_scope.value or ""),
                )

            def persist_catalog_filters(filters: CatalogFilterState) -> None:
                if core.loop is not None:
                    ui.run_javascript(
                        "localStorage.setItem("
                        + json.dumps(CATALOG_FILTERS_STORAGE_KEY)
                        + ", "
                        + json.dumps(filters.to_json())
                        + ");"
                    )

            def set_catalog_filter_controls(filters: CatalogFilterState) -> None:
                nonlocal catalog_filter_events_suspended
                catalog_filter_events_suspended = True
                values = (
                    (catalog_search, filters.search),
                    (catalog_app, list(filters.applications)),
                    (catalog_source, list(filters.sources)),
                    (catalog_material, filters.material),
                    (catalog_machine, list(filters.machines)),
                    (catalog_nozzle, filters.nozzle),
                    (catalog_scope, filters.profile_type),
                )
                for control, value in values:
                    control.value = value
                    control.update()
                catalog_filter_events_suspended = False

            def refresh_catalog(*, persist: bool = False) -> None:
                try:
                    filters = current_catalog_filters()
                    page = workbench.catalog_query(
                        filters.search,
                        limit=50,
                        profile_type=filters.profile_type or None,
                        applications=set(filters.applications) or None,
                        source_kinds=set(filters.sources) or None,
                        vendor_or_material=filters.material or None,
                        machines=set(filters.machines) or None,
                        nozzle=filters.nozzle or None,
                    )
                    state.entries = page["results"]
                    state.options = {
                        entry["path"]: (
                            f"{entry['name']} · {entry['app']}/{entry['source_kind']}"
                            + (" · broken" if entry.get("status") == "broken" else "")
                        )
                        for entry in state.entries
                    }
                    for selector in (
                        catalog_select,
                        compare_profiles,
                        lineage_select,
                        starting_source,
                        reference_sources,
                        sparse_parent,
                    ):
                        selector.set_options(state.options)
                    catalog_count.text = f"Showing {len(state.entries)} of {page['total']}"
                    active_filters = []
                    if filters.profile_type:
                        active_filters.append("Filaments")
                    active_filters.extend(filters.applications)
                    active_filters.extend(filters.sources)
                    for label, value in (
                        ("Material", filters.material),
                        ("Machines", ", ".join(filters.machines)),
                        ("Nozzle", filters.nozzle),
                    ):
                        if value:
                            active_filters.append(f"{label}: {value}")
                    catalog_filters_summary.text = (
                        "Active filters: " + " · ".join(str(value) for value in active_filters)
                        if active_filters
                        else "No active filters"
                    )
                    if persist:
                        persist_catalog_filters(filters)
                except Exception as exc:
                    ui.notify(str(exc), type="negative")

            def catalog_filters_changed() -> None:
                if not catalog_filter_events_suspended:
                    refresh_catalog(persist=True)

            def clear_all_catalog_filters() -> None:
                filters = CatalogFilterState.cleared()
                set_catalog_filter_controls(filters)
                refresh_catalog(persist=True)

            def reload_profiles_from_disk() -> None:
                try:
                    count = workbench.reload_catalog()
                    refresh_catalog()
                    ui.notify(f"Reloaded {count} profiles from disk", type="positive")
                except Exception as exc:
                    ui.notify(str(exc), type="negative", multi_line=True)

            async def restore_catalog_filters() -> None:
                try:
                    stored = await ui.run_javascript(
                        "localStorage.getItem(" + json.dumps(CATALOG_FILTERS_STORAGE_KEY) + ")"
                    )
                    filters = CatalogFilterState.from_json(str(stored) if stored else None)
                    set_catalog_filter_controls(filters)
                    refresh_catalog()
                except Exception:
                    return

            def inspect_profile() -> None:
                if not catalog_select.value:
                    return
                try:
                    view = workbench.profile_view(str(catalog_select.value))
                    profile_heading.text = view["name"]
                    profile_meta.text = view["path"]
                    profile_chain.text = " → ".join(view["chain"])
                    profile_summary.clear()
                    with profile_summary:
                        for label, value in (
                            ("Material", view["summary"].get("material") or "Unknown"),
                            ("Vendor", view["summary"].get("vendor") or "Unknown"),
                            ("Application", view["summary"]["application"]),
                            ("Source", view["summary"]["source_kind"]),
                            ("Depth", view["summary"]["inheritance_depth"]),
                            ("Overrides", view["summary"]["explicit_override_count"]),
                        ):
                            ui.label(f"{label}: {value}").classes("ft-status ft-ok")
                    if inspect_mode.value == "overrides":
                        rows = [
                            {
                                "key": row["key"],
                                "value": _display(row["explicit_value"]),
                                "parent": _display(row["parent_value"]),
                                "difference": row["difference"],
                                "source": row["parent_source"] or "—",
                            }
                            for row in view["overrides"]
                        ]
                        columns = [
                            {"headerName": "Setting", "field": "key", "minWidth": 230},
                            {"headerName": "Explicit value", "field": "value", "minWidth": 220},
                            {"headerName": "Parent value", "field": "parent", "minWidth": 220},
                            {"headerName": "Difference", "field": "difference", "width": 130},
                            {
                                "headerName": "Parent defined by",
                                "field": "source",
                                "minWidth": 180,
                            },
                        ]
                    else:
                        values = view[str(inspect_mode.value)]
                        rows = [
                            {
                                "key": key,
                                "value": _display(value),
                                "source": ", ".join(
                                    _inherited_source_names(
                                        view["name"],
                                        view["sources"].get(key),
                                        view["element_sources"].get(key, ()),
                                    )
                                ),
                            }
                            for key, value in sorted(values.items())
                        ]
                        columns = [
                            {"headerName": "Setting", "field": "key", "minWidth": 250},
                            {"headerName": "Value", "field": "value", "minWidth": 300, "flex": 1},
                        ]
                        if inspect_mode.value == "effective":
                            columns.append(
                                {
                                    "headerName": "Inherited from",
                                    "field": "source",
                                    "minWidth": 200,
                                }
                            )
                    profile_grid.options.update(
                        {
                            "columnDefs": columns,
                            "rowData": rows,
                            "defaultColDef": {"resizable": True, "sortable": True, "filter": True},
                        }
                    )
                    profile_grid.update()
                    profile_json.content = json.dumps(
                        view["raw"], ensure_ascii=False, indent=2, sort_keys=True
                    )
                    profile_json.update()
                except Exception as exc:
                    ui.notify(str(exc), type="negative")

            catalog_select.on_value_change(lambda _: inspect_profile())
            inspect_mode.on_value_change(lambda _: inspect_profile())
            for control in (catalog_app, catalog_source, catalog_scope):
                control.on_value_change(lambda _: catalog_filters_changed())
            for control in (
                catalog_search,
                catalog_material,
                catalog_nozzle,
            ):
                control.on(
                    "update:model-value",
                    lambda _: catalog_filters_changed(),
                    throttle=0.35,
                    leading_events=False,
                    trailing_events=True,
                )
            catalog_machine.on_value_change(lambda _: catalog_filters_changed())
            clear_catalog_filters.on_click(clear_all_catalog_filters)
            reload_catalog_button.on_click(reload_profiles_from_disk)
            if core.loop is not None:
                ui.timer(0.25, restore_catalog_filters, once=True)

        with ui.tab_panel(compare_tab):
            with ui.column().classes("w-full gap-4"):
                with ui.row().classes("ft-card p-4 w-full items-end gap-3"):
                    compare_search = ui.input(
                        label="Search settings", placeholder="Name or raw key"
                    ).classes("min-w-64 flex-grow")
                    compare_profiles = (
                        ui.select(
                            state.options,
                            label="Profiles (two or more)",
                            multiple=True,
                            with_input=True,
                            new_value_mode="add-unique",
                        )
                        .classes("min-w-64 flex-grow")
                        .props('data-testid="compare-profiles"')
                    )
                    compare_baseline = ui.select({}, label="Baseline profile").classes("w-64")
                    compare_mode = ui.select(
                        {"effective": "Effective", "raw": "Raw", "overrides": "Overrides"},
                        value="effective",
                        label="View",
                    ).classes("w-36")
                    compare_groups = ui.select(
                        GROUP_LABELS,
                        label="Groups",
                        multiple=True,
                    ).classes("w-64")
                    include_meta = ui.switch("Include metadata", value=False)
                with ui.row().classes("w-full items-center justify-between"):
                    compare_summary = ui.label("Select at least two profiles.").classes("ft-muted")
                    create_from_compare = ui.button(
                        "Create from this comparison", icon="arrow_forward"
                    )
                with ui.expansion("Export comparison", icon="file_download").classes(
                    "ft-card px-4 w-full"
                ):
                    with ui.row().classes("w-full items-end gap-3"):
                        export_path = ui.input(label="Comparison export path").classes("flex-grow")
                        export_format = ui.select(
                            {"html": "Self-contained HTML", "csv": "CSV"},
                            value="html",
                            label="Format",
                        ).classes("w-48")
                        export_sources = ui.switch("Include provenance", value=True)
                        export_button = ui.button("Export", icon="file_download").props("outline")
                compare_grid_container = ui.column().classes("ft-card p-2 w-full")
                with compare_grid_container:
                    compare_grid = ui.aggrid(
                        {"columnDefs": [], "rowData": [], "animateRows": False},
                        theme="quartz",
                        auto_size_columns=False,
                    ).classes("ft-grid")

            def render_comparison() -> None:
                profiles = list(compare_profiles.value or [])
                if compare_baseline.value in profiles:
                    profiles = [compare_baseline.value] + [
                        profile for profile in profiles if profile != compare_baseline.value
                    ]
                if len(profiles) < 2:
                    compare_summary.text = "Select at least two profiles."
                    compare_grid.options.update({"columnDefs": [], "rowData": []})
                    compare_grid.update()
                    return
                try:
                    data = workbench.comparison_view(
                        profiles,
                        mode=str(compare_mode.value),
                        include_meta=bool(include_meta.value),
                        key_pattern=str(compare_search.value or "") or None,
                        groups=set(compare_groups.value or []) or None,
                        only_different=True,
                    )
                    columns = [
                        {
                            "headerName": "Setting",
                            "field": "setting",
                            "pinned": "left",
                            "minWidth": 230,
                            "filter": True,
                        },
                        {"headerName": "Group", "field": "group", "width": 150, "filter": True},
                    ]
                    for index, label in enumerate(data["labels"]):
                        columns.append(
                            {
                                "headerName": label,
                                "field": f"value_{index}",
                                "minWidth": 220,
                                "flex": 1,
                                "wrapText": True,
                                "autoHeight": True,
                                "filter": True,
                            }
                        )
                    rows = []
                    for row in data["rows"]:
                        item = {
                            "key": row["key"],
                            "setting": _setting_label(row),
                            "group": row["group_label"],
                        }
                        baseline = row["cells"][0]
                        for index, cell in enumerate(row["cells"]):
                            item[f"value_{index}"] = _comparison_cell_text(
                                cell,
                                baseline_value=baseline["value"],
                                index=index,
                                mode=data["mode"],
                                profile_name=data["profiles"][index]["name"],
                            )
                        rows.append(item)
                    compare_grid.options.update(
                        {
                            "columnDefs": columns,
                            "rowData": rows,
                            "animateRows": False,
                            "defaultColDef": {"resizable": True, "sortable": True},
                        }
                    )
                    compare_grid.update()
                    counts = Counter(row["group_label"] for row in data["rows"])
                    summary = " · ".join(f"{group}: {count}" for group, count in counts.items())
                    compare_summary.text = f"{len(rows)} settings" + (
                        f" · {summary}" if summary else ""
                    )
                    state.selected_profiles = profiles
                except Exception as exc:
                    ui.notify(str(exc), type="negative", multi_line=True)

            def update_comparison_profiles() -> None:
                profiles = list(compare_profiles.value or [])
                compare_baseline.set_options(
                    {profile: state.options.get(profile, profile) for profile in profiles}
                )
                if profiles and compare_baseline.value not in profiles:
                    compare_baseline.value = profiles[0]
                render_comparison()

            compare_profiles.on_value_change(lambda _: update_comparison_profiles())
            for control in (
                compare_search,
                compare_baseline,
                compare_mode,
                compare_groups,
                include_meta,
            ):
                control.on_value_change(lambda _: render_comparison())

            def export_comparison() -> None:
                profiles = list(compare_profiles.value or [])
                if compare_baseline.value in profiles:
                    profiles = [compare_baseline.value] + [
                        profile for profile in profiles if profile != compare_baseline.value
                    ]
                if len(profiles) < 2:
                    ui.notify("Choose at least two profiles", type="warning")
                    return
                try:
                    selected = [parse_selector(selector) for selector in profiles]
                    catalog_profiles = [workbench.catalog.select(selector) for selector in selected]
                    labels = [
                        selector.label or profile.name
                        for selector, profile in zip(selected, catalog_profiles, strict=True)
                    ]
                    if compare_mode.value == "overrides":
                        data = workbench.comparison_view(
                            profiles,
                            mode="overrides",
                            include_meta=bool(include_meta.value),
                            key_pattern=str(compare_search.value or "") or None,
                            groups=set(compare_groups.value or []) or None,
                            only_different=True,
                        )
                        report = ComparisonReport(
                            labels=tuple(labels),
                            profiles=tuple(
                                workbench.resolver.resolve(profile) for profile in catalog_profiles
                            ),
                            rows=tuple(
                                ComparisonRow(
                                    key=row["key"],
                                    group=row["group"],
                                    cells=tuple(
                                        ComparisonCell(
                                            value=cell["value"],
                                            source=cell["source"],
                                            explicit=cell["explicit"],
                                            present=cell["present"],
                                        )
                                        for cell in row["cells"]
                                    ),
                                )
                                for row in data["rows"]
                            ),
                            mode="overrides",
                        )
                    else:
                        report = collect_comparison(
                            catalog_profiles,
                            workbench.resolver,
                            labels,
                            mode=str(compare_mode.value),
                            include_meta=bool(include_meta.value),
                            key_pattern=str(compare_search.value or "") or None,
                            groups=set(compare_groups.value or []) or None,
                            only_different=True,
                        )
                    path = Path(str(export_path.value or "")).expanduser().resolve()
                    if export_format.value == "csv":
                        write_csv(path, report, bool(export_sources.value))
                    else:
                        write_html(path, report, bool(export_sources.value))
                    ui.notify(f"Wrote {path}", type="positive")
                except Exception as exc:
                    ui.notify(str(exc), type="negative", multi_line=True)

            export_button.on_click(export_comparison)

        with ui.tab_panel(lineage_tab):
            with ui.column().classes("w-full gap-4"):
                with ui.row().classes("ft-card p-4 w-full items-end gap-3"):
                    lineage_select = ui.select(
                        state.options,
                        label="Profile",
                        with_input=True,
                        new_value_mode="add-unique",
                    ).classes("flex-grow")
                    lineage_load = ui.button("Show lineage", icon="account_tree").props(
                        'data-testid="lineage-load"'
                    )
                    lineage_all = ui.button("Show all descendants", icon="unfold_more").props(
                        "outline"
                    )
                    lineage_problems = ui.button("Problems", icon="warning").props("outline")
                ui.label(
                    "Loads only the selected profile, its complete ancestor chain, and immediate dependents. Select a child to continue down that branch."
                ).classes("ft-muted text-sm")
                with ui.row().classes("w-full gap-4 items-start ft-responsive-row"):
                    with ui.column().classes("ft-card p-4 w-full max-w-md"):
                        ui.label("ANCESTORS").classes("ft-kicker")
                        lineage_ancestors = ui.column().classes("w-full gap-1")
                        ui.label("CHILDREN / DEPENDENTS").classes("ft-kicker mt-3")
                        lineage_children = ui.aggrid(
                            {
                                "columnDefs": [
                                    {"headerName": "Profile", "field": "name", "flex": 1},
                                    {
                                        "headerName": "Children",
                                        "field": "child_count",
                                        "width": 100,
                                    },
                                ],
                                "rowData": [],
                            },
                            theme="quartz",
                        ).classes("w-full h-80")
                    with ui.column().classes("ft-card p-4 flex-grow min-w-0"):
                        lineage_heading = ui.label("Choose a profile").classes("text-lg font-bold")
                        lineage_badge = ui.label().classes("ft-stat self-start")
                        lineage_details = ui.code("{}", language="json").classes("ft-code w-full")

            def render_lineage(selector: Optional[str] = None) -> None:
                selected = selector or (str(lineage_select.value) if lineage_select.value else "")
                if not selected:
                    ui.notify("Choose a profile", type="warning")
                    return
                try:
                    context = workbench.lineage_context(selected)
                    lineage_select.value = context["selected"]["path"]
                    lineage_heading.text = context["selected"]["name"]
                    lineage_badge.text = (
                        f"{context['selected']['status']} · "
                        f"{context['selected']['app']} / {context['selected']['source_kind']}"
                    )
                    lineage_ancestors.clear()
                    with lineage_ancestors:
                        if not context["ancestors"]:
                            ui.label("This profile has no parent.").classes("ft-muted")
                        for index, node in enumerate(context["ancestors"], start=1):
                            ui.button(
                                f"{index}. {node['name']}",
                                on_click=lambda path=node["path"]: render_lineage(path),
                            ).props("flat no-caps align=left").classes("w-full")
                    lineage_children.options["rowData"] = context["children"]
                    lineage_children.update()
                    lineage_details.content = json.dumps(
                        {
                            "path": context["selected"]["path"],
                            "inherits": context["selected"]["parent_name"],
                            "immediate_dependents": context["children_total"],
                            "problem": context["selected"].get("error"),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    lineage_details.update()
                except Exception as exc:
                    ui.notify(str(exc), type="negative", multi_line=True)

            def select_lineage_child(event: events.GenericEventArguments) -> None:
                data = event.args.get("data", {}) if isinstance(event.args, dict) else {}
                if data.get("path"):
                    render_lineage(str(data["path"]))

            def show_all_descendants() -> None:
                if not lineage_select.value:
                    ui.notify("Choose a profile", type="warning")
                    return
                try:
                    graph = workbench.lineage_descendants(str(lineage_select.value))
                    lineage_children.options["rowData"] = [
                        node for node in graph["nodes"] if node["path"] != lineage_select.value
                    ]
                    lineage_children.update()
                    lineage_details.content = json.dumps(
                        {
                            "descendants_loaded": len(graph["nodes"]) - 1,
                            "truncated": graph["truncated"],
                            "limit": graph["limit"],
                        },
                        indent=2,
                    )
                    lineage_details.update()
                except Exception as exc:
                    ui.notify(str(exc), type="negative", multi_line=True)

            def show_lineage_problems() -> None:
                try:
                    graph = workbench.lineage_view()
                    problems = [node for node in graph["nodes"] if node["status"] == "broken"]
                    lineage_children.options["rowData"] = problems
                    lineage_children.update()
                    lineage_heading.text = "Lineage problems"
                    lineage_badge.text = f"{len(problems)} broken or cyclic profiles"
                except Exception as exc:
                    ui.notify(str(exc), type="negative", multi_line=True)

            lineage_load.on_click(lambda: render_lineage())
            lineage_children.on("rowClicked", select_lineage_child)
            lineage_all.on_click(show_all_descendants)
            lineage_problems.on_click(show_lineage_problems)

        with ui.tab_panel(compose_tab):
            with ui.column().classes("w-full gap-4"):
                with ui.column().classes("ft-card p-4 w-full"):
                    ui.label("COMPOSITION SOURCES").classes("ft-kicker")
                    with ui.row().classes("w-full items-end gap-3"):
                        starting_source = (
                            ui.select(
                                state.options,
                                label="Starting profile",
                                with_input=True,
                                new_value_mode="add-unique",
                            )
                            .classes("min-w-64 flex-grow")
                            .props('data-testid="starting-profile"')
                        )
                        reference_sources = (
                            ui.select(
                                state.options,
                                label="Reference profiles",
                                multiple=True,
                                with_input=True,
                                new_value_mode="add-unique",
                            )
                            .classes("min-w-64 flex-grow")
                            .props('data-testid="reference-profiles"')
                        )
                        load_sources = ui.button("Load sources", icon="playlist_add_check").props(
                            'data-testid="load-sources"'
                        )
                    ui.label(
                        "Unselected settings come from the starting profile. Donor cells identify an ancestor only when the effective value is inherited."
                    ).classes("ft-muted text-sm")
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    composition_search = ui.input(
                        label="Search settings", placeholder="Name or raw key"
                    ).classes("min-w-64 flex-grow")
                    composition_group_filter = ui.select(
                        GROUP_LABELS, label="Group", clearable=True
                    ).classes("w-64")
                    composition_state = ui.label("Saved").classes("ft-status ft-ok")
                    undo_button = ui.button("Undo", icon="undo").props("outline")
                    redo_button = ui.button("Redo", icon="redo").props("outline")
                with ui.expansion("Group actions", icon="library_add_check").classes(
                    "ft-card px-4 w-full"
                ):
                    with ui.row().classes("w-full items-end gap-3"):
                        ui.label("GROUP ACTION").classes("ft-kicker")
                        group_action = ui.select(GROUP_LABELS, label="Setting group").classes(
                            "w-64"
                        )
                        group_source = ui.select({}, label="Use values from").classes("w-72")
                        apply_group = ui.button("Preview and apply group", icon="library_add_check")
                with ui.expansion("Selected setting and custom value", icon="edit").classes(
                    "ft-card px-4 w-full"
                ):
                    with ui.row().classes("w-full items-end gap-3 ft-responsive-row"):
                        ui.label("SETTING CHOICE").classes("ft-kicker")
                        with ui.column().classes("gap-0 min-w-64"):
                            active_setting = ui.label("Select a setting row").classes("font-bold")
                            active_value = ui.label().classes("ft-muted text-sm break-all")
                            active_help = ui.label().classes("ft-muted text-xs")
                        choice_source = ui.select({}, label="Value source").classes("w-72")
                        custom_value = ui.textarea(
                            label="Custom JSON value", placeholder='e.g. ["260"] or true'
                        ).classes("min-w-64 flex-grow")
                        apply_choice = ui.button("Apply custom/removal", icon="check")
                with ui.column().classes("ft-card p-4 w-full min-w-0"):
                    composition_summary = ui.label("Load a starting profile.").classes("ft-muted")
                    ui.label(
                        "Choose a donor by clicking its value cell. Mint identifies the value source; amber identifies removal. Ancestor provenance appears only for inherited values."
                    ).classes("ft-muted text-sm")
                    composition_grid = (
                        ui.aggrid(
                            {"columnDefs": [], "rowData": [], "animateRows": False},
                            theme="quartz",
                            auto_size_columns=False,
                        )
                        .classes("ft-grid")
                        .props('data-testid="composition-grid"')
                    )
                    composition_grid.options.update(
                        {
                            ":getRowId": "params => params.data.key",
                            ":onCellClicked": _composition_scroll_capture_handler(
                                composition_grid.id
                            ),
                            "suppressScrollOnNewData": True,
                        }
                    )

        with ui.tab_panel(build_tab):
            with ui.row().classes("w-full gap-4 items-start ft-responsive-row"):
                with ui.column().classes("ft-card p-4 w-full max-w-lg"):
                    ui.label("OUTPUT POLICY").classes("ft-kicker")
                    with ui.row().classes("w-full gap-2 flex-wrap"):
                        dirty_badge = ui.label("Saved").classes("ft-status ft-ok")
                        preview_badge = ui.label("Changes not previewed").classes(
                            "ft-status ft-warning"
                        )
                    output_name = (
                        ui.input(label="Output profile name")
                        .classes("w-full")
                        .props('data-testid="output-name"')
                    )
                    output_mode = (
                        ui.toggle(
                            {
                                "sparse": "Sparse inherited profile",
                                "root": "Full AMS-compatible profile",
                            },
                            value="sparse",
                        )
                        .classes("w-full")
                        .props('data-testid="output-mode"')
                    )
                    sparse_parent = (
                        ui.select(
                            state.options,
                            label="Sparse inheritance parent",
                            with_input=True,
                            new_value_mode="add-unique",
                        )
                        .classes("w-full")
                        .props('data-testid="sparse-parent"')
                    )
                    sparse_help = ui.label(
                        "Sparse output inherits material identity and unchanged behavior from its parent."
                    ).classes("ft-muted text-sm")
                    ui.icon("info", size="xs").tooltip(
                        "Sparse profiles store only differences and cannot remove a value supplied by their parent."
                    )
                    root_controls = ui.column().classes("w-full gap-2")
                    with root_controls:
                        ui.label(
                            "Full output has no parent. AMS identity and exact printer compatibility are required."
                        ).classes("ft-muted text-sm")
                        material_intent = ui.radio(
                            {
                                "same": "Same physical material as the starting profile",
                                "new": "A new physical material",
                            },
                            value="same",
                        ).classes("w-full")
                        material_name = ui.input(
                            label="Material family name",
                            placeholder="e.g. My PETG",
                        ).classes("w-full")
                        ui.icon("info", size="xs").tooltip(
                            "filament_id identifies a material family in Bambu Studio; generated family variants share one ID."
                        )
                        with ui.expansion(
                            "Material identity (Advanced)", icon="fingerprint"
                        ).classes("w-full"):
                            identity_mode = ui.select(
                                {
                                    "inherit": "Retain starting material ID",
                                    "reuse": "Reuse matching ID or generate",
                                    "generate": "Generate Bambu-compatible ID",
                                    "explicit": "Use explicit ID",
                                },
                                value="inherit",
                                label="Identity policy",
                            ).classes("w-full")
                            explicit_id = ui.input(label="Explicit filament_id").classes("w-full")
                            identity_user_id = ui.input(
                                label="Optional identity namespace",
                                password=True,
                                password_toggle_button=True,
                            ).classes("w-full")
                        printer_search = ui.input(
                            label="Find exact printer presets",
                            placeholder="Search indexed machine presets",
                        ).classes("w-full")
                        printer_search_count = ui.label().classes("ft-muted text-xs")
                        compatibility = ui.select(
                            {},
                            label="Compatible printer presets",
                            multiple=True,
                            with_input=True,
                            new_value_mode="add-unique",
                        ).classes("w-full")
                        ui.icon("info", size="xs").tooltip(
                            "Use exact machine preset names. Source compatibility is filled when sources are loaded."
                        )
                        with ui.expansion(
                            "Material family variants (Advanced)", icon="hub"
                        ).classes("w-full"):
                            ui.label(
                                "Each variant creates one full profile with the shared material identity."
                            ).classes("ft-muted text-sm")
                            variants_container = ui.column().classes("w-full gap-2")
                            add_variant_button = ui.button("Add family variant", icon="add")
                    preview_button = (
                        ui.button("Preview and validate", icon="fact_check")
                        .classes("w-full")
                        .props('data-testid="preview-output"')
                    )
                    project_name = ui.input(label="Project name").classes("w-full")
                    project_path = ui.input(label="Composition project path").classes("w-full")
                    with ui.row().classes("w-full gap-2"):
                        save_project_button = ui.button("Save project", icon="save").props(
                            "outline"
                        )
                        save_project_as_button = ui.button("Save project as", icon="save_as").props(
                            "outline"
                        )
                        load_project_button = ui.button("Load project", icon="folder_open").props(
                            "outline"
                        )
                        recover_project_button = ui.button(
                            "Recover browser draft", icon="restore"
                        ).props("outline")
                with ui.column().classes("ft-card p-4 flex-grow min-w-0"):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("GENERATED PROFILE").classes("ft-kicker")
                        build_status = (
                            ui.label("No preview yet.")
                            .classes("ft-muted")
                            .props('role="status" aria-live="polite"')
                        )
                    issues_container = (
                        ui.column()
                        .classes("w-full gap-1")
                        .props('role="status" aria-live="polite"')
                    )
                    change_summary = ui.column().classes("w-full gap-1")
                    with ui.expansion("Generated JSON (Advanced)", icon="data_object").classes(
                        "w-full"
                    ):
                        output_json = (
                            ui.code("{}", language="json")
                            .classes("ft-code w-full")
                            .props(
                                'data-testid="generated-json" aria-label="Generated profile JSON" '
                                'data-copy-label="Copy generated JSON"'
                            )
                        )
                    output_path = ui.input(
                        label="Output JSON path, or directory for a family"
                    ).classes("w-full")
                    write_button = ui.button("Write generated profile", icon="download").props(
                        "outline"
                    )
                    write_button.disable()
                    ui.separator()
                    ui.label("INSTALLATION").classes("ft-kicker")
                    with ui.row().classes("w-full gap-3"):
                        install_app = ui.select(
                            {"bambu": "Bambu Studio", "orca": "OrcaSlicer"},
                            value="bambu",
                            label="Application",
                        ).classes("w-48")
                        install_action = ui.select(
                            {
                                "create": "Create new",
                                "update": "Update with backup",
                                "uninstall": "Uninstall with backup",
                            },
                            value="create",
                            label="Action",
                        ).classes("w-48")
                        user_folder = ui.input(
                            label="User folder",
                            placeholder="Auto-detect active slicer account",
                        ).classes("w-64")
                        config_dir = ui.input(label="Application data directory").classes(
                            "flex-grow"
                        )
                    with ui.row().classes("w-full gap-2"):
                        plan_button = ui.button("Preview install plan", icon="route").props(
                            "outline"
                        )
                        plan_button.disable()
                        install_button = ui.button("Install", icon="publish")
                        install_button.disable()
                    install_output = (
                        ui.code("No installation planned.")
                        .classes("ft-code w-full")
                        .props('role="status" aria-live="polite"')
                    )

    def update_workspace_state() -> None:
        dirty_text = "Unsaved changes" if state.dirty else "Saved"
        dirty_classes = "ft-status ft-warning" if state.dirty else "ft-status ft-ok"
        for badge in (composition_state, dirty_badge):
            badge.text = dirty_text
            badge.classes(replace=dirty_classes)
        if state.preview_revision == state.revision:
            preview_badge.text = "Current preview" if state.preview_valid else "Validation failed"
            preview_badge.classes(
                replace="ft-status ft-ok" if state.preview_valid else "ft-status ft-danger"
            )
        else:
            preview_badge.text = "Changes not previewed"
            preview_badge.classes(replace="ft-status ft-warning")
        undo_button.set_enabled(bool(state.undo_stack))
        redo_button.set_enabled(bool(state.redo_stack))
        undo_button.text = f"Undo {state.last_action}" if state.undo_stack else "Undo"
        redo_button.text = "Redo" if state.redo_stack else "Redo"
        status_label.text = f"{len(state.selections)} choices · " + (
            "Unsaved changes" if state.dirty else "Saved workspace"
        )
        if core.loop is not None:
            ui.run_javascript(f"window.__filamentToolsDirty = {str(state.dirty).lower()};")

    def invalidate_install_plan() -> None:
        state.install_plan_revision = None
        state.pending_plan = None
        install_button.disable()
        install_output.content = "Installation plan is stale. Preview it again."
        install_output.update()

    def invalidate_recipe(action: str) -> None:
        state.revision += 1
        state.preview_revision = None
        state.preview_valid = False
        state.preview_artifacts = []
        build_status.text = "Changes not previewed."
        output_json.content = "{}"
        output_json.update()
        issues_container.clear()
        change_summary.clear()
        write_button.disable()
        plan_button.disable()
        invalidate_install_plan()
        state.last_action = action
        update_workspace_state()
        try:
            recipe = make_recipe()
            payload = json.dumps(recipe.model_dump(mode="json"), ensure_ascii=False)
            if core.loop is not None:
                ui.run_javascript(
                    "localStorage.setItem('filament-tools-recovery-v1', "
                    + json.dumps(payload)
                    + ");"
                )
        except Exception:
            pass

    def is_family_output() -> bool:
        return str(output_mode.value) == OutputMode.ROOT.value and bool(variant_rows)

    def sync_destination_defaults(profile_name: str, *, include_project_name: bool = True) -> None:
        profile = profile_name.strip()
        if not profile:
            return
        if include_project_name and project_name_seed.should_replace(str(project_name.value or "")):
            suggested_project = suggest_project_name(profile)
            project_name.value = suggested_project
            project_name_seed.record(suggested_project)
        active_project_name = str(project_name.value or "").strip()
        if active_project_name and project_path_seed.should_replace(str(project_path.value or "")):
            suggested_project_path = str(
                suggest_project_path(active_project_name, state.project_directory)
            )
            project_path.value = suggested_project_path
            project_path_seed.record(suggested_project_path)
        if output_path_seed.should_replace(str(output_path.value or "")):
            suggested_output = str(
                suggest_output_path(
                    profile,
                    state.output_directory,
                    family=is_family_output(),
                )
            )
            output_path.value = suggested_output
            output_path_seed.record(suggested_output)
        if material_name_seed.should_replace(str(material_name.value or "")):
            suggested_material = suggest_project_name(profile)
            material_name.value = suggested_material
            material_name_seed.record(suggested_material)

    def persist_destination_directories() -> None:
        if core.loop is None:
            return
        payload = json.dumps(
            {
                "project": str(state.project_directory),
                "output": str(state.output_directory),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        ui.run_javascript(
            "localStorage.setItem("
            + json.dumps(DESTINATION_DIRECTORIES_STORAGE_KEY)
            + ", "
            + json.dumps(payload)
            + ");"
        )

    async def restore_destination_directories() -> None:
        try:
            stored = await ui.run_javascript(
                "localStorage.getItem(" + json.dumps(DESTINATION_DIRECTORIES_STORAGE_KEY) + ")"
            )
            payload = json.loads(str(stored)) if stored else {}
            if not isinstance(payload, dict):
                return
            project_directory = Path(str(payload.get("project") or "")).expanduser()
            output_directory = Path(str(payload.get("output") or "")).expanduser()
            if project_directory.is_dir():
                state.project_directory = project_directory.resolve()
            if output_directory.is_dir():
                state.output_directory = output_directory.resolve()
            sync_destination_defaults(str(output_name.value or ""))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return

    ui.add_body_html(
        """
        <script>
        window.__filamentToolsDirty = false;
        window.addEventListener('beforeunload', event => {
          if (window.__filamentToolsDirty) { event.preventDefault(); event.returnValue = ''; }
        });
        const labelCopyButtons = () => document.querySelectorAll('[data-copy-label]').forEach(root => {
          const button = root.querySelector('button');
          if (button) button.setAttribute('aria-label', root.dataset.copyLabel);
        });
        new MutationObserver(labelCopyButtons).observe(document.body, {childList: true, subtree: true});
        labelCopyButtons();
        </script>
        """
    )

    with ui.dialog() as quick_start_dialog, ui.card().classes("w-full max-w-2xl"):
        ui.label("Create a filament profile").classes("text-xl font-bold")
        ui.label(
            "Combine settings from existing profiles, then validate the result before saving or installing it."
        ).classes("ft-muted")
        for number, title, detail in (
            (
                1,
                "Choose a starting profile",
                "This supplies every setting unless you explicitly replace it.",
            ),
            (
                2,
                "Add reference profiles",
                "Add profiles whose settings you want to compare or reuse.",
            ),
            (
                3,
                "Compare the differences",
                "Hide unchanged settings so the meaningful choices are easier to find.",
            ),
            (
                4,
                "Choose the settings you want",
                "Keep the starting value or select a value from any reference profile.",
            ),
            (
                5,
                "Choose an output type",
                "Sparse profiles inherit from a parent. Full profiles are standalone and require material identity and printer compatibility.",
            ),
            (
                6,
                "Preview before writing",
                "Validate the profile and review its installation destination. Nothing is written until you choose Install.",
            ),
        ):
            with ui.row().classes("w-full items-start gap-3"):
                ui.label(str(number)).classes("ft-stat")
                with ui.column().classes("gap-0"):
                    ui.label(title).classes("font-bold")
                    ui.label(detail).classes("ft-muted text-sm")
        with ui.expansion("Terms and edge cases", icon="menu_book").classes("w-full"):
            ui.markdown(
                """
- **Raw** is explicit JSON; **effective** includes inherited values; **overrides** compares explicit child values with the parent.
- **Sparse** output cannot remove a setting supplied by its parent. Use full output when intentional removal is required.
- **Material identity** (`filament_id`) groups compatible full presets into one AMS material family.
- Printer compatibility values must exactly match slicer machine-preset names.
"""
            )
        with ui.row().classes("w-full justify-end"):
            dismiss_quick_start = ui.button("Start exploring", icon="check")

    def dismiss_walkthrough() -> None:
        if core.loop is not None:
            ui.run_javascript("localStorage.setItem('filament-tools-walkthrough-v1', 'seen')")
        quick_start_dialog.close()

    async def show_walkthrough_once() -> None:
        try:
            seen = await ui.run_javascript("localStorage.getItem('filament-tools-walkthrough-v1')")
            if not seen:
                quick_start_dialog.open()
        except Exception:
            return

    quick_start_button.on_click(quick_start_dialog.open)
    dismiss_quick_start.on_click(dismiss_walkthrough)
    if core.loop is not None:
        ui.timer(0.75, show_walkthrough_once, once=True)

    def refresh_printer_options() -> None:
        try:
            page = workbench.printer_options(str(printer_search.value or ""), limit=50)
            selected = [str(value) for value in compatibility.value or []]
            variant_selected = [
                str(value) for row in variant_rows for value in (row["printers"].value or [])
            ]
            names = list(dict.fromkeys([*page["results"], *selected, *variant_selected]))
            printer_option_map.clear()
            printer_option_map.update({name: name for name in names})
            compatibility.set_options(printer_option_map, value=selected)
            for row in variant_rows:
                row["printers"].set_options(
                    printer_option_map, value=list(row["printers"].value or [])
                )
            printer_search_count.text = (
                f"Showing {len(page['results'])} of {page['total']} indexed printer presets"
            )
        except Exception as exc:
            ui.notify(str(exc), type="negative")

    def remove_variant(row: Dict[str, Any]) -> None:
        row["element"].delete()
        variant_rows.remove(row)
        sync_destination_defaults(str(output_name.value or ""), include_project_name=False)
        invalidate_recipe("family variants")

    def add_variant(variant: Optional[TargetVariant] = None, *, changed: bool = True) -> None:
        with variants_container:
            element = ui.row().classes("w-full items-end gap-2 ft-responsive-row")
            with element:
                name = ui.input(
                    label="Variant profile name",
                    value=variant.name if variant else "",
                ).classes("min-w-64 flex-grow")
                selected_printers = list(variant.compatible_printers) if variant else []
                for printer in selected_printers:
                    printer_option_map.setdefault(printer, printer)
                printers = ui.select(
                    printer_option_map,
                    label="Exact compatible printers",
                    value=selected_printers,
                    multiple=True,
                    with_input=True,
                    new_value_mode="add-unique",
                ).classes("min-w-64 flex-grow")
                edits = ui.textarea(
                    label="Variant setting edits (JSON object)",
                    value=(
                        json.dumps(variant.edits, ensure_ascii=False, sort_keys=True)
                        if variant and variant.edits
                        else ""
                    ),
                    placeholder='{"filament_max_volumetric_speed":["20"]}',
                ).classes("min-w-64 flex-grow")
                remove = ui.button(icon="delete", color="negative").props(
                    'flat aria-label="Remove family variant"'
                )
        row = {"element": element, "name": name, "printers": printers, "edits": edits}
        variant_rows.append(row)
        sync_destination_defaults(str(output_name.value or ""), include_project_name=False)
        remove.on_click(lambda: remove_variant(row))
        name.on_value_change(lambda _: invalidate_recipe("family variants"))
        printers.on_value_change(lambda _: invalidate_recipe("family variants"))
        edits.on_value_change(lambda _: invalidate_recipe("family variants"))
        if changed:
            invalidate_recipe("family variants")

    def clear_variants() -> None:
        for row in list(variant_rows):
            row["element"].delete()
        variant_rows.clear()

    def structured_variants() -> List[TargetVariant]:
        variants: List[TargetVariant] = []
        for index, row in enumerate(variant_rows, start=1):
            name = str(row["name"].value or "").strip()
            printers = [str(value) for value in row["printers"].value or []]
            if not name and not printers:
                continue
            if not name:
                raise ValueError(f"family variant {index} requires a profile name")
            if not printers:
                raise ValueError(f"family variant {index} requires compatible printers")
            try:
                edits = _variant_edits_json(str(row["edits"].value or ""))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"family variant {index}: {exc}") from exc
            variants.append(TargetVariant(name=name, compatible_printers=printers, edits=edits))
        return variants

    def populate_compatibility_from_source() -> None:
        if not starting_source.value:
            return
        try:
            source = workbench.resolver.resolve_selector(str(starting_source.value))
            compatible = source.values.get("compatible_printers", [])
            if not isinstance(compatible, list):
                return
            values = compatibility_seed.accept_source_values(
                [str(value) for value in compatibility.value or []],
                compatible,
            )
            if values is None:
                return
            for value in values:
                printer_option_map.setdefault(value, value)
            compatibility.set_options(printer_option_map, value=values)
        except Exception:
            return

    add_variant_button.on_click(lambda: add_variant())
    printer_search.on(
        "update:model-value",
        lambda _: refresh_printer_options(),
        throttle=0.35,
        leading_events=False,
        trailing_events=True,
    )

    def sync_sources_from_compare() -> None:
        values = list(compare_profiles.value or [])
        if compare_baseline.value in values:
            values = [compare_baseline.value] + [
                value for value in values if value != compare_baseline.value
            ]
        if not values and catalog_select.value:
            values = [str(catalog_select.value)]
        if not values:
            ui.notify("Select profiles in Compare or Profiles first", type="warning")
            return
        starting_source.value = values[0]
        reference_sources.value = values[1:]
        sparse_parent.value = values[0]
        tabs.value = compose_tab
        request_source_load()

    add_compare_button.on_click(
        lambda: (
            (
                setattr(
                    compare_profiles,
                    "value",
                    list(dict.fromkeys([*(compare_profiles.value or []), catalog_select.value])),
                ),
                setattr(tabs, "value", compare_tab),
            )
            if catalog_select.value
            else ui.notify("Choose a profile first", type="warning")
        )
    )
    create_from_compare.on_click(sync_sources_from_compare)

    def make_recipe() -> CompositionRecipe:
        if not starting_source.value:
            raise ValueError("choose a starting profile")
        references = [
            str(value)
            for value in (reference_sources.value or [])
            if str(value) != str(starting_source.value)
        ]
        name = str(output_name.value or "").strip()
        if not name:
            defaults = workbench.composition_defaults(
                str(starting_source.value),
                project_directory=state.project_directory,
                output_directory=state.output_directory,
                family=is_family_output(),
            )
            name = defaults["profile_name"]
            output_name.value = name
            output_name_seed.record(name)
            sync_destination_defaults(name)
        fingerprint_sources = {str(starting_source.value), *references}
        if str(output_mode.value) == OutputMode.SPARSE.value:
            fingerprint_sources.add(str(sparse_parent.value or starting_source.value))
        for selector in fingerprint_sources:
            if selector not in state.fingerprints:
                state.fingerprints[selector] = workbench.resolver.resolve_selector(
                    selector
                ).fingerprint
        is_root = str(output_mode.value) == OutputMode.ROOT.value
        selected_material_name = str(material_name.value or "").strip()
        if is_root and material_intent.value == "new" and not selected_material_name:
            raise ValueError("a new physical material requires a material family name")
        return CompositionRecipe(
            name=name,
            starting_source=str(starting_source.value),
            reference_sources=references,
            sparse_parent=str(sparse_parent.value or starting_source.value),
            output_mode=OutputMode(str(output_mode.value)),
            selections=state.selections,
            compatible_printers=(
                [str(value) for value in compatibility.value or []] or None if is_root else None
            ),
            identity_mode=(
                IdentityMode(str(identity_mode.value)) if is_root else IdentityMode.INHERIT
            ),
            filament_id=(
                str(explicit_id.value).strip()
                if is_root
                and identity_mode.value == IdentityMode.EXPLICIT.value
                and explicit_id.value
                else None
            ),
            material_name=(selected_material_name if is_root and selected_material_name else None),
            user_id=(
                str(identity_user_id.value or "").strip()
                if is_root and identity_user_id.value
                else None
            ),
            variants=structured_variants() if is_root else [],
            fingerprints=state.fingerprints,
        )

    def refresh_composition(reset: bool = False) -> None:
        try:
            if reset:
                state.selections.clear()
                state.fingerprints.clear()
                state.undo_stack.clear()
                state.redo_stack.clear()
            recipe = make_recipe()
            data = workbench.composition_view(recipe)
            for key in data.get("redundant_selections", []):
                state.selections.pop(str(key), None)
            state.composition = data
            if reset or not state.fingerprints:
                state.fingerprints = {
                    source["selector"]: source["fingerprint"] for source in data["sources"]
                }
            source_options = {source["selector"]: source["name"] for source in data["sources"]}
            group_source.set_options(source_options)
            choice_source.set_options(
                {
                    **source_options,
                    "__custom__": "Custom JSON value",
                    "__remove__": "Remove setting",
                }
            )
            columns = [
                {
                    "headerName": "Setting",
                    "field": "setting",
                    "pinned": "left",
                    "minWidth": 240,
                    "filter": True,
                },
                {"headerName": "Group", "field": "group", "width": 150, "filter": True},
            ]
            for index, source in enumerate(data["sources"]):
                columns.append(_composition_source_column(source["name"], index))
            columns.extend(
                [
                    _composition_result_column(),
                    {"headerName": "Starting → result", "field": "change", "minWidth": 220},
                    {"headerName": "Value source", "field": "value_source", "width": 170},
                ]
            )
            rows = []
            for row in data["rows"]:
                if (
                    composition_search.value
                    and str(composition_search.value).casefold() not in row["key"].casefold()
                ):
                    continue
                if (
                    composition_group_filter.value
                    and row["group"] != composition_group_filter.value
                ):
                    continue
                item = {
                    "key": row["key"],
                    "setting": _setting_label(row),
                    "group": row["group_label"],
                }
                for index, cell in enumerate(row["cells"]):
                    item[f"source_{index}"] = _composition_source_text(cell)
                    item[f"_source_selected_{index}"] = (
                        row["result"]["selected_selector"] == cell["selector"]
                    )
                result = row["result"]
                item["_result_state"] = (
                    result["selection_kind"]
                    if result["selection_kind"] in {"custom", "remove"}
                    else ""
                )
                item["result"] = (
                    "Removed"
                    if result["selection_kind"] == "remove"
                    else _display(result["value"], result["present"])
                )
                item["value_source"] = result["selected_via"] or "Removed"
                starting = row["cells"][0]
                before = _display(starting["value"], starting["present"])
                after = _display(result["value"], result["present"])
                item["change"] = "Unchanged" if before == after else f"{before} → {after}"
                rows.append(item)
            _update_composition_grid(composition_grid, columns, rows, reset=reset)
            composition_summary.text = (
                f"{len(rows)} visible settings · {len(state.selections)} explicit choices"
            )
            if state.active_key:
                selected_row = next(
                    (row for row in data["rows"] if row["key"] == state.active_key), None
                )
                if selected_row:
                    active_value.text = "Current result: " + _display(
                        selected_row["result"]["value"],
                        selected_row["result"]["present"],
                    )
                else:
                    state.active_key = None
                    active_setting.text = "Select a setting row"
                    active_value.text = ""
                    active_help.text = ""
            update_workspace_state()
        except Exception as exc:
            ui.notify(str(exc), type="negative", multi_line=True)

    with ui.dialog() as replace_sources_dialog, ui.card().classes("w-full max-w-lg"):
        ui.label("Replace composition sources?").classes("text-lg font-bold")
        ui.label(
            "Loading different sources clears explicit setting choices and undo history."
        ).classes("ft-muted")
        with ui.row().classes("w-full justify-end"):
            ui.button("Keep current work", on_click=replace_sources_dialog.close).props("flat")
            confirm_replace_sources = ui.button("Replace sources", icon="playlist_add_check")

    def perform_source_load() -> None:
        replace_sources_dialog.close()
        replace_output_name = output_name_seed.should_replace(str(output_name.value or ""))
        if replace_output_name:
            defaults = workbench.composition_defaults(
                str(starting_source.value),
                project_directory=state.project_directory,
                output_directory=state.output_directory,
                family=is_family_output(),
            )
            output_name.value = defaults["profile_name"]
            output_name_seed.record(defaults["profile_name"])
            if project_name_seed.should_replace(str(project_name.value or "")):
                project_name.value = defaults["project_name"]
                project_name_seed.record(defaults["project_name"])
            if project_path_seed.should_replace(str(project_path.value or "")):
                project_path.value = defaults["project_path"]
                project_path_seed.record(defaults["project_path"])
            if output_path_seed.should_replace(str(output_path.value or "")):
                output_path.value = defaults["output_path"]
                output_path_seed.record(defaults["output_path"])
            if install_app_seed.should_replace(str(install_app.value or "")):
                install_app.value = defaults["application"]
                install_app_seed.record(defaults["application"])
        refresh_composition(reset=True)
        sync_destination_defaults(str(output_name.value or ""))
        populate_compatibility_from_source()
        invalidate_recipe("source change")

    def request_source_load() -> None:
        if state.selections:
            replace_sources_dialog.open()
        else:
            perform_source_load()

    load_sources.on_click(request_source_load)
    confirm_replace_sources.on_click(perform_source_load)
    composition_search.on_value_change(lambda _: refresh_composition())
    composition_group_filter.on_value_change(lambda _: refresh_composition())

    def select_composition_row(event: events.GenericEventArguments) -> None:
        args = event.args if isinstance(event.args, dict) else {}
        data = args.get("data", {})
        key = data.get("key")
        if not key or not state.composition:
            return
        state.active_key = str(key)
        active_setting.text = str(key)
        row = next(row for row in state.composition["rows"] if row["key"] == key)
        metadata = row.get("metadata", {})
        active_setting.text = _setting_label(row).replace("\n", " · ")
        active_help.text = " · ".join(
            value
            for value in (
                str(metadata.get("description") or ""),
                f"Unit: {metadata['unit']}" if metadata.get("unit") else "",
            )
            if value
        )
        active_value.text = (
            f"Current result: {_display(row['result']['value'], row['result']['present'])}"
        )
        choice = state.selections.get(str(key))
        if choice is None:
            choice_source.value = str(starting_source.value)
            custom_value.value = ""
        elif choice.kind == ChoiceKind.SOURCE:
            choice_source.value = choice.source
            custom_value.value = ""
        elif choice.kind == ChoiceKind.REMOVE:
            choice_source.value = "__remove__"
            custom_value.value = ""
        else:
            choice_source.value = "__custom__"
            custom_value.value = json.dumps(choice.value, ensure_ascii=False)
        column = args.get("column")
        nested_column_id = column.get("colId") if isinstance(column, dict) else None
        column_id = str(args.get("colId") or nested_column_id or "")
        if column_id.startswith("source_"):
            try:
                source_index = int(column_id.removeprefix("source_"))
                selector = str(state.composition["sources"][source_index]["selector"])
                state.checkpoint(f"{key} donor selection")
                if selector == str(starting_source.value):
                    state.selections.pop(str(key), None)
                else:
                    state.selections[str(key)] = CompositionChoice(
                        kind=ChoiceKind.SOURCE, source=selector
                    )
                invalidate_recipe(f"{key} donor selection")
                refresh_composition()
            except (IndexError, ValueError) as exc:
                ui.notify(str(exc), type="negative")

    composition_grid.on("cellClicked", select_composition_row)

    def apply_setting_choice() -> None:
        if not state.active_key:
            ui.notify("Select a setting row", type="warning")
            return
        try:
            state.checkpoint(f"{state.active_key} choice")
            selected = str(choice_source.value or "")
            if selected == str(starting_source.value):
                state.selections.pop(state.active_key, None)
            elif selected == "__custom__":
                state.selections[state.active_key] = CompositionChoice(
                    kind=ChoiceKind.CUSTOM,
                    value=json.loads(str(custom_value.value)),
                )
            elif selected == "__remove__":
                state.selections[state.active_key] = CompositionChoice(kind=ChoiceKind.REMOVE)
            elif selected:
                state.selections[state.active_key] = CompositionChoice(
                    kind=ChoiceKind.SOURCE, source=selected
                )
            else:
                raise ValueError("choose a value source")
            invalidate_recipe(f"{state.active_key} choice")
            refresh_composition()
        except Exception as exc:
            if state.undo_stack:
                state.selections = state.undo_stack.pop()
            ui.notify(str(exc), type="negative")

    apply_choice.on_click(apply_setting_choice)

    def apply_group_choice() -> None:
        if not state.composition or not group_action.value or not group_source.value:
            ui.notify("Choose a group and donor source", type="warning")
            return
        matching_rows = [
            row for row in state.composition["rows"] if row["group"] == str(group_action.value)
        ]
        state.checkpoint(f"{GROUP_LABELS[str(group_action.value)]} group")
        selector = str(group_source.value)
        changed = 0
        for row in state.composition["rows"]:
            if row["group"] != str(group_action.value):
                continue
            donor = next((cell for cell in row["cells"] if cell["selector"] == selector), None)
            if donor and donor["present"]:
                if selector == str(starting_source.value):
                    state.selections.pop(row["key"], None)
                else:
                    state.selections[row["key"]] = CompositionChoice(
                        kind=ChoiceKind.SOURCE, source=selector
                    )
                changed += 1
        invalidate_recipe(f"{GROUP_LABELS[str(group_action.value)]} group")
        refresh_composition()
        ui.notify(
            f"Applied {changed} of {len(matching_rows)} "
            f"{GROUP_LABELS[str(group_action.value)]} settings"
        )

    with ui.dialog() as group_dialog, ui.card().classes("w-full max-w-lg"):
        ui.label("Apply donor to setting group?").classes("text-lg font-bold")
        group_preview_text = ui.label().classes("ft-muted")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=group_dialog.close).props("flat")
            confirm_group = ui.button("Apply group", icon="library_add_check")

    def preview_group_choice() -> None:
        if not state.composition or not group_action.value or not group_source.value:
            ui.notify("Choose a group and donor source", type="warning")
            return
        selector = str(group_source.value)
        rows = [row for row in state.composition["rows"] if row["group"] == group_action.value]
        applicable = sum(
            1
            for row in rows
            if any(cell["selector"] == selector and cell["present"] for cell in row["cells"])
        )
        donor_name = next(
            (
                source["name"]
                for source in state.composition["sources"]
                if source["selector"] == selector
            ),
            selector,
        )
        group_preview_text.text = (
            f"{applicable} of {len(rows)} {GROUP_LABELS[str(group_action.value)]} "
            f"settings will use values from {donor_name}."
        )
        group_dialog.open()

    apply_group.on_click(preview_group_choice)
    confirm_group.on_click(lambda: (group_dialog.close(), apply_group_choice()))

    def undo() -> None:
        if not state.undo_stack:
            return
        state.redo_stack.append(copy.deepcopy(state.selections))
        state.selections = state.undo_stack.pop()
        invalidate_recipe("undo")
        refresh_composition()

    def redo() -> None:
        if not state.redo_stack:
            return
        state.undo_stack.append(copy.deepcopy(state.selections))
        state.selections = state.redo_stack.pop()
        invalidate_recipe("redo")
        refresh_composition()

    undo_button.on_click(undo)
    redo_button.on_click(redo)

    def show_issues(issues: List[Dict[str, Any]]) -> None:
        issues_container.clear()
        with issues_container:
            if not issues:
                ui.label("No validation issues.").classes("ft-stat self-start")
            for issue in issues:
                color = "negative" if issue["severity"] == "error" else "warning"
                with ui.banner().props(f"dense rounded {color}").classes("w-full"):
                    ui.label(f"{issue['severity'].upper()} · {issue['code']}").classes("font-bold")
                    ui.label(issue["message"])

    def preview_output() -> None:
        try:
            recipe = make_recipe()
            artifacts = workbench.build_recipe(recipe)
            issues = workbench.validate_recipe(recipe, artifacts)
            show_issues([issue.model_dump(mode="json") for issue in issues])
            output_json.content = "\n\n".join(
                json.dumps(artifact.data, ensure_ascii=False, indent=2, sort_keys=True)
                for artifact in artifacts
            )
            output_json.update()
            build_status.text = f"{len(artifacts)} artifact(s) · {len(issues)} issue(s)"
            change_summary.clear()
            with change_summary:
                ui.label(
                    "Sparse inherited profile"
                    if recipe.output_mode == OutputMode.SPARSE
                    else "Full AMS-compatible profile"
                ).classes("font-bold")
                for artifact in artifacts:
                    ui.label(
                        f"{artifact.name}: {len(artifact.changed_keys)} changed settings"
                    ).classes("ft-muted")
            state.preview_revision = state.revision
            state.preview_valid = not has_errors(issues)
            state.preview_artifacts = artifacts
            write_button.set_enabled(state.preview_valid)
            plan_button.set_enabled(state.preview_valid)
            invalidate_install_plan()
            update_workspace_state()
        except Exception as exc:
            state.preview_revision = state.revision
            state.preview_valid = False
            state.preview_artifacts = []
            build_status.text = str(exc)
            write_button.disable()
            plan_button.disable()
            invalidate_install_plan()
            update_workspace_state()
            ui.notify(str(exc), type="negative", multi_line=True)

    preview_button.on_click(preview_output)

    def write_output() -> None:
        try:
            if state.preview_revision != state.revision or not state.preview_valid:
                raise ValueError("preview and validate the current changes before writing")
            artifacts = state.preview_artifacts
            if len(artifacts) == 1:
                paths = [write_artifact(artifacts[0], str(output_path.value or ""))]
                state.output_directory = Path(paths[0]).parent
            else:
                paths = write_artifacts(artifacts, str(output_path.value or ""))
                state.output_directory = Path(str(output_path.value)).expanduser().resolve()
            persist_destination_directories()
            ui.notify("Wrote " + ", ".join(paths), type="positive", multi_line=True)
        except Exception as exc:
            ui.notify(str(exc), type="negative", multi_line=True)

    write_button.on_click(write_output)

    def save_recipe_project(*, save_as: bool = False) -> None:
        try:
            requested = Path(str(project_path.value or "")).expanduser().resolve()
            replace = not save_as and state.current_project_path == requested
            if not save_as and state.current_project_path is not None and not replace:
                raise ValueError("The project path changed; use Save project as")
            name = str(project_name.value or "").strip()
            if not name:
                raise ValueError("project name cannot be empty")
            path = save_composition_project(
                requested,
                make_recipe(),
                replace=replace,
                project_name=name,
            )
            state.current_project_path = path
            state.project_directory = path.parent
            project_path.value = str(path)
            project_path_seed.reset()
            persist_destination_directories()
            state.saved_revision = state.revision
            update_workspace_state()
            ui.notify(f"Saved {path}", type="positive")
        except Exception as exc:
            ui.notify(str(exc), type="negative")

    def apply_loaded_recipe(
        recipe: CompositionRecipe,
        *,
        saved: bool,
        loaded_project_name: Optional[str] = None,
    ) -> None:
        starting_source.value = recipe.starting_source
        reference_sources.value = recipe.reference_sources
        sparse_parent.value = recipe.sparse_parent or recipe.starting_source
        output_name_seed.reset()
        output_name.value = recipe.name
        project_name_seed.reset()
        project_name.value = loaded_project_name or suggest_project_name(recipe.name)
        output_mode.value = recipe.output_mode.value
        identity_mode.value = recipe.identity_mode.value
        material_intent.value = (
            "same" if recipe.identity_mode in {IdentityMode.INHERIT, IdentityMode.REUSE} else "new"
        )
        material_name_seed.reset()
        material_name.value = recipe.material_name or suggest_project_name(recipe.name)
        identity_user_id.value = recipe.user_id or ""
        explicit_id.value = recipe.filament_id or ""
        compatibility_seed.reset()
        for printer in recipe.compatible_printers or []:
            printer_option_map.setdefault(printer, printer)
        compatibility.set_options(printer_option_map, value=list(recipe.compatible_printers or []))
        clear_variants()
        for variant in recipe.variants:
            add_variant(variant, changed=False)
        state.selections = dict(recipe.selections)
        state.fingerprints = dict(recipe.fingerprints)
        refresh_composition()
        state.revision += 1
        state.saved_revision = state.revision if saved else state.revision - 1
        state.preview_revision = None
        state.preview_valid = False
        state.preview_artifacts = []
        write_button.disable()
        plan_button.disable()
        invalidate_install_plan()
        sync_destination_defaults(recipe.name)
        update_output_visibility()
        update_workspace_state()

    def load_recipe_project() -> None:
        try:
            path = Path(str(project_path.value or "")).expanduser().resolve()
            recipe, metadata = load_composition_project_document(path)
            state.current_project_path = path
            state.project_directory = path.parent
            project_path.value = str(path)
            project_path_seed.reset()
            persist_destination_directories()
            apply_loaded_recipe(
                recipe,
                saved=True,
                loaded_project_name=str(metadata.get("name") or recipe.name),
            )
            ui.notify("Composition project loaded", type="positive")
        except Exception as exc:
            ui.notify(str(exc), type="negative")

    async def recover_recipe_project() -> None:
        try:
            recovered = await ui.run_javascript(
                "localStorage.getItem('filament-tools-recovery-v1')"
            )
            if not recovered:
                raise ValueError("no browser recovery draft is available")
            recipe = CompositionRecipe.model_validate_json(str(recovered))
            state.current_project_path = None
            project_path_seed.reset()
            project_path.value = ""
            apply_loaded_recipe(recipe, saved=False)
            sync_destination_defaults(recipe.name)
            tabs.value = compose_tab
            ui.notify("Recovered the browser draft", type="positive")
        except Exception as exc:
            ui.notify(str(exc), type="negative")

    save_project_button.on_click(lambda: save_recipe_project())
    save_project_as_button.on_click(lambda: save_recipe_project(save_as=True))
    load_project_button.on_click(load_recipe_project)
    recover_project_button.on_click(recover_recipe_project)

    def installation_plan():
        if state.preview_revision != state.revision or not state.preview_valid:
            raise ValueError("preview and validate the current changes before installation")
        plan = plan_install(
            artifacts=state.preview_artifacts,
            app=str(install_app.value),
            app_data_dir=Path(str(config_dir.value)) if config_dir.value else None,
            user_folder=str(user_folder.value).strip() if user_folder.value else None,
            action=InstallAction(str(install_action.value)),
        )
        return plan

    def preview_install() -> None:
        try:
            plan = installation_plan()
            install_output.content = json.dumps(
                {
                    "valid": plan.valid,
                    "action": plan.action.value,
                    "destinations": [str(operation.destination) for operation in plan.operations],
                    "backups": [
                        str(operation.backup) for operation in plan.operations if operation.backup
                    ],
                    "issues": [issue.model_dump(mode="json") for issue in plan.issues],
                },
                ensure_ascii=False,
                indent=2,
            )
            install_output.update()
            state.pending_plan = plan
            state.install_plan_revision = state.revision
            install_button.set_enabled(plan.valid)
        except Exception as exc:
            invalidate_install_plan()
            ui.notify(str(exc), type="negative", multi_line=True)

    plan_button.on_click(preview_install)

    with ui.dialog() as install_dialog, ui.card().classes("w-full max-w-2xl"):
        install_dialog_heading = ui.label("Install generated profiles?").classes(
            "text-lg font-bold"
        )
        install_dialog_message = ui.label("").classes("ft-muted")
        install_dialog_details = ui.code("").classes("ft-code w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=install_dialog.close).props("flat")
            confirm_install = ui.button("Install profiles", icon="publish")

    def request_install() -> None:
        try:
            plan = state.pending_plan
            if plan is None or state.install_plan_revision != state.revision or not plan.valid:
                raise ValueError("preview a current, valid installation plan first")
            labels = []
            for operation in plan.operations:
                label = f"{operation.action.value}: {operation.destination}"
                if operation.backup:
                    label += f"\n  backup: {operation.backup}"
                labels.append(label)
            install_dialog_details.content = "\n".join(labels)
            install_dialog_heading.text = f"{plan.action.value.title()} reviewed profiles?"
            install_dialog_message.text = (
                "Existing profiles are preserved at the displayed backup paths."
                if plan.action != InstallAction.CREATE
                else "This creates new profile files and never overwrites existing profiles."
            )
            confirm_install.text = {
                InstallAction.CREATE: "Install profiles",
                InstallAction.UPDATE: "Update profiles",
                InstallAction.UNINSTALL: "Uninstall profiles",
            }[plan.action]
            install_dialog_details.update()
            install_dialog.open()
        except Exception as exc:
            ui.notify(str(exc), type="negative", multi_line=True)

    def confirm_installation() -> None:
        try:
            plan = state.pending_plan
            if plan is None or state.install_plan_revision != state.revision:
                raise ValueError("the installation plan is stale; preview it again")
            paths = apply_install_plan(plan)
            workbench.reload_catalog()
            refresh_catalog()
            install_dialog.close()
            state.pending_plan = None
            state.install_plan_revision = None
            install_button.disable()
            completed = {
                InstallAction.CREATE: "Installed",
                InstallAction.UPDATE: "Updated with backups",
                InstallAction.UNINSTALL: "Uninstalled with backups",
            }[plan.action]
            install_output.content = (
                completed
                + ":\n"
                + "\n".join(str(path) for path in paths)
                + "\n\nRestart the slicer to load the new profiles."
            )
            install_output.update()
            ui.notify(f"{completed}. Restart the slicer to reload profiles.", type="positive")
        except Exception as exc:
            ui.notify(str(exc), type="negative", multi_line=True)

    install_button.on_click(request_install)
    confirm_install.on_click(confirm_installation)

    def update_output_visibility() -> None:
        is_sparse = str(output_mode.value) == OutputMode.SPARSE.value
        sparse_parent.set_visibility(is_sparse)
        sparse_help.set_visibility(is_sparse)
        root_controls.set_visibility(not is_sparse)
        explicit_id.set_visibility(
            not is_sparse and identity_mode.value == IdentityMode.EXPLICIT.value
        )
        material_name.set_visibility(not is_sparse and material_intent.value == "new")
        identity_user_id.set_visibility(
            not is_sparse and identity_mode.value == IdentityMode.GENERATE.value
        )

    def output_mode_changed() -> None:
        update_output_visibility()
        sync_destination_defaults(str(output_name.value or ""), include_project_name=False)
        invalidate_recipe("output mode")

    def output_name_changed() -> None:
        sync_destination_defaults(str(output_name.value or ""))
        invalidate_recipe("profile name")

    def project_name_changed() -> None:
        if project_path_seed.should_replace(str(project_path.value or "")):
            value = str(project_name.value or "").strip()
            if value:
                suggested = str(suggest_project_path(value, state.project_directory))
                project_path.value = suggested
                project_path_seed.record(suggested)
        invalidate_recipe("project name")

    def material_intent_changed() -> None:
        expected = (
            IdentityMode.INHERIT.value
            if material_intent.value == "same"
            else IdentityMode.GENERATE.value
        )
        if identity_mode.value != expected:
            identity_mode.value = expected
        update_output_visibility()
        invalidate_recipe("material identity")

    def identity_mode_changed() -> None:
        expected_intent = (
            "same"
            if identity_mode.value in {IdentityMode.INHERIT.value, IdentityMode.REUSE.value}
            else "new"
        )
        if material_intent.value != expected_intent:
            material_intent.value = expected_intent
        update_output_visibility()
        invalidate_recipe("material identity")

    output_mode.on_value_change(lambda _: output_mode_changed())
    material_intent.on_value_change(lambda _: material_intent_changed())
    identity_mode.on_value_change(lambda _: identity_mode_changed())
    output_name.on_value_change(lambda _: output_name_changed())
    project_name.on_value_change(lambda _: project_name_changed())
    for control, action in (
        (sparse_parent, "inheritance parent"),
        (material_name, "material name"),
        (explicit_id, "material identity"),
        (identity_user_id, "material identity"),
        (compatibility, "printer compatibility"),
    ):
        control.on_value_change(lambda _, reason=action: invalidate_recipe(reason))
    for control in (install_app, install_action, user_folder, config_dir):
        control.on_value_change(lambda _: invalidate_install_plan())
    if core.loop is not None:
        ui.timer(0.35, restore_destination_directories, once=True)

    update_output_visibility()
    update_workspace_state()


def mount_workbench(app: FastAPI, workbench: ProfileWorkbench) -> None:
    """Mount the per-browser NiceGUI workbench after API routes are registered."""
    ui.run_with(
        app,
        root=lambda: render_workbench(workbench),
        title="Filament Tools Workbench",
        favicon="🧵",
        dark=WORKBENCH_DARK_MODE,
        show_welcome_message=False,
    )
