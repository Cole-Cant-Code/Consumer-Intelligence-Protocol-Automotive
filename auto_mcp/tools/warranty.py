"""Warranty information tool implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cip_protocol import CIP

from auto_mcp.constants import LUXURY_MAKES
from auto_mcp.data.inventory import get_vehicle
from auto_mcp.tools.orchestration import run_tool_with_orchestration


def _is_within(years_used: int, miles_used: int, years_limit: int, miles_limit: int) -> bool:
    return years_used <= years_limit and miles_used <= miles_limit


async def get_warranty_info_impl(
    cip: CIP,
    *,
    vehicle_id: str,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Estimate likely warranty coverage windows based on vehicle age and mileage."""
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    current_year = datetime.now(timezone.utc).year
    years_used = max(0, current_year - int(vehicle["year"]))
    miles_used = int(vehicle["mileage"])

    luxury = vehicle["make"].lower() in LUXURY_MAKES
    fuel_type = vehicle["fuel_type"].lower()

    if luxury:
        basic_years, basic_miles = 4, 50_000
    else:
        basic_years, basic_miles = 3, 36_000

    powertrain_years, powertrain_miles = 5, 60_000

    basic_active = _is_within(years_used, miles_used, basic_years, basic_miles)
    powertrain_active = _is_within(
        years_used,
        miles_used,
        powertrain_years,
        powertrain_miles,
    )

    ev_battery_active = False
    if fuel_type in {"electric", "hybrid"}:
        ev_battery_active = _is_within(years_used, miles_used, 8, 100_000)

    cpo_eligible = years_used <= 6 and miles_used <= 80_000

    user_input = (
        f"Summarize likely warranty coverage for {vehicle['year']} {vehicle['make']} "
        f"{vehicle['model']} (ID: {vehicle_id})"
    )

    data_context: dict[str, Any] = {
        "vehicle": {
            "id": vehicle["id"],
            "year": vehicle["year"],
            "make": vehicle["make"],
            "model": vehicle["model"],
            "trim": vehicle["trim"],
            "mileage": vehicle["mileage"],
            "fuel_type": vehicle["fuel_type"],
        },
        "usage": {
            "years_used": years_used,
            "miles_used": miles_used,
        },
        "coverage": {
            "basic": {
                "likely_active": basic_active,
                "term_years": basic_years,
                "term_miles": basic_miles,
            },
            "powertrain": {
                "likely_active": powertrain_active,
                "term_years": powertrain_years,
                "term_miles": powertrain_miles,
            },
            "ev_battery": {
                "likely_active": ev_battery_active,
                "term_years": 8,
                "term_miles": 100_000,
            },
            "cpo_eligibility": cpo_eligible,
        },
        "disclaimer": (
            "Warranty terms vary by make, trim, and in-service date. "
            "Always confirm exact coverage with the manufacturer or dealer."
        ),
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="get_warranty_info",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )
