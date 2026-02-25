"""Inventory stats and lead analytics tool implementations."""

from __future__ import annotations

from typing import Any

from cip_protocol import CIP

from auto_mcp.data.inventory import get_inventory_stats, get_lead_analytics
from auto_mcp.tools.orchestration import run_tool_with_orchestration


async def get_inventory_stats_impl(
    cip: CIP,
    *,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Get comprehensive inventory analytics via CIP."""
    stats = get_inventory_stats()

    user_input = "Show inventory statistics and health metrics"

    data_context: dict[str, Any] = {"stats": stats}

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="get_inventory_stats",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )


async def get_lead_analytics_impl(
    cip: CIP,
    *,
    days: int = 30,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Get lead analytics for dealer engagement reporting via CIP."""
    analytics = get_lead_analytics(days)

    user_input = f"Show lead analytics for the last {days} days"

    data_context: dict[str, Any] = {"analytics": analytics}

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="get_lead_analytics",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )
