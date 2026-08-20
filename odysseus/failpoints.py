"""Deterministic fault injection for persistence and runtime recovery tests.

Failpoints are inert unless ``ODYSSEUS_FAILPOINT`` names an exact point. The
default mode raises an exception for focused unit tests; ``exit`` terminates
the process immediately so subprocess tests exercise real crash windows
without cleanup handlers.
"""

from __future__ import annotations

import os
import threading


FAILPOINT_EXIT_CODE = 86
_guard = threading.Lock()
_counts: dict[str, int] = {}


class InjectedFailure(RuntimeError):
    """A configured deterministic failpoint fired."""


def reset_failpoints() -> None:
    """Reset process-local occurrence counters used by deterministic tests."""

    with _guard:
        _counts.clear()


def _configured_occurrence(name: str) -> int | None:
    raw = os.environ.get("ODYSSEUS_FAILPOINT", "")
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        point, separator, occurrence = item.partition("@")
        if point != name:
            continue
        if not separator:
            return 1
        try:
            return max(1, int(occurrence))
        except ValueError:
            return None
    return None


def failpoint(name: str) -> None:
    """Fire one exact configured point on its requested occurrence."""

    occurrence = _configured_occurrence(name)
    if occurrence is None:
        return
    with _guard:
        count = _counts.get(name, 0) + 1
        _counts[name] = count
    if count != occurrence:
        return
    mode = os.environ.get("ODYSSEUS_FAILPOINT_MODE", "raise").strip().lower()
    if mode == "exit":
        os._exit(FAILPOINT_EXIT_CODE)
    if mode != "raise":
        raise RuntimeError(f"unsupported ODYSSEUS_FAILPOINT_MODE: {mode}")
    raise InjectedFailure(f"injected failure at {name}")
