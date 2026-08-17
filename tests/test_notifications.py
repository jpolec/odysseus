from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odysseus.notifications import NotificationManager
from odysseus.store import RunStore


class Response:
    status = 204

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *_args):  # noqa: ANN204
        return False


class NotificationTests(unittest.TestCase):
    def test_webhook_delivery_is_audited_without_persisting_secret_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = RunStore(root / "state")
            manager = NotificationManager(store)
            run = store.create({"task": "Review this", "project_path": str(project)})
            destination = {"type": "webhook", "name": "ops", "url": "https://secret.example.test/hook/token"}

            with mock.patch("odysseus.notifications.request.urlopen", return_value=Response()) as call:
                manager._deliver(
                    destination,
                    run,
                    "run.failed",
                    {
                        "message": "Checks failed: Authorization: Bearer abcdefghijklmnop",
                        "nested": {"api_key": "sk-abcdefghijklmnop1234"},
                    },
                )

            request_value = call.call_args.args[0]
            delivered = json.loads(request_value.data)
            self.assertEqual(delivered["event"], "run.failed")
            self.assertIn("[REDACTED]", delivered["message"])
            self.assertNotIn("abcdefghijklmnop", request_value.data.decode())
            journal = manager.journal.read_text()
            self.assertIn('"destination":"ops"', journal)
            self.assertNotIn("secret.example.test", journal)
            self.assertNotIn("abcdefghijklmnop", journal)


if __name__ == "__main__":
    unittest.main()
