from __future__ import annotations

import unittest

from filament_tools.model import ProfileDraft, Severity
from filament_tools.validation import validate_profile_data
from tests.support import SRC, root_profile  # noqa: F401


class ValidationTests(unittest.TestCase):
    def test_valid_root_has_no_errors(self) -> None:
        issues = validate_profile_data(root_profile())
        self.assertFalse([issue for issue in issues if issue.severity == Severity.ERROR])

    def test_cloud_identity_and_missing_compatibility_have_stable_codes(self) -> None:
        profile = root_profile()
        profile["setting_id"] = "cloud-owned"
        profile["compatible_printers"] = []
        codes = {issue.code for issue in validate_profile_data(profile)}
        self.assertIn("profile.cloud_metadata", codes)
        self.assertIn("root.compatibility_missing", codes)

    def test_profile_name_cannot_escape_install_directory(self) -> None:
        profile = root_profile()
        profile["name"] = "../escaped"
        profile["filament_settings_id"] = ["../escaped"]
        codes = {issue.code for issue in validate_profile_data(profile)}
        self.assertIn("profile.unsafe_name", codes)

    def test_profile_names_are_portable_across_supported_platforms(self) -> None:
        for name in (
            "CON",
            "NUL.json",
            "name:bad",
            "name?bad",
            "trailing.",
            "trailing ",
            "control\x01name",
            "x" * 252,
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "profile name"):
                    ProfileDraft(name=name, source="source.json")

    def test_profile_names_are_normalized_to_nfc(self) -> None:
        draft = ProfileDraft(name="Cafe\u0301 PETG", source="source.json")

        self.assertEqual(draft.name, "Café PETG")


if __name__ == "__main__":
    unittest.main()
