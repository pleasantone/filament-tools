from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from filament_tools.catalog import ProfileCatalog
from filament_tools.editor.app import create_editor_app
from filament_tools.editor.security import is_loopback_host, validate_editor_host
from filament_tools.service import ProfileWorkbench


class EditorSecurityTests(unittest.TestCase):
    def test_only_loopback_bind_addresses_are_accepted(self) -> None:
        for value in ("localhost", "127.0.0.1", "127.0.0.2", "::1"):
            with self.subTest(value=value):
                self.assertTrue(is_loopback_host(value))
                self.assertEqual(validate_editor_host(value), value)
        for value in ("0.0.0.0", "::", "192.168.1.10", "example.com"):
            with self.subTest(value=value):
                self.assertFalse(is_loopback_host(value))
                with self.assertRaisesRegex(ValueError, "only bind"):
                    validate_editor_host(value)

    def test_api_rejects_non_loopback_host_and_origin(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            app = create_editor_app(ProfileWorkbench(ProfileCatalog([Path(raw)])), mount_ui=False)
            client = TestClient(app, base_url="http://127.0.0.1")

            self.assertEqual(client.get("/api/profiles").status_code, 200)
            self.assertEqual(
                client.get("/api/profiles", headers={"host": "profiles.example"}).status_code,
                403,
            )
            self.assertEqual(
                client.get(
                    "/api/profiles", headers={"origin": "https://profiles.example"}
                ).status_code,
                403,
            )


if __name__ == "__main__":
    unittest.main()
