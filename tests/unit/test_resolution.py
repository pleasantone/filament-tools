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
