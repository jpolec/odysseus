#!/usr/bin/env python3
"""Deterministic fake JSON-stream agent used by end-to-end tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path


prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
if "read-only review agent" in prompt:
    text = "No material concerns. The deterministic demo change is ready."
else:
    Path("odysseus-demo.txt").write_text("created by the Odysseus test agent\n")
    text = "Created odysseus-demo.txt in the isolated worktree."

print(json.dumps({"type": "assistant", "message": {"content": [{"text": text}]}}))
