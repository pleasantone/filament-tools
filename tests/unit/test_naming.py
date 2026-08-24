from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from filament_tools.catalog import ProfileCatalog
from filament_tools.naming import (
    suggest_output_path,
    suggest_profile_name,
    suggest_project_name,
    suggest_project_path,
)
from filament_tools.service import ProfileWorkbench
from tests.support import root_profile, write_profile


class NamingTests(unittest.TestCase):
    def test_custom_name_preserves_machine_suffix_and_avoids_collisions(self) -> None:
        source = "Generic PETG @BBL H2C 0.4 nozzle"
        self.assertEqual(
            suggest_profile_name(source),
            "Generic PETG Custom @BBL H2C 0.4 nozzle",
        )
        self.assertEqual(
            suggest_profile_name(
                source,
                {
                    "Generic PETG Custom @BBL H2C 0.4 nozzle",
                    "Generic PETG Custom 2 @BBL H2C 0.4 nozzle",
                },
            ),
            "Generic PETG Custom 3 @BBL H2C 0.4 nozzle",
        )

    def test_project_and_output_paths_follow_their_distinct_names(self) -> None:
        directory = Path("/tmp/filament-tools")
        profile = "Generic PETG Custom @BBL H2C 0.4 nozzle"
        project = suggest_project_name(profile)

        self.assertEqual(project, "Generic PETG Custom")
        self.assertEqual(
            suggest_project_path(project, directory),
            directory.resolve() / "Generic PETG Custom.ftdraft",
        )
        self.assertEqual(
            suggest_output_path(profile, directory),
            directory.resolve() / f"{profile}.json",
        )
        self.assertEqual(suggest_output_path(profile, directory, family=True), directory.resolve())

    def test_workbench_uses_one_default_policy_for_drafts_and_composition(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = write_profile(
                directory,
                "Generic PETG @BBL H2C 0.4 nozzle",
                root_profile("Generic PETG @BBL H2C 0.4 nozzle"),
            )
            workbench = ProfileWorkbench(ProfileCatalog([directory]))

            draft = workbench.create_draft(str(source))
            defaults = workbench.composition_defaults(
                str(source), project_directory=directory, output_directory=directory
            )

            self.assertEqual(draft.name, defaults["profile_name"])
            self.assertEqual(defaults["project_name"], "Generic PETG Custom")
            self.assertEqual(
                defaults["output_path"],
                str(directory.resolve() / f"{draft.name}.json"),
            )

    def test_install_application_follows_the_starting_profile(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = write_profile(
                directory,
                "Orca PETG",
                root_profile("Orca PETG"),
                "OrcaSlicer/user/default/filament/base/Orca PETG.json",
            )
            workbench = ProfileWorkbench(ProfileCatalog([directory]))

            defaults = workbench.composition_defaults(str(source))

            self.assertEqual(defaults["application"], "orca")


if __name__ == "__main__":
    unittest.main()
