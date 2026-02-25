"""Dealer intelligence tool implementations for lead quality and operations."""

from __future__ import annotations

from typing import Any

from cip_protocol import CIP

from auto_mcp.data.inventory import (
    get_funnel_metrics,
    get_hot_leads,
    get_inventory_aging_report,
    get_lead_detail,
    get_pricing_opportunities,
)


async def get_hot_leads_impl(
    cip: CIP,
    *,
    limit: int = 10,
    min_score: float = 10.0,
    dealer_zip: str = "",
    days: int = 30,
) -> str:
    """Return ranked high-intent leads with context for follow-up prioritization."""
    if limit <= 0:
        return "Limit must be greater than 0."
    if limit > 100:
        return "Limit must be 100 or fewer."
    if min_score < 0:
        return "Minimum score must be greater than or equal to 0."
    if days <= 0:
        return "Days must be greater than 0."

    leads = get_hot_leads(limit=limit, min_score=min_score, dealer_zip=dealer_zip, days=days)

    user_input = (
        f"Show hot leads from the last {days} days"
        + (f" for dealer ZIP {dealer_zip}" if dealer_zip else "")
    )

    data_context: dict[str, Any] = {
        "filters": {
            "limit": limit,
            "min_score": min_score,
            "dealer_zip": dealer_zip,
            "days": days,
        },
        "lead_count": len(leads),
        "hot_leads": leads,
    }

    result = await cip.run(
        user_input,
        tool_name="get_hot_leads",
        data_context=data_context,
    )
    return result.response.content


async def get_lead_detail_impl(cip: CIP, *, lead_id: str, days: int = 90) -> str:
    """Return timeline and score decomposition for a single lead profile."""
    if not lead_id.strip():
        return "Lead ID is required."
    if days <= 0:
        return "Days must be greater than 0."

    detail = get_lead_detail(lead_id.strip(), days=days)
    if detail is None:
        return f"Lead profile '{lead_id}' not found."

    user_input = f"Show lead detail for {lead_id} over the last {days} days"

    data_context: dict[str, Any] = {
        "lead_id": lead_id,
        "days": days,
        "detail": detail,
    }

    result = await cip.run(
        user_input,
        tool_name="get_lead_detail",
        data_context=data_context,
    )
    return result.response.content


async def get_inventory_aging_report_impl(
    cip: CIP,
    *,
    min_days_on_lot: int = 30,
    limit: int = 100,
    dealer_zip: str = "",
) -> str:
    """Return aging and velocity intelligence to surface stale inventory risk."""
    if min_days_on_lot < 0:
        return "Minimum days on lot must be greater than or equal to 0."
    if limit <= 0:
        return "Limit must be greater than 0."
    if limit > 500:
        return "Limit must be 500 or fewer."

    report = get_inventory_aging_report(
        min_days_on_lot=min_days_on_lot,
        limit=limit,
        dealer_zip=dealer_zip,
    )

    user_input = (
        f"Show inventory aging report using stale threshold {min_days_on_lot} days"
        + (f" for dealer ZIP {dealer_zip}" if dealer_zip else "")
    )

    data_context: dict[str, Any] = {
        "report": report,
    }

    result = await cip.run(
        user_input,
        tool_name="get_inventory_aging_report",
        data_context=data_context,
    )
    return result.response.content


async def get_pricing_opportunities_impl(
    cip: CIP,
    *,
    limit: int = 25,
    stale_days_threshold: int = 45,
    overpriced_threshold_pct: float = 5.0,
    underpriced_threshold_pct: float = -5.0,
) -> str:
    """Return prioritized pricing actions based on market context and aging."""
    if limit <= 0:
        return "Limit must be greater than 0."
    if limit > 500:
        return "Limit must be 500 or fewer."
    if stale_days_threshold < 0:
        return "Stale days threshold must be greater than or equal to 0."
    if underpriced_threshold_pct > overpriced_threshold_pct:
        return "Underpriced threshold cannot be greater than overpriced threshold."

    opportunities = get_pricing_opportunities(
        limit=limit,
        stale_days_threshold=stale_days_threshold,
        overpriced_threshold_pct=overpriced_threshold_pct,
        underpriced_threshold_pct=underpriced_threshold_pct,
    )

    user_input = (
        "Show pricing opportunities using market delta thresholds "
        f"{underpriced_threshold_pct}% to {overpriced_threshold_pct}% "
        f"and stale threshold {stale_days_threshold} days"
    )

    data_context: dict[str, Any] = {
        "opportunities": opportunities,
    }

    result = await cip.run(
        user_input,
        tool_name="get_pricing_opportunities",
        data_context=data_context,
    )
    return result.response.content


async def get_funnel_metrics_impl(
    cip: CIP,
    *,
    days: int = 30,
    dealer_zip: str = "",
    breakdown_by: str = "none",
) -> str:
    """Return closed-loop funnel conversion metrics through sale outcomes."""
    if days <= 0:
        return "Days must be greater than 0."

    normalized_breakdown = breakdown_by.strip().lower() or "none"
    if normalized_breakdown not in {"none", "source_channel"}:
        return "breakdown_by must be one of: none, source_channel."

    metrics = get_funnel_metrics(
        days=days,
        dealer_zip=dealer_zip,
        breakdown_by=normalized_breakdown,
    )

    user_input = (
        f"Show funnel metrics for the last {days} days"
        + (f" for dealer ZIP {dealer_zip}" if dealer_zip else "")
        + (f" with breakdown by {normalized_breakdown}" if normalized_breakdown != "none" else "")
    )

    data_context: dict[str, Any] = {
        "metrics": metrics,
    }

    result = await cip.run(
        user_input,
        tool_name="get_funnel_metrics",
        data_context=data_context,
    )
    return result.response.content
