"""Inventory stats and lead analytics tool implementations."""

from __future__ import annotations

from typing import Any

from cip_protocol import CIP

from auto_mcp.data.inventory import get_inventory_stats, get_lead_analytics


async def get_inventory_stats_impl(cip: CIP) -> str:
    """Get comprehensive inventory analytics via CIP."""
    stats = get_inventory_stats()

    user_input = "Show inventory statistics and health metrics"

    data_context: dict[str, Any] = {"stats": stats}

    result = await cip.run(
        user_input, tool_name="get_inventory_stats", data_context=data_context,
    )
    return result.response.content


async def get_lead_analytics_impl(cip: CIP, *, days: int = 30) -> str:
    """Get lead analytics for dealer engagement reporting via CIP."""
    analytics = get_lead_analytics(days)

    user_input = f"Show lead analytics for the last {days} days"

    data_context: dict[str, Any] = {"analytics": analytics}

    result = await cip.run(
        user_input, tool_name="get_lead_analytics", data_context=data_context,
    )
    return result.response.content
