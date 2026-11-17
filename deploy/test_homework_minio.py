"""Собранный Compose разделяет root-настройки MinIO и права приложения Homework."""

import unittest

from test_migration_compose import ROOT, configuration


class HomeworkStorageComposeTests(unittest.TestCase):
    def test_storage_is_private_and_not_required_for_api_start(self):
        for overlay in (None, "compose.dev.yaml", "compose.production.yaml"):
            with self.subTest(overlay=overlay):
                services = configuration(overlay)
                storage = services["homework-minio"]
                init = services["homework-minio-init"]
                api = services["homework-api"]
                self.assertFalse(storage.get("ports"))
                self.assertEqual(storage["volumes"][0]["target"], "/data")
                self.assertTrue(
                    all(mount.get("read_only", False) for mount in init["volumes"])
                )
                self.assertEqual(
                    init["depends_on"]["homework-minio"]["condition"], "service_healthy"
                )
                api_env_files = [entry["path"] for entry in api["env_file"]]
                root_env = str(ROOT / "services/homework/.minio.env")
                self.assertNotIn(root_env, api_env_files)
                self.assertIn(root_env, [entry["path"] for entry in init["env_file"]])
                self.assertNotIn("homework-minio-init", api.get("depends_on", {}))


if __name__ == "__main__":
    unittest.main()
