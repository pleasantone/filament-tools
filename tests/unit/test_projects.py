from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from filament_tools.editor.projects import (
    COMPOSITION_PROJECT_FORMAT,
    LEGACY_COMPOSITION_PROJECT_FORMAT,
    load_composition_project_document,
    save_composition_project,
)
from filament_tools.model import CompositionRecipe


class CompositionProjectTests(unittest.TestCase):
    def test_current_project_can_be_saved_atomically_more_than_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "material.ftdraft"
            first = CompositionRecipe(name="First", starting_source="source.json")
            second = CompositionRecipe(name="Second", starting_source="source.json")

            save_composition_project(path, first)
            original_document = json.loads(path.read_text(encoding="utf-8"))
            save_composition_project(path, second, replace=True, project_name="Material project")

            loaded, metadata = load_composition_project_document(path)
            self.assertEqual(loaded.name, "Second")
            self.assertEqual(metadata["name"], "Material project")
            self.assertEqual(metadata["created_at"], original_document["project"]["created_at"])
            self.assertTrue(metadata["modified_at"])
            self.assertFalse(list(path.parent.glob(f".{path.name}.*.tmp")))

    def test_save_as_remains_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "material.ftdraft"
            recipe = CompositionRecipe(name="Material", starting_source="source.json")
            save_composition_project(path, recipe)

            with self.assertRaises(FileExistsError):
                save_composition_project(path, recipe)

    def test_legacy_composition_project_loads_with_synthesized_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "legacy.ftdraft"
            recipe = CompositionRecipe(name="Legacy material", starting_source="source.json")
            path.write_text(
                json.dumps(
                    {
                        "format": LEGACY_COMPOSITION_PROJECT_FORMAT,
                        "recipe": recipe.model_dump(mode="json"),
                    }
                ),
                encoding="utf-8",
            )

            loaded, metadata = load_composition_project_document(path)

            self.assertEqual(loaded, recipe)
            self.assertEqual(metadata["name"], "Legacy material")
            self.assertIsNone(metadata["created_at"])

    def test_new_project_uses_versioned_metadata_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "material.ftdraft"
            recipe = CompositionRecipe(name="Material", starting_source="source.json")

            save_composition_project(path, recipe)

            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["format"], COMPOSITION_PROJECT_FORMAT)
            self.assertEqual(document["project"]["name"], "Material")


if __name__ == "__main__":
    unittest.main()
