"""Lead escalation tool implementations."""

from __future__ import annotations

from typing import Any

from cip_protocol import CIP

from auto_mcp.escalation.store import EscalationStore
from auto_mcp.tools.orchestration import run_tool_with_orchestration


async def get_escalations_impl(
    cip: CIP,
    escalation_store: EscalationStore,
    *,
    limit: int = 20,
    include_delivered: bool = False,
    escalation_type: str = "",
    days: int = 30,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Return recent lead escalation alerts for dealer review."""
    if limit <= 0:
        return "Limit must be greater than 0."
    if limit > 200:
        return "Limit must be 200 or fewer."
    if include_delivered and days <= 0:
        return "Days must be greater than 0 when include_delivered is true."

    if include_delivered:
        escalations = escalation_store.get_all(
            limit=limit,
            days=days,
            escalation_type=escalation_type,
        )
    else:
        escalations = escalation_store.get_pending(
            limit=limit,
            escalation_type=escalation_type,
        )

    filter_parts: list[str] = []
    if escalation_type:
        filter_parts.append(f"type '{escalation_type}'")
    if include_delivered:
        filter_parts.append(f"last {days} days including acknowledged")
    else:
        filter_parts.append("pending only")
    filter_str = ", ".join(filter_parts) if filter_parts else "all pending"

    user_input = (
        f"Present {len(escalations)} lead escalation alert(s) ({filter_str}). "
        "For each alert, explain what threshold was crossed, why it matters, "
        "and what the dealer should do next."
    )

    data_context: dict[str, Any] = {
        "escalation_count": len(escalations),
        "filter": filter_str,
        "escalations": escalations,
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="get_escalations",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )


def acknowledge_escalation_impl(
    escalation_store: EscalationStore,
    *,
    escalation_id: str,
) -> str:
    """Mark an escalation as delivered/acknowledged."""
    if not escalation_id or not escalation_id.strip():
        return "Error: escalation_id is required."

    marked = escalation_store.mark_delivered(escalation_id.strip())
    if marked:
        return f"Escalation {escalation_id} acknowledged."
    return f"Escalation {escalation_id} not found or already acknowledged."
