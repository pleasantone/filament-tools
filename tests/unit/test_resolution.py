from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from filament_tools.catalog import ProfileCatalog
from filament_tools.resolution import ProfileResolver
from tests.support import SRC, write_profile  # noqa: F401


class ResolutionTests(unittest.TestCase):
    def test_resolves_chain_with_name_and_path_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = write_profile(directory, "Root", {"speed": 10, "temperature": 245})
            child = write_profile(directory, "Child", {"inherits": "Root", "speed": 12})
            catalog = ProfileCatalog([directory])
            result = ProfileResolver(catalog).resolve(catalog.load_path(child))
            self.assertEqual(result.values["temperature"], 245)
            self.assertEqual(result.sources["temperature"], "Root")
            self.assertEqual(result.source_paths["temperature"], root.resolve())
            self.assertEqual(result.sources["speed"], "Child")
            self.assertEqual(result.chain, ("Root", "Child"))
            self.assertEqual(len(result.fingerprint), 64)

    def test_cycle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            first = write_profile(directory, "First", {"inherits": "Second"})
            write_profile(directory, "Second", {"inherits": "First"})
            catalog = ProfileCatalog([directory])
            with self.assertRaisesRegex(RuntimeError, "inheritance cycle"):
                ProfileResolver(catalog).resolve(catalog.load_path(first))

    def test_parent_resolution_prefers_same_vendor_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "OrcaSlicer"
            expected = write_profile(
                root / "system",
                "fdm_filament_pla",
                {"temperature": 215},
                "VendorOne/filament/base/fdm_filament_pla.json",
            )
            write_profile(
                root / "system",
                "fdm_filament_pla",
                {"temperature": 225},
                "VendorTwo/filament/base/fdm_filament_pla.json",
            )
            child = write_profile(
                root / "system",
                "Vendor PLA",
                {"inherits": "fdm_filament_pla"},
                "VendorOne/filament/Vendor/Vendor PLA.json",
            )
            catalog = ProfileCatalog([root])

            result = ProfileResolver(catalog).resolve(catalog.load_path(child))

            self.assertEqual(result.values["temperature"], 215)
            self.assertEqual(result.source_paths["temperature"], expected.resolve())
            with self.assertRaisesRegex(RuntimeError, "ambiguous"):
                catalog.find("fdm_filament_pla")

    def test_parent_resolution_falls_back_to_unique_match_in_same_application(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            expected = write_profile(
                root / "BambuStudio/system",
                "Shared Base",
                {"temperature": 215},
                "Shared/filament/Shared Base.json",
            )
            child = write_profile(
                root / "BambuStudio/system",
                "Vendor PLA",
                {"inherits": "Shared Base"},
                "BBL/filament/Vendor PLA.json",
            )
            write_profile(
                root / "OrcaSlicer/system",
                "Shared Base",
                {"temperature": 225},
                "Other/filament/Shared Base.json",
            )
            catalog = ProfileCatalog([root])

            result = ProfileResolver(catalog).resolve(catalog.load_path(child))

            self.assertEqual(result.values["temperature"], 215)
            self.assertEqual(result.source_paths["temperature"], expected.resolve())

    def test_parent_resolution_prefers_nearest_match_within_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "OrcaSlicer/profiles/InfiMech/machine"
            expected = write_profile(root, "Machine Base", {"speed": 500})
            write_profile(root / "Variant", "Machine Base", {"speed": 300})
            child = write_profile(root, "Klipper Base", {"inherits": "Machine Base"})
            catalog = ProfileCatalog([root.parents[2]])

            result = ProfileResolver(catalog).resolve(catalog.load_path(child))

            self.assertEqual(result.values["speed"], 500)
            self.assertEqual(result.source_paths["speed"], expected.resolve())

    def test_parent_resolution_uses_application_shared_package_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "OrcaSlicer/profiles"
            expected = write_profile(
                root / "OrcaFilamentLibrary/filament/base",
                "fdm_filament_pla",
                {"temperature": 215},
            )
            write_profile(
                root / "BBL/filament",
                "fdm_filament_pla",
                {"temperature": 220},
            )
            write_profile(
                root / "OtherVendor/filament",
                "fdm_filament_pla",
                {"temperature": 225},
            )
            child = write_profile(
                root / "VendorWithoutBase/filament",
                "Vendor PLA",
                {"inherits": "fdm_filament_pla"},
            )
            catalog = ProfileCatalog([root])

            result = ProfileResolver(catalog).resolve(catalog.load_path(child))

            self.assertEqual(result.values["temperature"], 215)
            self.assertEqual(result.source_paths["temperature"], expected.resolve())

    def test_nil_vector_positions_inherit_parent_elements_with_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = write_profile(
                directory,
                "Root",
                {"filament_flow_ratio": ["0.97", "0.97"]},
            )
            child = write_profile(
                directory,
                "Child",
                {
                    "inherits": "Root",
                    "filament_flow_ratio": ["1.0185", "nil"],
                },
            )
            catalog = ProfileCatalog([directory])
            result = ProfileResolver(catalog).resolve(catalog.load_path(child))
            self.assertEqual(result.values["filament_flow_ratio"], ["1.0185", "0.97"])
            self.assertEqual(result.element_sources["filament_flow_ratio"], ("Child", "Root"))
            self.assertEqual(
                result.element_source_paths["filament_flow_ratio"],
                (child.resolve(), root.resolve()),
            )


if __name__ == "__main__":
    unittest.main()
