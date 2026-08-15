from __future__ import annotations

import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from odysseus import __version__
from odysseus.cli import cmd_doctor, parser


class CLITests(unittest.TestCase):
    def test_start_is_a_serve_alias_and_version_is_current(self) -> None:
        args = parser().parse_args(["start", "--port", "9911"])
        self.assertEqual(args.port, 9911)
        self.assertEqual(args.func.__name__, "cmd_serve")
        self.assertEqual(__version__, "0.6.1")

    def test_doctor_has_readable_and_json_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            human_args = argparse.Namespace(state_dir=Path(temp) / "human", json=False)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = cmd_doctor(human_args)
            self.assertIn("Odysseus 0.6.1", output.getvalue())
            self.assertIn("Git", output.getvalue())
            self.assertIn(result, {0, 1})

            json_args = argparse.Namespace(state_dir=Path(temp) / "json", json=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                cmd_doctor(json_args)
            self.assertIn('"state_dir"', output.getvalue())


if __name__ == "__main__":
    unittest.main()
