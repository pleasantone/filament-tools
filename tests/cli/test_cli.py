from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT, root_profile, run_cli, write_profile


class CliTests(unittest.TestCase):
    def test_install_maintenance_actions_are_previewable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            profile = write_profile(directory, "Maintained PETG", root_profile("Maintained PETG"))
            config = directory / "BambuStudio"
            config.mkdir()
            created = run_cli(["install", str(profile), "--config-dir", str(config)])
            self.assertEqual(created.returncode, 0, created.stderr)

            for action in ("update", "uninstall"):
                with self.subTest(action=action):
                    preview = run_cli(
                        [
                            "install",
                            str(profile),
                            "--config-dir",
                            str(config),
                            "--action",
                            action,
                            "--dry-run",
                        ]
                    )
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    self.assertIn(f"Action: {action}", preview.stdout)
                    self.assertIn("backup:", preview.stdout)

    def test_help_exposes_intent_commands(self) -> None:
        result = run_cli(["--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("catalog", "inspect", "compare", "build", "validate", "install", "editor"):
            self.assertIn(command, result.stdout)

    def test_compare_existing_fixtures(self) -> None:
        fixture = ROOT / "tests/fixtures/profiles"
        result = run_cli(
            [
                "--no-auto-discover",
                "--search-dir",
                str(fixture),
                "compare",
                "Generic PETG H2C 0.4",
                "Bambu PETG HF H2C 0.4",
                "--only-different",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("filament_max_volumetric_speed", result.stdout)

    def test_editor_rejects_remote_bind_before_starting_server(self) -> None:
        result = run_cli(["editor", "--host", "0.0.0.0"])

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("may only bind", result.stderr)

    def test_build_root_then_dry_run_install(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = write_profile(directory, "Base PETG", root_profile("Base PETG"))
            output = directory / "Flat PETG.json"
            result = run_cli(
                [
                    "--no-auto-discover",
                    "build",
                    "root",
                    "--source",
                    str(source),
                    "--name",
                    "Flat PETG",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("inherits", json.loads(output.read_text()))
            config = directory / "BambuStudio"
            config.mkdir()
            install = run_cli(
                [
                    "install",
                    str(output),
                    "--config-dir",
                    str(config),
                    "--dry-run",
                ]
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertIn("Dry run", install.stdout)
            self.assertFalse((config / "user/default/filament/base/Flat PETG.json").exists())


if __name__ == "__main__":
    unittest.main()
