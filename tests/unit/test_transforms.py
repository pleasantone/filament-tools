from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from filament_tools.catalog import ProfileCatalog
from filament_tools.model import IdentityMode, OutputMode, ProfileDraft, TargetVariant
from filament_tools.resolution import ProfileResolver
from filament_tools.transforms import build_family, build_root, build_sparse
from filament_tools.validation import has_errors, validate_sparse_roundtrip
from tests.support import SRC, root_profile, write_profile  # noqa: F401


class TransformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        base_data = root_profile("Base PETG")
        self.base_path = write_profile(self.directory, "Base PETG", base_data)
        self.modified_path = write_profile(
            self.directory,
            "Tuned PETG",
            {
                "inherits": "Base PETG",
                "nozzle_temperature": ["255"],
                "filament_max_volumetric_speed": ["22"],
            },
        )
        self.catalog = ProfileCatalog([self.directory])
        resolver = ProfileResolver(self.catalog)
        self.base = resolver.resolve(self.catalog.load_path(self.base_path))
        self.modified = resolver.resolve(self.catalog.load_path(self.modified_path))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_sparse_contains_only_behavioral_delta_and_structural_key(self) -> None:
        draft = ProfileDraft(
            name="Tuned sparse",
            source=str(self.modified_path),
            base=str(self.base_path),
            output_mode=OutputMode.SPARSE,
        )
        artifact = build_sparse(draft, self.modified, self.base)
        self.assertEqual(artifact.data["inherits"], "Base PETG")
        self.assertNotIn("filament_id", artifact.data)
        self.assertEqual(artifact.data["nozzle_temperature"], ["255"])
        self.assertEqual(artifact.data["filament_extruder_variant"], ["Direct Drive"])
        self.assertFalse(
            has_errors(validate_sparse_roundtrip(artifact, self.base.values, self.modified.values))
        )

    def test_root_is_flattened_and_ams_eligible(self) -> None:
        draft = ProfileDraft(
            name="Tuned root",
            source=str(self.modified_path),
            output_mode=OutputMode.ROOT,
            identity_mode=IdentityMode.INHERIT,
        )
        artifact = build_root(draft, self.modified)
        self.assertNotIn("inherits", artifact.data)
        self.assertEqual(artifact.data["filament_id"], "P1234567")
        self.assertEqual(artifact.data["nozzle_temperature"], ["255"])
        self.assertEqual(artifact.data["filament_settings_id"], ["Tuned root"])

    def test_family_shares_filament_id_and_varies_targets(self) -> None:
        draft = ProfileDraft(
            name="Tuned family",
            source=str(self.modified_path),
            output_mode=OutputMode.ROOT,
            identity_mode=IdentityMode.GENERATE,
            variants=[
                TargetVariant(
                    name="Tuned H2C 0.4",
                    compatible_printers=["Bambu Lab H2C 0.4 nozzle"],
                ),
                TargetVariant(
                    name="Tuned H2C 0.6",
                    compatible_printers=["Bambu Lab H2C 0.6 nozzle"],
                    edits={"filament_max_volumetric_speed": ["19"]},
                ),
            ],
        )
        artifacts = build_family(draft, self.modified)
        self.assertEqual(artifacts[0].data["filament_id"], artifacts[1].data["filament_id"])
        self.assertEqual(artifacts[1].data["filament_max_volumetric_speed"], ["19"])
        self.assertEqual(
            artifacts[1].data["compatible_printers"],
            ["Bambu Lab H2C 0.6 nozzle"],
        )


if __name__ == "__main__":
    unittest.main()
