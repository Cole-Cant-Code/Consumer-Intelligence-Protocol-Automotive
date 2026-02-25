"""Lead escalation detection — pure logic, no DB or I/O."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Status transitions that trigger an escalation.
ESCALATION_TRANSITIONS: dict[tuple[str, str], str] = {
    ("new", "engaged"): "cold_to_warm",
    ("new", "qualified"): "cold_to_hot",
    ("engaged", "qualified"): "warm_to_hot",
}

EscalationCallback = Callable[[dict[str, Any]], None]

_lock = threading.RLock()
_callbacks: list[EscalationCallback] = []


def register_callback(cb: EscalationCallback) -> None:
    """Register an external callback for escalation events (e.g. webhooks)."""
    with _lock:
        _callbacks.append(cb)


def clear_callbacks() -> None:
    """Remove all callbacks. Intended for tests."""
    with _lock:
        _callbacks.clear()


def check_escalation(
    *,
    lead_id: str,
    old_status: str,
    new_status: str,
    score: float,
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    source_channel: str,
    action: str,
) -> dict[str, Any] | None:
    """Return an escalation record if the transition warrants one, else None.

    Does NOT persist — the caller is responsible for dedup and storage.
    """
    if old_status == new_status:
        return None

    escalation_type = ESCALATION_TRANSITIONS.get((old_status, new_status))
    if escalation_type is None:
        return None

    escalation: dict[str, Any] = {
        "id": f"esc-{uuid.uuid4().hex[:12]}",
        "lead_id": lead_id,
        "escalation_type": escalation_type,
        "old_status": old_status,
        "new_status": new_status,
        "score": score,
        "vehicle_id": vehicle_id,
        "customer_name": customer_name,
        "customer_contact": customer_contact,
        "source_channel": source_channel,
        "triggering_action": action,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with _lock:
        for cb in _callbacks:
            try:
                cb(escalation)
            except Exception:
                logger.exception("Escalation callback failed")

    return escalation
