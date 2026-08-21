from __future__ import annotations

import unittest

from filament_tools.identity import bambu_filament_id, material_name_from_profile_name
from tests.support import SRC  # noqa: F401


class IdentityTests(unittest.TestCase):
    def test_bambu_filament_id_matches_documented_md5_shape(self) -> None:
        self.assertEqual(bambu_filament_id("My PETG"), "P8874d27")
        self.assertEqual(bambu_filament_id("My PETG", "user-42"), "P25dd192")

    def test_material_name_discards_printer_suffix(self) -> None:
        self.assertEqual(material_name_from_profile_name("My PETG @BBL H2C 0.4"), "My PETG")


if __name__ == "__main__":
    unittest.main()
