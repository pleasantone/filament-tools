from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "profile_diff.py"
FIXTURES = ROOT / "tests" / "fixtures" / "profiles"


class ProfileDiffCliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run_cli_with_search_dir(FIXTURES, *args)

    def run_cli_with_search_dir(
        self,
        search_dir: Path,
        *args: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--no-auto-discover",
                "--search-dir",
                str(search_dir),
                *args,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def write_profile(self, directory: Path, name: str, **settings: object) -> Path:
        path = directory / f"{name}.json"
        data = {"name": name, "type": "filament", **settings}
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_name_lookup_finds_exact_profile(self) -> None:
        result = self.run_cli(
            "--find-profile",
            "Generic PETG H2C 0.4",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Generic PETG H2C 0.4", result.stdout)
        self.assertNotIn("Generic PETG H2C 0.6", result.stdout)

    def test_selectors_compare_one_material_across_nozzles(self) -> None:
        result = self.run_cli(
            "--select",
            "Bambu PETG HF;machine=H2C;nozzle=0.4",
            "--select",
            "Bambu PETG HF;machine=H2C;nozzle=0.6",
            "--keys",
            "^counter_coef_2$",
            "--width",
            "48",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Bambu PETG HF H2C 0.4 [H2C / 0.4", result.stdout)
        self.assertIn("Bambu PETG HF H2C 0.6 [H2C / 0.6", result.stdout)
        self.assertIn('["0.0058"]', result.stdout)
        self.assertIn('["0.0062"]', result.stdout)

    def test_legacy_selection_arguments_are_rejected(self) -> None:
        for argument, value in (
            ("--profile", "Generic PETG"),
            ("--machine", "H2C"),
            ("--nozzle", "0.4"),
        ):
            with self.subTest(argument=argument):
                result = self.run_cli(
                    "--select",
                    "Generic PETG;machine=H2C;nozzle=0.4",
                    "--select",
                    "Bambu PETG HF;machine=H2C;nozzle=0.4",
                    argument,
                    value,
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn("unrecognized arguments", result.stderr)

    def test_effective_mode_reports_inherited_source(self) -> None:
        result = self.run_cli(
            "--select",
            "Generic PETG;machine=H2C;nozzle=0.4",
            "--select",
            "Bambu PETG HF;machine=H2C;nozzle=0.4",
            "--keys",
            "^counter_coef_2$",
            "--show-source",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Synthetic PETG Common", result.stdout)
        self.assertIn("Bambu PETG HF H2C 0.4", result.stdout)

    def test_raw_mode_does_not_include_inherited_value(self) -> None:
        result = self.run_cli(
            "--select",
            "Generic PETG;machine=H2C;nozzle=0.4",
            "--select",
            "Bambu PETG HF;machine=H2C;nozzle=0.4",
            "--mode",
            "raw",
            "--keys",
            "^counter_coef_2$",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        row = next(line for line in result.stdout.splitlines() if line.startswith("counter_coef_2"))
        self.assertIn("∅", row)
        self.assertIn('["0.0058"]', row)

    def test_per_profile_selectors_can_mix_machine_and_nozzle(self) -> None:
        result = self.run_cli(
            "--select",
            "Bambu PETG HF;machine=H2C;nozzle=0.4;label=HF fine",
            "--select",
            "Generic PETG;machine=H2C;nozzle=0.6;label=Generic wide",
            "--keys",
            "^filament_max_volumetric_speed$",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HF fine", result.stdout)
        self.assertIn("Generic wide", result.stdout)
        self.assertIn('["24"]', result.stdout)
        self.assertIn('["18"]', result.stdout)

    def test_exact_selectors_do_not_require_filters(self) -> None:
        result = self.run_cli(
            "--select",
            "Generic PETG H2C 0.4",
            "--select",
            "Generic PETG H2C 0.6",
            "--keys",
            "^filament_max_volumetric_speed$",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('["15"]', result.stdout)
        self.assertIn('["18"]', result.stdout)

    def test_system_copy_is_preferred_over_identical_bundled_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "BambuStudio"
            system = root / "system" / "BBL" / "filament"
            bundled = root / "resources" / "profiles" / "BBL" / "filament"
            system.mkdir(parents=True)
            bundled.mkdir(parents=True)
            self.write_profile(system, "Managed Copy", copy_value="same")
            self.write_profile(bundled, "Managed Copy", copy_value="same")
            comparison = self.write_profile(root, "Copy Comparison", copy_value="other")

            result = self.run_cli_with_search_dir(
                root,
                "--select",
                "Managed Copy",
                "--select",
                str(comparison),
                "--mode",
                "raw",
                "--keys",
                "^copy_value$",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("same", result.stdout)
            self.assertNotIn("warning:", result.stderr)

    def test_different_system_copy_is_preferred_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "BambuStudio"
            system = root / "system" / "BBL" / "filament"
            bundled = root / "resources" / "profiles" / "BBL" / "filament"
            system.mkdir(parents=True)
            bundled.mkdir(parents=True)
            system_path = self.write_profile(
                system,
                "Changed Managed Copy",
                copy_value="system value",
            )
            bundled_path = self.write_profile(
                bundled,
                "Changed Managed Copy",
                copy_value="bundled value",
            )
            comparison = self.write_profile(root, "Changed Copy Comparison")

            result = self.run_cli_with_search_dir(
                root,
                "--select",
                "Changed Managed Copy",
                "--select",
                str(comparison),
                "--mode",
                "raw",
                "--keys",
                "^copy_value$",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("system value", result.stdout)
            self.assertNotIn("bundled value", result.stdout)
            self.assertIn(
                "warning: system and bundled profile copies differ; "
                "preferring system copy",
                result.stderr,
            )
            self.assertIn(str(system_path), result.stderr)
            self.assertIn(str(bundled_path), result.stderr)

    def test_same_name_non_copy_variants_remain_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "BambuStudio"
            system = root / "system" / "BBL" / "filament"
            bundled = root / "resources" / "profiles" / "OTHER" / "filament"
            system.mkdir(parents=True)
            bundled.mkdir(parents=True)
            self.write_profile(system, "Unrelated Duplicate", copy_value="system")
            self.write_profile(bundled, "Unrelated Duplicate", copy_value="bundled")
            comparison = self.write_profile(root, "Unrelated Comparison")

            result = self.run_cli_with_search_dir(
                root,
                "--select",
                "Unrelated Duplicate",
                "--select",
                str(comparison),
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("is ambiguous", result.stderr)
            self.assertIn("/system/BBL/", result.stderr)
            self.assertIn("/resources/profiles/OTHER/", result.stderr)

    def test_selector_rejects_unknown_options(self) -> None:
        result = self.run_cli(
            "--select",
            "Generic PETG;material=PETG",
            "--select",
            "Bambu PETG HF;nozzle=0.4",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown selector option 'material'", result.stderr)

    def test_group_filter_applies_to_terminal_output(self) -> None:
        result = self.run_cli(
            "--select",
            "Generic PETG;machine=H2C;nozzle=0.4",
            "--select",
            "Bambu PETG HF;machine=H2C;nozzle=0.4",
            "--group",
            "dimensional",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("counter_coef_2", result.stdout)
        self.assertNotIn("nozzle_temperature", result.stdout)
        self.assertNotIn("filament_max_volumetric_speed", result.stdout)

    def test_html_is_grouped_searchable_and_marks_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "comparison.html"
            result = self.run_cli(
                "--select",
                "Generic PETG;machine=H2C;nozzle=0.4;label=Generic",
                "--select",
                "Bambu PETG HF;machine=H2C;nozzle=0.4;label=HF",
                "--group",
                "temperature",
                "--group",
                "dimensional",
                "--html",
                str(output),
                "--show-source",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            document = output.read_text(encoding="utf-8")
            self.assertIn('data-group="temperature"', document)
            self.assertIn('data-group="dimensional"', document)
            self.assertIn('id="parameter-search"', document)
            self.assertIn('class="value inherited"', document)
            self.assertIn('class="value explicit different"', document)
            self.assertIn("position: sticky", document)
            self.assertNotIn("filament_max_volumetric_speed", document)

    def test_overrides_mode_compares_only_explicit_keys_with_parent_effective_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_profile(
                directory,
                "Override Grandparent",
                inherited_setting="grandparent value",
                parent_only="not a child override",
            )
            self.write_profile(
                directory,
                "Override Parent",
                inherits="Override Grandparent",
                same_setting="unchanged",
            )
            child = self.write_profile(
                directory,
                "Override Child",
                inherits="Override Parent",
                inherited_setting="child value",
                same_setting="unchanged",
                new_setting="new value",
            )
            output = directory / "overrides.csv"

            result = self.run_cli_with_search_dir(
                directory,
                "--select",
                str(child),
                "--mode",
                "overrides",
                "--csv",
                str(output),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = {row["parameter"]: row for row in csv.DictReader(handle)}
            self.assertEqual(
                set(rows),
                {"inherited_setting", "same_setting", "new_setting"},
            )
            self.assertEqual(rows["inherited_setting"]["explicit value"], "child value")
            self.assertEqual(
                rows["inherited_setting"]["parent effective value"],
                "grandparent value",
            )
            self.assertEqual(rows["inherited_setting"]["difference"], "changed")
            self.assertEqual(
                rows["inherited_setting"]["parent source"],
                "Override Grandparent",
            )
            self.assertEqual(rows["same_setting"]["difference"], "same")
            self.assertEqual(rows["same_setting"]["parent source"], "Override Parent")
            self.assertEqual(rows["new_setting"]["difference"], "added")

    def test_overrides_only_different_hides_redundant_explicit_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.write_profile(directory, "Difference Parent", setting="same")
            child = self.write_profile(
                directory,
                "Difference Child",
                inherits="Difference Parent",
                setting="same",
                changed="child",
            )

            result = self.run_cli_with_search_dir(
                directory,
                "--select",
                str(child),
                "--mode",
                "overrides",
                "--only-different",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("changed", result.stdout)
            self.assertNotIn("setting", result.stdout)

    def test_overrides_mode_reports_missing_parent_without_hiding_child_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            child = self.write_profile(
                directory,
                "Missing Parent Child",
                inherits="Parent That Does Not Exist",
                visible_override="still shown",
            )

            result = self.run_cli_with_search_dir(
                directory,
                "--select",
                str(child),
                "--mode",
                "overrides",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("MISSING PARENT 'Parent That Does Not Exist'", result.stdout)
            self.assertIn("visible_override", result.stdout)
            self.assertIn("unavailable", result.stdout)
            self.assertIn("warning:", result.stderr)

    def test_overrides_mode_reports_inheritance_cycle_without_hiding_child_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            cycle_a = self.write_profile(
                directory,
                "Cycle A",
                inherits="Cycle B",
                a_override="A",
            )
            self.write_profile(
                directory,
                "Cycle B",
                inherits="Cycle A",
                b_override="B",
            )

            result = self.run_cli_with_search_dir(
                directory,
                "--select",
                str(cycle_a),
                "--mode",
                "overrides",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("INHERITANCE CYCLE", result.stdout)
            self.assertIn("Cycle A.json", result.stdout)
            self.assertIn("Cycle B.json", result.stdout)
            self.assertIn("a_override", result.stdout)
            self.assertIn("unavailable", result.stdout)

    def test_overrides_mode_renders_every_selected_profile_and_html_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            root = self.write_profile(directory, "Root Profile", root_setting="root")
            child = self.write_profile(
                directory,
                "HTML Child",
                inherits="Root Profile",
                root_setting="child",
            )
            output = directory / "overrides.html"

            result = self.run_cli_with_search_dir(
                directory,
                "--select",
                str(child),
                "--select",
                str(root),
                "--mode",
                "overrides",
                "--html",
                str(output),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count("Profile:"), 2)
            self.assertIn("NO PARENT: profile does not declare inherits", result.stdout)
            document = output.read_text(encoding="utf-8")
            self.assertIn("Mode: <b>overrides</b>", document)
            self.assertIn("Parent effective value", document)
            self.assertIn("Root Profile", document)
            self.assertIn('class="difference changed"', document)


if __name__ == "__main__":
    unittest.main()
