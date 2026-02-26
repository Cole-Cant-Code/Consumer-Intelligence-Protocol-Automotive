"""Escalation persistence — re-exported from CIP.

The CIP generic store uses ``entity_id`` as the SQL column name.
AutoCIP passes ``entity_id_field="vehicle_id"`` so that escalation
dicts keyed by ``"vehicle_id"`` are stored correctly.
"""

from cip_protocol.engagement.store import EscalationStore

__all__ = ["EscalationStore"]
