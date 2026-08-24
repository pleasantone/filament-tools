from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from filament_tools.catalog import ProfileCatalog, _expand_discovery_roots
from filament_tools.service import ProfileWorkbench
from tests.support import SRC, write_profile  # noqa: F401


class CatalogIntegrationTests(unittest.TestCase):
    def test_discovery_uses_active_trees_without_scanning_backup_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "OrcaSlicer"
            user = root / "user"
            system = root / "system"
            backup = root / "user_backup-v2.3.2"
            user.mkdir(parents=True)
            system.mkdir()
            backup.mkdir()

            roots = _expand_discovery_roots([root])

            self.assertEqual(roots, [user.resolve(), system.resolve()])
            self.assertNotIn(backup.resolve(), roots)

    def test_bulk_scan_ignores_underscore_profile_but_exact_path_loads_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            visible = write_profile(root, "Machine Base", {"speed": 500})
            auxiliary = write_profile(
                root,
                "Machine Base",
                {"speed": 300},
                "_Machine Base.json",
            )
            catalog = ProfileCatalog([root])

            self.assertEqual(catalog.find("Machine Base").path, visible.resolve())
            self.assertEqual(catalog.load_path(auxiliary).path, auxiliary.resolve())

    def test_fixture_catalog_exposes_printer_search_options(self) -> None:
        fixture_profiles = Path(__file__).parents[1] / "fixtures" / "profiles"
        workbench = ProfileWorkbench(ProfileCatalog([fixture_profiles]))

        page = workbench.printer_options("h2c", limit=1)

        self.assertEqual(page["results"], ["Bambu Lab H2C 0.4 nozzle"])
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["limit"], 1)

    def test_system_copy_wins_and_difference_warns(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "BambuStudio"
            relative = "BBL/filament/Test PETG.json"
            system = write_profile(root / "system", "Test PETG", {"speed": 12}, relative)
            bundled = write_profile(
                root / "resources/profiles", "Test PETG", {"speed": 10}, relative
            )
            warnings = []
            catalog = ProfileCatalog([root], warnings.append)
            selected = catalog.find("Test PETG")
            self.assertEqual(selected.path, system.resolve())
            self.assertNotEqual(system.read_text(), bundled.read_text())
            self.assertEqual(len(warnings), 1)
            self.assertIn(str(system.resolve()), warnings[0])
            self.assertIn(str(bundled.resolve()), warnings[0])

    def test_unrelated_duplicate_names_are_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_profile(root / "one", "Duplicate", {"value": 1})
            write_profile(root / "two", "Duplicate", {"value": 2})
            with self.assertRaisesRegex(RuntimeError, "ambiguous"):
                ProfileCatalog([root]).find("Duplicate")

    def test_workbench_filters_before_limit_and_finds_late_filaments(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for index in range(520):
                write_profile(
                    root,
                    f"A Process {index:03}",
                    {"type": "process", "layer_height": "0.2"},
                )
            target = write_profile(
                root,
                "Zeta PETG",
                {
                    "type": "filament",
                    "filament_type": ["PETG"],
                    "compatible_printers": ["Bambu Lab H2C 0.4 nozzle"],
                },
            )
            workbench = ProfileWorkbench(ProfileCatalog([root]))

            default_page = workbench.catalog_query(limit=50)
            search_page = workbench.catalog_query("PETG", limit=50)

            self.assertEqual(default_page["total"], 1)
            self.assertEqual(default_page["results"][0]["path"], str(target.resolve()))
            self.assertEqual(search_page["total"], 1)
            self.assertEqual(search_page["results"][0]["name"], "Zeta PETG")

    def test_machine_filters_match_any_machine_and_keep_generic_ancestors(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_profile(root, "Generic PLA", {"type": "filament", "temperature": 220})
            write_profile(
                root,
                "H2C PLA",
                {
                    "inherits": "Generic PLA",
                    "compatible_printers": ["Bambu Lab H2C 0.4 nozzle"],
                },
            )
            write_profile(
                root,
                "X1C PLA",
                {
                    "inherits": "Generic PLA",
                    "compatible_printers": ["Bambu Lab X1 Carbon 0.4 nozzle"],
                },
            )
            write_profile(
                root,
                "A1 PLA",
                {
                    "inherits": "Generic PLA",
                    "compatible_printers": ["Bambu Lab A1 0.4 nozzle"],
                },
            )
            workbench = ProfileWorkbench(ProfileCatalog([root]))

            page = workbench.catalog_query(machines={"H2C", "X1C"}, limit=50)
            parent_search = workbench.catalog_query("Generic", machines={"H2C", "X1C"}, limit=50)

            self.assertEqual(
                {entry["name"] for entry in page["results"]},
                {"Generic PLA", "H2C PLA", "X1C PLA"},
            )
            self.assertEqual(parent_search["results"][0]["name"], "Generic PLA")
            self.assertEqual(parent_search["total"], 1)

    def test_managed_copy_preference_happens_before_result_limit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "BambuStudio"
            relative = "BBL/filament/Preferred PETG.json"
            system = write_profile(
                root / "system",
                "Preferred PETG",
                {"type": "filament", "filament_type": ["PETG"]},
                relative,
            )
            write_profile(
                root / "resources/profiles",
                "Preferred PETG",
                {"type": "filament", "filament_type": ["PETG"]},
                relative,
            )
            results, total = ProfileCatalog([root]).query_visible(
                query="Preferred", profile_type="filament", limit=1
            )
            self.assertEqual(total, 1)
            self.assertEqual(results[0].path, system.resolve())


if __name__ == "__main__":
    unittest.main()
