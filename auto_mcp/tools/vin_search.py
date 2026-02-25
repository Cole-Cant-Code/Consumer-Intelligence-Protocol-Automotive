"""VIN lookup tool implementation."""

from __future__ import annotations

import re
from typing import Any

from cip_protocol import CIP

from auto_mcp.data.inventory import get_vehicle_by_vin
from auto_mcp.tools.orchestration import run_tool_with_orchestration

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.IGNORECASE)


async def search_by_vin_impl(
    cip: CIP,
    *,
    vin: str,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Look up a vehicle by VIN and return CIP-formatted results."""
    vin = vin.strip().upper()
    if not _VIN_RE.match(vin):
        return (
            f"Invalid VIN '{vin}'. A VIN must be exactly 17 "
            "alphanumeric characters (no I, O, Q)."
        )

    vehicle = get_vehicle_by_vin(vin)
    if not vehicle:
        return f"No vehicle found with VIN {vin} in our inventory."

    user_input = f"Look up vehicle with VIN: {vin}"

    data_context: dict[str, Any] = {
        "vehicle": {
            "id": vehicle["id"],
            "vin": vehicle["vin"],
            "year": vehicle["year"],
            "make": vehicle["make"],
            "model": vehicle["model"],
            "trim": vehicle["trim"],
            "body_type": vehicle["body_type"],
            "price": vehicle["price"],
            "mileage": vehicle["mileage"],
            "exterior_color": vehicle["exterior_color"],
            "interior_color": vehicle["interior_color"],
            "fuel_type": vehicle["fuel_type"],
            "mpg_city": vehicle["mpg_city"],
            "mpg_highway": vehicle["mpg_highway"],
            "engine": vehicle["engine"],
            "transmission": vehicle["transmission"],
            "drivetrain": vehicle["drivetrain"],
            "features": vehicle["features"],
            "safety_rating": vehicle["safety_rating"],
            "dealer_name": vehicle["dealer_name"],
            "dealer_location": vehicle["dealer_location"],
            "availability_status": vehicle["availability_status"],
            "source": vehicle.get("source", ""),
        },
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="search_by_vin",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )
