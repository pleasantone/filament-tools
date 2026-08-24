from __future__ import annotations

import unittest
from pathlib import Path

from filament_tools.editor.install_plans import ReviewedInstallPlans
from filament_tools.model import InstallPlan


class ReviewedInstallPlanTests(unittest.TestCase):
    def test_plan_capability_is_one_use(self) -> None:
        store = ReviewedInstallPlans()
        plan = InstallPlan(app="bambu", app_data_dir=Path("/tmp/app"), user_folder="default")

        plan_id = store.issue(plan)

        self.assertIs(store.consume(plan_id), plan)
        with self.assertRaisesRegex(ValueError, "already used"):
            store.consume(plan_id)

    def test_expired_plan_is_rejected(self) -> None:
        now = [10.0]
        store = ReviewedInstallPlans(ttl_seconds=5, clock=lambda: now[0])
        plan = InstallPlan(app="bambu", app_data_dir=Path("/tmp/app"), user_folder="default")
        plan_id = store.issue(plan)
        now[0] = 16.0

        with self.assertRaisesRegex(ValueError, "expired"):
            store.consume(plan_id)


if __name__ == "__main__":
    unittest.main()
