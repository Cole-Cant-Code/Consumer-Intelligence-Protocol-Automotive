"""Location-based vehicle search tool implementation."""

from __future__ import annotations

from typing import Any

from cip_protocol import CIP

from auto_mcp.data.inventory import get_zip_database, search_vehicles_by_location
from auto_mcp.tools.orchestration import run_tool_with_orchestration


async def search_by_location_impl(
    cip: CIP,
    *,
    zip_code: str,
    radius_miles: float = 50.0,
    make: str | None = None,
    model: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    body_type: str | None = None,
    fuel_type: str | None = None,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Search vehicles near a ZIP code and return CIP-formatted results."""
    zip_db = get_zip_database()
    coord = zip_db.get(zip_code)
    if not coord:
        return f"ZIP code {zip_code} not recognized. Supported metros include major US cities."

    vehicles = search_vehicles_by_location(
        center_lat=coord.lat,
        center_lng=coord.lng,
        radius_miles=radius_miles,
        make=make,
        model=model,
        year_min=year_min,
        year_max=year_max,
        price_min=price_min,
        price_max=price_max,
        body_type=body_type,
        fuel_type=fuel_type,
    )

    criteria_parts: list[str] = [f"near {coord.city}, {coord.state} ({zip_code})"]
    criteria_parts.append(f"within {radius_miles} miles")
    if make:
        criteria_parts.append(f"make: {make}")
    if model:
        criteria_parts.append(f"model: {model}")
    if body_type:
        criteria_parts.append(f"body type: {body_type}")
    if fuel_type:
        criteria_parts.append(f"fuel type: {fuel_type}")

    criteria_str = ", ".join(criteria_parts)
    user_input = f"Search for vehicles {criteria_str}"

    data_context: dict[str, Any] = {
        "total_matches": len(vehicles),
        "search_center": f"{coord.city}, {coord.state}",
        "radius_miles": radius_miles,
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
                "distance_miles": v.get("distance_miles", 0),
                "availability_status": v["availability_status"],
            }
            for v in vehicles
        ],
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="search_by_location",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )
