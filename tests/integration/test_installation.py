from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from filament_tools.installation import apply_install_plan, plan_install
from filament_tools.model import InstallAction
from tests.support import SRC, root_profile, write_profile  # noqa: F401


class InstallationIntegrationTests(unittest.TestCase):
    def test_update_replaces_profile_and_preserves_reviewed_backup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            config = directory / "BambuStudio"
            config.mkdir()
            source = write_profile(
                directory,
                "Updated PETG",
                {**root_profile("Updated PETG"), "nozzle_temperature": ["250"]},
            )
            created = plan_install([source], app_data_dir=config)
            destination = apply_install_plan(created)[0]
            original = destination.read_text(encoding="utf-8")
            write_profile(
                directory,
                "Updated PETG",
                {**root_profile("Updated PETG"), "nozzle_temperature": ["265"]},
            )

            update = plan_install([source], app_data_dir=config, action=InstallAction.UPDATE)
            self.assertTrue(update.valid)
            backup = update.operations[0].backup
            self.assertIsNotNone(backup)
            apply_install_plan(update)

            self.assertIn('"265"', destination.read_text(encoding="utf-8"))
            self.assertEqual(backup.read_text(encoding="utf-8"), original)

    def test_uninstall_removes_profile_and_preserves_backup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            config = directory / "BambuStudio"
            config.mkdir()
            source = write_profile(directory, "Removed PETG", root_profile("Removed PETG"))
            destination = apply_install_plan(plan_install([source], app_data_dir=config))[0]

            uninstall = plan_install([source], app_data_dir=config, action=InstallAction.UNINSTALL)
            backup = uninstall.operations[0].backup
            self.assertTrue(uninstall.valid)
            apply_install_plan(uninstall)

            self.assertFalse(destination.exists())
            self.assertTrue(backup.is_file())

    def test_update_rejects_profile_changed_after_review(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            config = directory / "BambuStudio"
            config.mkdir()
            source = write_profile(directory, "Drift PETG", root_profile("Drift PETG"))
            destination = apply_install_plan(plan_install([source], app_data_dir=config))[0]
            update = plan_install([source], app_data_dir=config, action=InstallAction.UPDATE)
            destination.write_text("changed after review", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "changed after planning"):
                apply_install_plan(update)
            self.assertFalse(update.operations[0].backup.exists())

    def test_late_update_conflict_restores_earlier_profile(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            config = directory / "BambuStudio"
            config.mkdir()
            first = write_profile(directory, "First update", root_profile("First update"))
            second = write_profile(directory, "Second update", root_profile("Second update"))
            created = plan_install([first, second], app_data_dir=config)
            first_destination, second_destination = apply_install_plan(created)
            first_original = first_destination.read_text(encoding="utf-8")
            write_profile(
                directory,
                "First update",
                {**root_profile("First update"), "nozzle_temperature": ["265"]},
            )
            update = plan_install([first, second], app_data_dir=config, action=InstallAction.UPDATE)
            second_destination.write_text("late change", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "changed after planning"):
                apply_install_plan(update)

            self.assertEqual(first_destination.read_text(encoding="utf-8"), first_original)
            self.assertEqual(second_destination.read_text(encoding="utf-8"), "late change")
            self.assertFalse(update.operations[0].backup.exists())

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
