from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from filament_tools.catalog import ProfileCatalog
from filament_tools.composition import materialize_recipe
from filament_tools.model import ChoiceKind, CompositionChoice, CompositionRecipe, OutputMode
from filament_tools.resolution import ProfileResolver
from filament_tools.service import ProfileWorkbench
from tests.support import SRC, root_profile, write_profile  # noqa: F401


class CompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.starting = write_profile(
            self.directory,
            "Starting PETG",
            {**root_profile("Starting PETG"), "fan_max_speed": ["60"], "vendor": "A"},
        )
        self.donor = write_profile(
            self.directory,
            "Fast PETG",
            {
                "inherits": "Starting PETG",
                "nozzle_temperature": ["265"],
                "filament_max_volumetric_speed": ["24"],
                "donor_only_setting": "fast",
            },
        )
        self.workbench = ProfileWorkbench(ProfileCatalog([self.directory]))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def recipe(self, mode: OutputMode = OutputMode.SPARSE) -> CompositionRecipe:
        return CompositionRecipe(
            name="Composed PETG",
            starting_source=str(self.starting),
            reference_sources=[str(self.donor)],
            sparse_parent=str(self.starting),
            output_mode=mode,
            selections={
                "nozzle_temperature": CompositionChoice(
                    kind=ChoiceKind.SOURCE, source=str(self.donor)
                ),
                "fan_max_speed": CompositionChoice(kind=ChoiceKind.CUSTOM, value=["75"]),
            },
        )

    def test_materializes_donor_and_custom_values_with_two_kinds_of_provenance(self) -> None:
        materialized = materialize_recipe(self.recipe(), ProfileResolver(self.workbench.catalog))
        self.assertEqual(materialized.values["nozzle_temperature"], ["265"])
        self.assertEqual(materialized.selection_sources["nozzle_temperature"], "Fast PETG")
        self.assertEqual(materialized.value_sources["nozzle_temperature"], "Fast PETG")
        self.assertEqual(materialized.values["fan_max_speed"], ["75"])
        self.assertEqual(materialized.value_sources["fan_max_speed"], "Custom value")

    def test_same_recipe_builds_sparse_or_full_ams_profile(self) -> None:
        sparse = self.workbench.build_recipe(self.recipe())[0]
        self.assertEqual(sparse.data["inherits"], "Starting PETG")
        self.assertEqual(sparse.data["nozzle_temperature"], ["265"])
        self.assertNotIn("filament_id", sparse.data)

        root = self.workbench.build_recipe(self.recipe(OutputMode.ROOT))[0]
        self.assertNotIn("inherits", root.data)
        self.assertEqual(root.data["filament_id"], "P1234567")
        self.assertEqual(root.data["nozzle_temperature"], ["265"])
        self.assertEqual(root.data["fan_max_speed"], ["75"])

    def test_identity_and_compatibility_are_not_copyable_settings(self) -> None:
        recipe = self.recipe()
        recipe.selections["filament_id"] = CompositionChoice(
            kind=ChoiceKind.SOURCE, source=str(self.donor)
        )
        with self.assertRaisesRegex(ValueError, "managed by output controls"):
            materialize_recipe(recipe, ProfileResolver(self.workbench.catalog))

    def test_effectively_identical_donor_choice_falls_back_to_starting_profile(self) -> None:
        recipe = self.recipe()
        recipe.selections = {
            "fan_max_speed": CompositionChoice(
                kind=ChoiceKind.SOURCE,
                source=str(self.donor),
            )
        }

        materialized = materialize_recipe(recipe, ProfileResolver(self.workbench.catalog))

        self.assertEqual(materialized.redundant_selections, ("fan_max_speed",))
        self.assertEqual(materialized.selection_sources["fan_max_speed"], "Starting PETG")
        self.assertNotIn("fan_max_speed", materialized.draft.edits)

    def test_composition_view_only_includes_source_or_result_differences(self) -> None:
        view = self.workbench.composition_view(self.recipe())
        rows = {row["key"]: row for row in view["rows"]}
        keys = set(rows)

        self.assertIn("nozzle_temperature", keys)
        self.assertIn("filament_max_volumetric_speed", keys)
        self.assertIn("fan_max_speed", keys)
        self.assertNotIn("version", keys)
        self.assertEqual(rows["nozzle_temperature"]["result"]["selected_selector"], str(self.donor))
        self.assertEqual(rows["nozzle_temperature"]["result"]["selection_kind"], "source")
        self.assertIsNone(rows["fan_max_speed"]["result"]["selected_selector"])
        self.assertEqual(rows["fan_max_speed"]["result"]["selection_kind"], "custom")
        self.assertEqual(
            rows["donor_only_setting"]["result"]["selected_selector"], str(self.starting)
        )
        self.assertEqual(rows["donor_only_setting"]["result"]["selected_via"], "Starting PETG")


if __name__ == "__main__":
    unittest.main()
