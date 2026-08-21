from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from filament_tools.catalog import ProfileCatalog
from filament_tools.comparison import compare_profiles
from filament_tools.reporting.terminal import comparison_text
from filament_tools.resolution import ProfileResolver
from tests.support import SRC, root_profile, write_profile  # noqa: F401


class ComparisonTests(unittest.TestCase):
    def test_missing_and_explicit_json_null_are_different(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            left = write_profile(directory, "Left", root_profile("Left"))
            right = write_profile(directory, "Right", {**root_profile("Right"), "optional": None})
            catalog = ProfileCatalog([directory])
            report = compare_profiles(
                [catalog.load_path(left), catalog.load_path(right)],
                ProfileResolver(catalog),
                only_different=True,
            )
            row = next(row for row in report.rows if row.key == "optional")
            self.assertFalse(row.cells[0].present)
            self.assertTrue(row.cells[1].present)
            rendered = comparison_text(report)
            self.assertIn("∅", rendered)
            self.assertIn("null", rendered)


if __name__ == "__main__":
    unittest.main()
