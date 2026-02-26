"""Vehicle search tool implementation."""

from __future__ import annotations

from typing import Any

from cip_protocol import CIP

from auto_mcp.data.inventory import search_vehicles_windowed
from auto_mcp.tools.orchestration import run_tool_with_orchestration


async def search_vehicles_impl(
    cip: CIP,
    *,
    make: str | None = None,
    model: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    body_type: str | None = None,
    fuel_type: str | None = None,
    limit: int = 10,
    offset: int = 0,
    include_sold: bool = False,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Search the vehicle inventory with optional filters and return CIP-formatted results."""
    if limit <= 0:
        return "Please provide a positive limit."
    if limit > 50:
        return "Please use a limit of 50 or fewer results per request."
    if offset < 0:
        return "Please provide an offset greater than or equal to 0."

    total_matches, top_matches = search_vehicles_windowed(
        make=make,
        model=model,
        year_min=year_min,
        year_max=year_max,
        price_min=price_min,
        price_max=price_max,
        body_type=body_type,
        fuel_type=fuel_type,
        limit=limit,
        offset=offset,
        include_sold=include_sold,
    )

    # Build criteria description for CIP
    criteria_parts: list[str] = []
    if make:
        criteria_parts.append(f"make: {make}")
    if model:
        criteria_parts.append(f"model: {model}")
    if year_min:
        criteria_parts.append(f"year from: {year_min}")
    if year_max:
        criteria_parts.append(f"year to: {year_max}")
    if price_min is not None:
        criteria_parts.append(f"min price: ${price_min:,.0f}")
    if price_max is not None:
        criteria_parts.append(f"max price: ${price_max:,.0f}")
    if body_type:
        criteria_parts.append(f"body type: {body_type}")
    if fuel_type:
        criteria_parts.append(f"fuel type: {fuel_type}")
    if include_sold:
        criteria_parts.append("including sold inventory")

    criteria_str = ", ".join(criteria_parts) if criteria_parts else "all vehicles"
    user_input = (
        f"Search for vehicles matching: {criteria_str}. "
        f"Use pagination offset: {offset}, limit: {limit}. "
        "For every result shown, include the exact Vehicle ID."
    )

    data_context: dict[str, Any] = {
        "total_matches": total_matches,
        "showing": len(top_matches),
        "offset": offset,
        "limit": limit,
        "search_criteria": criteria_str,
        "vehicles": [
            {
                "id": v["id"],
                "year": v["year"],
                "make": v["make"],
                "model": v["model"],
                "trim": v["trim"],
                "price": v["price"],
                "mileage": v["mileage"],
                "fuel_type": v["fuel_type"],
                "body_type": v["body_type"],
                "dealer_name": v["dealer_name"],
                "dealer_location": v["dealer_location"],
                "availability_status": v["availability_status"],
            }
            for v in top_matches
        ],
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="search_vehicles",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )
