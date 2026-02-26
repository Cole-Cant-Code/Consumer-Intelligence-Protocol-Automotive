"""Lead escalation detection — automotive domain wrapper.

Core logic lives in ``cip_protocol.engagement.detector``.  This module
provides the AutoCIP-specific transition map and backward-compatible
module-level callback management.
"""

from __future__ import annotations

from typing import Any

from cip_protocol.engagement.detector import (
    EscalationCallback,
    EscalationConfig,
    EscalationDetector,
)

# Automotive-specific status transitions.
ESCALATION_TRANSITIONS: dict[tuple[str, str], str] = {
    ("new", "engaged"): "cold_to_warm",
    ("new", "qualified"): "cold_to_hot",
    ("engaged", "qualified"): "warm_to_hot",
}

_AUTO_CONFIG = EscalationConfig(
    transitions=ESCALATION_TRANSITIONS,
    entity_id_field="vehicle_id",
)

_detector = EscalationDetector(_AUTO_CONFIG)


def register_callback(cb: EscalationCallback) -> None:
    """Register an external callback for escalation events (e.g. webhooks)."""
    _detector.register_callback(cb)


def clear_callbacks() -> None:
    """Remove all callbacks. Intended for tests."""
    _detector.clear_callbacks()


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

    Preserves the original AutoCIP call signature — maps ``vehicle_id``
    to the generic ``entity_id`` parameter expected by CIP.
    """
    return _detector.check(
        lead_id=lead_id,
        old_status=old_status,
        new_status=new_status,
        score=score,
        entity_id=vehicle_id,
        customer_name=customer_name,
        customer_contact=customer_contact,
        source_channel=source_channel,
        action=action,
    )
