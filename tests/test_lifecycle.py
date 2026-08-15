from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from odysseus.lifecycle import ServerLease


class LifecycleLeaseTests(unittest.TestCase):
    def test_only_one_server_can_own_a_state_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first = ServerLease(temp)
            second = ServerLease(temp)
            first.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "another Odysseus server"):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()

    def test_server_refuses_active_maintenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "runtime" / "maintenance.lock"
            lock.mkdir(parents=True)
            (lock / "owner.json").write_text(
                json.dumps({"pid": os.getpid(), "token": "installer"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "maintenance is active"):
                ServerLease(temp).acquire()


if __name__ == "__main__":
    unittest.main()
