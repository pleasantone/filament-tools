from __future__ import annotations

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
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--no-auto-discover",
                "--search-dir",
                str(FIXTURES),
                *args,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

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


if __name__ == "__main__":
    unittest.main()
