"""Shared delivery-state vocabulary."""

from __future__ import annotations

from typing import Any, Mapping


DELIVERED_DELIVERY_STATUSES = frozenset(
    {"applied", "pr_created", "integrated_applied", "integrated_pr_created"}
)
INTEGRATED_DELIVERY_STATUSES = frozenset({"integrated_applied", "integrated_pr_created"})
PENDING_DELIVERY_STATUSES = frozenset({"not_applied", "integration_queued", "failed", "not_started"})


def delivery_status(delivery: Mapping[str, Any] | None) -> str:
    return str((delivery or {}).get("status") or "")


def is_delivered_delivery(delivery: Mapping[str, Any] | None) -> bool:
    return delivery_status(delivery) in DELIVERED_DELIVERY_STATUSES
