from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI

from tests.support import SRC, root_profile, write_profile  # noqa: F401

try:
    from fastapi.testclient import TestClient
except ImportError:  # The required suite can run before optional dev installation.
    TestClient = None

from filament_tools.catalog import ProfileCatalog
from filament_tools.service import ProfileWorkbench


@unittest.skipIf(TestClient is None, "FastAPI development dependencies are not installed")
class EditorIntegrationTests(unittest.TestCase):
    def test_catalog_reload_finds_new_files_and_invalidates_resolution_cache(self) -> None:
        from filament_tools.editor.app import create_editor_app

        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = write_profile(
                directory,
                "Reload PETG",
                {**root_profile("Reload PETG"), "nozzle_temperature": ["250"]},
            )
            client = TestClient(
                create_editor_app(ProfileWorkbench(ProfileCatalog([directory])), mount_ui=False),
                base_url="http://127.0.0.1",
            )
            first = client.get("/api/profile", params={"selector": str(source)})
            self.assertEqual(first.json()["effective"]["nozzle_temperature"], ["250"])

            write_profile(
                directory,
                "Reload PETG",
                {**root_profile("Reload PETG"), "nozzle_temperature": ["265"]},
            )
            write_profile(directory, "New PETG", root_profile("New PETG"))
            stale = client.get("/api/profile", params={"selector": str(source)})
            self.assertEqual(stale.json()["effective"]["nozzle_temperature"], ["250"])

            reloaded = client.post("/api/catalog/reload")
            self.assertEqual(reloaded.status_code, 200, reloaded.text)
            refreshed = client.get("/api/profile", params={"selector": str(source)})
            self.assertEqual(refreshed.json()["effective"]["nozzle_temperature"], ["265"])
            catalog = client.get("/api/profiles", params={"q": "New PETG"})
            self.assertEqual(catalog.json()["total"], 1)

    def test_composition_install_requires_and_consumes_reviewed_plan(self) -> None:
        from filament_tools.editor.app import create_editor_app

        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = write_profile(directory, "Install PETG", root_profile("Install PETG"))
            config = directory / "BambuStudio"
            config.mkdir()
            client = TestClient(
                create_editor_app(ProfileWorkbench(ProfileCatalog([directory])), mount_ui=False),
                base_url="http://127.0.0.1",
            )
            request = {
                "recipe": {
                    "name": "Installed PETG",
                    "starting_source": str(source),
                    "output_mode": "root",
                    "identity_mode": "inherit",
                },
                "config_dir": str(config),
            }

            direct = client.post("/api/composition/install", json=request)
            self.assertEqual(direct.status_code, 422)
            preview = client.post("/api/composition/install-plan", json=request)
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertTrue(preview.json()["valid"])
            plan_id = preview.json()["plan_id"]
            self.assertTrue(plan_id)

            installed = client.post("/api/composition/install", json={"plan_id": plan_id})
            self.assertEqual(installed.status_code, 200, installed.text)
            destination = config / "user/default/filament/base/Installed PETG.json"
            self.assertTrue(destination.is_file())
            replayed = client.post("/api/composition/install", json={"plan_id": plan_id})
            self.assertEqual(replayed.status_code, 400)
            self.assertIn("already used", replayed.text)

            request["action"] = "update"
            update_preview = client.post("/api/composition/install-plan", json=request)
            self.assertEqual(update_preview.status_code, 200, update_preview.text)
            self.assertEqual(update_preview.json()["action"], "update")
            self.assertTrue(update_preview.json()["operations"][0]["backup"])
            updated = client.post(
                "/api/composition/install",
                json={"plan_id": update_preview.json()["plan_id"]},
            )
            self.assertEqual(updated.status_code, 200, updated.text)

            request["action"] = "uninstall"
            uninstall_preview = client.post("/api/composition/install-plan", json=request)
            self.assertEqual(uninstall_preview.status_code, 200, uninstall_preview.text)
            uninstalled = client.post(
                "/api/composition/install",
                json={"plan_id": uninstall_preview.json()["plan_id"]},
            )
            self.assertEqual(uninstalled.status_code, 200, uninstalled.text)
            self.assertFalse(destination.exists())

    def test_composition_project_api_supports_save_then_replace(self) -> None:
        from filament_tools.editor.app import create_editor_app

        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            client = TestClient(
                create_editor_app(ProfileWorkbench(ProfileCatalog([directory])), mount_ui=False),
                base_url="http://127.0.0.1",
            )
            path = directory / "project.ftdraft"
            request = {
                "path": str(path),
                "recipe": {
                    "name": "First",
                    "starting_source": "source.json",
                    "output_mode": "root",
                    "identity_mode": "generate",
                    "material_name": "PETG Project Material",
                    "user_id": "identity-namespace",
                    "variants": [
                        {
                            "name": "First H2C",
                            "compatible_printers": ["Bambu Lab H2C 0.4 nozzle"],
                            "edits": {"filament_max_volumetric_speed": ["20"]},
                        }
                    ],
                },
                "project_name": "PETG project",
            }

            created = client.post("/api/composition/project/save", json=request)
            self.assertEqual(created.status_code, 200, created.text)
            duplicate = client.post("/api/composition/project/save", json=request)
            self.assertEqual(duplicate.status_code, 400)
            request["replace"] = True
            request["recipe"]["name"] = "Second"
            replaced = client.post("/api/composition/project/save", json=request)
            self.assertEqual(replaced.status_code, 200, replaced.text)

            loaded = client.get("/api/composition/project/load", params={"path": str(path)})
            self.assertEqual(loaded.status_code, 200, loaded.text)
            self.assertEqual(loaded.json()["recipe"]["name"], "Second")
            self.assertEqual(loaded.json()["project"]["name"], "PETG project")
            self.assertEqual(loaded.json()["recipe"]["material_name"], "PETG Project Material")
            self.assertEqual(
                loaded.json()["recipe"]["variants"][0]["edits"],
                {"filament_max_volumetric_speed": ["20"]},
            )

    def test_routes_can_mount_without_server_workbench_ui(self) -> None:
        from filament_tools.editor.app import create_editor_app

        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            write_profile(directory, "Editor PETG", root_profile("Editor PETG"))
            target = FastAPI()

            result = create_editor_app(
                ProfileWorkbench(ProfileCatalog([directory])),
                target=target,
                mount_ui=False,
            )
            client = TestClient(result, base_url="http://127.0.0.1")

            self.assertIs(result, target)
            self.assertEqual(client.get("/api/profiles").status_code, 200)
            self.assertEqual(client.get("/").status_code, 404)

    def test_catalog_profile_and_preview_endpoints(self) -> None:
        from filament_tools.editor.app import create_editor_app

        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = write_profile(directory, "Editor PETG", root_profile("Editor PETG"))
            donor = write_profile(
                directory,
                "Editor Fast PETG",
                {"inherits": "Editor PETG", "nozzle_temperature": ["265"]},
            )
            write_profile(
                directory,
                "Bambu Lab H2C 0.4 nozzle",
                {"type": "machine", "printer_model": "H2C"},
            )
            client = TestClient(
                create_editor_app(ProfileWorkbench(ProfileCatalog([directory]))),
                base_url="http://127.0.0.1",
            )
            self.assertEqual(client.get("/").status_code, 200)
            catalog_response = client.get("/api/profiles?q=Editor")
            self.assertEqual(catalog_response.status_code, 200)
            self.assertEqual(catalog_response.json()["total"], 2)
            self.assertIn("Editor PETG", catalog_response.text)
            machine_filtered = client.get(
                "/api/profiles",
                params={"q": "Editor", "machine": ["H2C", "X1C"]},
            )
            self.assertEqual(machine_filtered.status_code, 200)
            self.assertEqual(machine_filtered.json()["total"], 2)
            printers = client.get("/api/printers", params={"q": "H2C"})
            self.assertEqual(printers.status_code, 200)
            self.assertEqual(printers.json()["results"], ["Bambu Lab H2C 0.4 nozzle"])
            profile = client.get("/api/profile", params={"selector": str(source)})
            self.assertEqual(profile.status_code, 200)
            self.assertEqual(profile.json()["summary"]["type"], "filament")
            self.assertIn("overrides", profile.json())
            preview = client.post(
                "/api/preview",
                json={
                    "name": "Editor PETG root",
                    "source": str(source),
                    "output_mode": "root",
                    "identity_mode": "inherit",
                },
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.json()["artifacts"][0]["data"]["name"], "Editor PETG root")
            output = directory / "Editor PETG root.json"
            built = client.post(
                "/api/build",
                json={
                    "draft": {
                        "name": "Editor PETG root",
                        "source": str(source),
                        "output_mode": "root",
                        "identity_mode": "inherit",
                    },
                    "output_path": str(output),
                },
            )
            self.assertEqual(built.status_code, 200, built.text)
            self.assertTrue(output.is_file())

            comparison = client.post(
                "/api/compare",
                json={"profiles": [str(source), str(donor)], "only_different": True},
            )
            self.assertEqual(comparison.status_code, 200, comparison.text)
            self.assertEqual(comparison.json()["rows"][0]["key"], "nozzle_temperature")
            overrides = client.post(
                "/api/compare",
                json={
                    "profiles": [str(source), str(donor)],
                    "mode": "overrides",
                    "only_different": True,
                },
            )
            self.assertEqual(overrides.status_code, 200, overrides.text)
            self.assertIn("nozzle_temperature", {row["key"] for row in overrides.json()["rows"]})

            recipe = {
                "name": "Editor composed PETG",
                "starting_source": str(source),
                "reference_sources": [str(donor)],
                "sparse_parent": str(source),
                "output_mode": "sparse",
                "selections": {"nozzle_temperature": {"kind": "source", "source": str(donor)}},
            }
            composition = client.post("/api/composition", json=recipe)
            self.assertEqual(composition.status_code, 200, composition.text)
            temperature = next(
                row for row in composition.json()["rows"] if row["key"] == "nozzle_temperature"
            )
            self.assertEqual(temperature["result"]["value"], ["265"])
            sparse_preview = client.post("/api/composition/preview", json=recipe)
            self.assertEqual(sparse_preview.status_code, 200, sparse_preview.text)
            self.assertEqual(
                sparse_preview.json()["artifacts"][0]["data"]["inherits"], "Editor PETG"
            )
            recipe["output_mode"] = "root"
            root_preview = client.post("/api/composition/preview", json=recipe)
            self.assertEqual(root_preview.status_code, 200, root_preview.text)
            self.assertNotIn("inherits", root_preview.json()["artifacts"][0]["data"])
            lineage = client.get("/api/lineage/context", params={"selector": str(donor)})
            self.assertEqual(lineage.status_code, 200)
            self.assertEqual(lineage.json()["ancestors"][0]["name"], "Editor PETG")
            descendants = client.get("/api/lineage/descendants", params={"selector": str(source)})
            self.assertEqual(descendants.status_code, 200)
            self.assertEqual(len(descendants.json()["nodes"]), 2)


if __name__ == "__main__":
    unittest.main()
