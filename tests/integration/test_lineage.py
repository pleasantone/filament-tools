from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from filament_tools.catalog import ProfileCatalog
from filament_tools.lineage import inheritance_graph, lineage_context, lineage_descendants
from tests.support import SRC, root_profile, write_profile  # noqa: F401


class LineageIntegrationTests(unittest.TestCase):
    def test_graph_includes_roots_children_and_broken_parents(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = write_profile(directory, "Root PETG", root_profile("Root PETG"))
            child = write_profile(directory, "Child PETG", {"inherits": "Root PETG", "speed": 2})
            broken = write_profile(directory, "Broken PETG", {"inherits": "Missing PETG"})
            graph = inheritance_graph(ProfileCatalog([directory]))
            nodes = {node["path"]: node for node in graph["nodes"]}
            edges = {(edge["parent"], edge["child"]) for edge in graph["edges"]}
            self.assertIn((str(root.resolve()), str(child.resolve())), edges)
            self.assertEqual(nodes[str(root.resolve())]["status"], "root")
            self.assertEqual(nodes[str(broken.resolve())]["status"], "broken")
            self.assertIn("could not resolve", nodes[str(broken.resolve())]["error"])

    def test_scoped_lineage_loads_ancestors_and_one_child_level(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            root = write_profile(directory, "Root PETG", root_profile("Root PETG"))
            child = write_profile(directory, "Child PETG", {"inherits": "Root PETG"})
            grandchild = write_profile(directory, "Grandchild PETG", {"inherits": "Child PETG"})
            catalog = ProfileCatalog([directory])

            context = lineage_context(catalog, catalog.load_path(child))
            descendants = lineage_descendants(catalog, catalog.load_path(root))

            self.assertEqual([node["name"] for node in context["ancestors"]], ["Root PETG"])
            self.assertEqual([node["name"] for node in context["children"]], ["Grandchild PETG"])
            self.assertEqual(context["children"][0]["child_count"], 0)
            self.assertEqual(
                {node["path"] for node in descendants["nodes"]},
                {str(root.resolve()), str(child.resolve()), str(grandchild.resolve())},
            )


if __name__ == "__main__":
    unittest.main()
