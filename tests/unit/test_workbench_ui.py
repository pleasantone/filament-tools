from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI

from filament_tools.catalog import ProfileCatalog
from filament_tools.editor.workbench_ui import (
    CatalogFilterState,
    CompatibilitySeedState,
    SeededStringState,
    _comparison_cell_text,
    _composition_result_column,
    _composition_scroll_capture_handler,
    _composition_source_column,
    _composition_source_text,
    _inherited_source_names,
    _update_composition_grid,
    mount_workbench,
)
from filament_tools.service import ProfileWorkbench
from tests.support import SRC  # noqa: F401


class CompatibilitySeedStateTests(unittest.TestCase):
    def test_replaces_an_unchanged_seed_when_source_changes(self) -> None:
        state = CompatibilitySeedState()

        first = state.accept_source_values([], ["Bambu Lab H2C 0.4 nozzle"])
        second = state.accept_source_values(first or [], ["Bambu Lab H2C 0.6 nozzle"])

        self.assertEqual(first, ["Bambu Lab H2C 0.4 nozzle"])
        self.assertEqual(second, ["Bambu Lab H2C 0.6 nozzle"])

    def test_preserves_user_edits_and_an_explicit_empty_selection(self) -> None:
        state = CompatibilitySeedState()
        state.accept_source_values([], ["Bambu Lab H2C 0.4 nozzle"])

        self.assertIsNone(
            state.accept_source_values(["Custom printer"], ["Bambu Lab H2C 0.6 nozzle"])
        )
        self.assertIsNone(state.accept_source_values([], ["Bambu Lab H2C 0.6 nozzle"]))

    def test_reset_treats_loaded_project_values_as_explicit(self) -> None:
        state = CompatibilitySeedState()
        state.accept_source_values([], ["Bambu Lab H2C 0.4 nozzle"])
        state.reset()

        self.assertIsNone(
            state.accept_source_values(
                ["Project printer"],
                ["Bambu Lab H2C 0.6 nozzle"],
            )
        )


class SeededStringStateTests(unittest.TestCase):
    def test_replaces_generated_names_but_preserves_explicit_names(self) -> None:
        state = SeededStringState()

        self.assertTrue(state.should_replace(""))
        state.record("H2C 0.4 composed")
        self.assertTrue(state.should_replace("H2C 0.4 composed"))
        self.assertFalse(state.should_replace("My PETG"))

    def test_reset_treats_loaded_project_name_as_explicit(self) -> None:
        state = SeededStringState()
        state.record("H2C 0.4 composed")
        state.reset()

        self.assertFalse(state.should_replace("Project PETG"))


class CatalogFilterStateTests(unittest.TestCase):
    def test_first_run_defaults_to_h2c_and_x1c_filaments(self) -> None:
        filters = CatalogFilterState.from_json(None)

        self.assertEqual(filters.machines, ("H2C", "X1C"))
        self.assertEqual(filters.profile_type, "filament")

    def test_persisted_filters_round_trip_including_explicitly_cleared_state(self) -> None:
        filters = CatalogFilterState(
            search="PETG",
            applications=("OrcaSlicer",),
            sources=("user",),
            material="SUNLU",
            machines=("H2C",),
            nozzle="0.4",
        )

        self.assertEqual(CatalogFilterState.from_json(filters.to_json()), filters)
        self.assertEqual(
            CatalogFilterState.from_json(CatalogFilterState.cleared().to_json()),
            CatalogFilterState.cleared(),
        )

    def test_invalid_saved_filters_fall_back_to_first_run_defaults(self) -> None:
        self.assertEqual(CatalogFilterState.from_json("not json"), CatalogFilterState())


class WorkbenchThemeTests(unittest.TestCase):
    def test_mount_forces_light_theme(self) -> None:
        workbench = ProfileWorkbench(ProfileCatalog([]))

        with patch("filament_tools.editor.workbench_ui.ui.run_with") as run_with:
            mount_workbench(FastAPI(), workbench)

        self.assertIs(run_with.call_args.kwargs["dark"], False)


class ComparisonCellTextTests(unittest.TestCase):
    def test_direct_value_omits_redundant_profile_source_and_explicit_label(self) -> None:
        text = _comparison_cell_text(
            {
                "value": ["265"],
                "source": "Fast PETG",
                "explicit": True,
                "present": True,
            },
            baseline_value=["255"],
            index=1,
            mode="effective",
        )

        self.assertEqual(text, '["265"] · Δ +10')

    def test_inherited_value_keeps_ancestor_provenance(self) -> None:
        text = _comparison_cell_text(
            {
                "value": ["255"],
                "source": "Generic PETG",
                "explicit": False,
                "present": True,
            },
            baseline_value=["255"],
            index=1,
            mode="effective",
        )

        self.assertEqual(text, '["255"]\n↳ Generic PETG · inherited')

    def test_mixed_vector_shows_only_inherited_element_sources(self) -> None:
        text = _comparison_cell_text(
            {
                "value": ["1", "2"],
                "source": "Child PETG",
                "explicit": True,
                "present": True,
                "element_sources": ["Child PETG", "Generic PETG"],
            },
            baseline_value=["1", "2"],
            index=0,
            mode="effective",
            profile_name="Child PETG",
        )

        self.assertEqual(text, '["1","2"]\n↳ Generic PETG · inherited elements')

    def test_missing_value_has_no_inherited_marker(self) -> None:
        text = _comparison_cell_text(
            {"value": None, "source": None, "explicit": False, "present": False},
            baseline_value=None,
            index=0,
            mode="raw",
        )

        self.assertEqual(text, "∅")

    def test_override_value_omits_parent_provenance_because_the_value_is_direct(self) -> None:
        text = _comparison_cell_text(
            {
                "value": ["265"],
                "source": "Generic PETG",
                "explicit": True,
                "present": True,
                "difference": "different",
            },
            baseline_value=["265"],
            index=0,
            mode="overrides",
            profile_name="Fast PETG",
        )

        self.assertEqual(text, '["265"] · different')


class ProvenanceDisplayTests(unittest.TestCase):
    def test_direct_profile_source_is_omitted(self) -> None:
        self.assertEqual(_inherited_source_names("Child", "Child", ["Child"]), [])

    def test_only_ancestor_names_are_returned_for_mixed_values(self) -> None:
        self.assertEqual(
            _inherited_source_names("Child", "Child", ["Child", "Root", "Root"]),
            ["Root"],
        )


class CompositionGridUpdateTests(unittest.TestCase):
    def test_cell_click_captures_scroll_before_the_server_callback(self) -> None:
        script = _composition_scroll_capture_handler(42)

        self.assertIn("closest?.('.nicegui-aggrid')", script)
        self.assertIn("document.getElementById('c42')", script)
        self.assertIn("window.__filamentToolsGridScroll[42]", script)
        self.assertIn("top: viewport?.scrollTop", script)
        self.assertIn("pageY: window.scrollY", script)
        self.assertIn("capturedAt: performance.now()", script)

    def test_same_row_refresh_updates_only_changed_rows_and_restores_scroll(self) -> None:
        columns = [{"field": "setting"}]
        rows = [
            {"key": "speed", "setting": "New speed"},
            {"key": "temperature", "setting": "Unchanged temperature"},
        ]
        grid = Mock()
        grid.id = 42
        grid.options = {
            "columnDefs": columns,
            "rowData": [
                {"key": "speed", "setting": "Old speed"},
                {"key": "temperature", "setting": "Unchanged temperature"},
            ],
        }

        _update_composition_grid(grid, columns, rows, reset=False)

        script = grid.client.run_javascript.call_args.args[0]
        self.assertIn("component.api.applyTransaction", script)
        self.assertIn("New speed", script)
        self.assertNotIn("Unchanged temperature", script)
        self.assertIn("window.__filamentToolsGridScroll?.[42]", script)
        self.assertIn("performance.now() - pendingCapture.capturedAt < 1500", script)
        self.assertIn("delete window.__filamentToolsGridScroll[42]", script)
        self.assertIn("liveViewport.scrollTop = scrollTop", script)
        self.assertIn("verticalRail.scrollTop = scrollTop", script)
        self.assertIn("window.scrollTo(pageX, pageY)", script)
        grid.run_grid_method.assert_not_called()
        grid.update.assert_not_called()

    def test_unchanged_rows_do_not_touch_the_live_grid(self) -> None:
        columns = [{"field": "setting"}]
        rows = [{"key": "speed", "setting": "Speed"}]
        grid = Mock()
        grid.options = {"columnDefs": columns, "rowData": list(rows)}

        _update_composition_grid(grid, columns, rows, reset=False)

        grid.client.run_javascript.assert_not_called()
        grid.run_grid_method.assert_not_called()
        grid.update.assert_not_called()

    def test_changed_row_set_replaces_data(self) -> None:
        columns = [{"field": "setting"}]
        rows = [{"key": "speed", "setting": "Speed"}]
        grid = Mock()
        grid.options = {"columnDefs": columns, "rowData": []}

        _update_composition_grid(grid, columns, rows, reset=False)

        grid.run_grid_method.assert_called_once_with("setGridOption", "rowData", rows)
        grid.update.assert_not_called()

    def test_column_change_rebuilds_grid(self) -> None:
        grid = Mock()
        grid.options = {"columnDefs": [], "rowData": []}

        _update_composition_grid(
            grid,
            [{"field": "setting"}],
            [{"key": "speed"}],
            reset=False,
        )

        grid.update.assert_called_once_with()
        grid.run_grid_method.assert_not_called()


class CompositionSelectionDisplayTests(unittest.TestCase):
    def test_source_text_contains_value_and_inheritance_but_no_selected_label(self) -> None:
        text = _composition_source_text(
            {
                "name": "Fast PETG",
                "value": ["265"],
                "present": True,
                "source": "Generic PETG",
                "element_sources": [],
            }
        )

        self.assertEqual(text, '["265"]\n↳ inherited from Generic PETG')
        self.assertNotIn("selected", text.casefold())

    def test_source_and_result_columns_define_semantic_background_classes(self) -> None:
        source = _composition_source_column("Fast PETG", 1)
        result = _composition_result_column()

        self.assertIn("ft-value-source", source[":cellClass"])
        self.assertIn("ft-value-source", result[":cellClass"])
        self.assertIn("ft-value-removed", result[":cellClass"])


if __name__ == "__main__":
    unittest.main()
