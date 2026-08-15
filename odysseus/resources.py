"""Resolve assets from either a source checkout or an installed wheel."""

from __future__ import annotations

import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent.parent


def resource_path(group: str, name: str = "") -> Path:
    """Return a shipped resource path, preferring the editable source tree."""

    relative = Path(group) / name if name else Path(group)
    source = SOURCE_ROOT / relative
    if source.exists():
        return source
    candidates = [Path(sys.prefix), *Path(__file__).resolve().parents]
    for prefix in candidates:
        installed = prefix / "share" / "odysseus" / relative
        if installed.exists():
            return installed
    raise FileNotFoundError(f"Odysseus resource is missing: {relative}")
