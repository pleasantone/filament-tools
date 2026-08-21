from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from filament_tools.installation import apply_install_plan, plan_install
from tests.support import SRC, root_profile, write_profile  # noqa: F401


class InstallationIntegrationTests(unittest.TestCase):
    def test_plan_routes_root_to_base_and_apply_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            config = directory / "BambuStudio"
            config.mkdir()
            (config / "BambuStudio.conf").write_text(
                '{"app":{"preset_folder":"account-1"}}', encoding="utf-8"
            )
            source = write_profile(directory, "Synthetic PETG", root_profile())
            plan = plan_install([source], app_data_dir=config)
            self.assertTrue(plan.valid)
            self.assertEqual(
                plan.operations[0].destination,
                config.resolve() / "user/account-1/filament/base/Synthetic PETG.json",
            )
            self.assertEqual(apply_install_plan(plan), [plan.operations[0].destination])

    def test_late_conflict_rolls_back_earlier_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            config = directory / "BambuStudio"
            config.mkdir()
            first_data = root_profile("First PETG")
            second_data = root_profile("Second PETG")
            first = write_profile(directory, "First PETG", first_data)
            second = write_profile(directory, "Second PETG", second_data)
            plan = plan_install([first, second], app_data_dir=config)
            late_destination = plan.operations[1].destination
            late_destination.parent.mkdir(parents=True)
            late_destination.write_text("race", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                apply_install_plan(plan)
            self.assertFalse(plan.operations[0].destination.exists())
            self.assertEqual(late_destination.read_text(), "race")

    def test_late_sync_metadata_conflict_blocks_apply(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            config = directory / "BambuStudio"
            config.mkdir()
            source = write_profile(directory, "Sync PETG", root_profile("Sync PETG"))
            plan = plan_install([source], app_data_dir=config)
            sync_path = plan.operations[0].destination.with_suffix(".info")
            sync_path.parent.mkdir(parents=True)
            sync_path.write_text("sync", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sync metadata"):
                apply_install_plan(plan)
            self.assertFalse(plan.operations[0].destination.exists())


if __name__ == "__main__":
    unittest.main()
