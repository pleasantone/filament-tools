from __future__ import annotations

import unittest

from filament_tools.editor.workbench_ui import CompatibilitySeedState, SeededStringState
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


if __name__ == "__main__":
    unittest.main()
