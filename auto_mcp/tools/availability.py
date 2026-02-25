"""Availability check tool implementation."""

from __future__ import annotations

from typing import Any

from cip_protocol import CIP

from auto_mcp.data.inventory import get_vehicle


async def check_availability_impl(
    cip: CIP,
    *,
    vehicle_id: str,
    zip_code: str = "",
) -> str:
    """Check availability and dealer info for a specific vehicle."""
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    user_input = (
        f"Check availability of the {vehicle['year']} {vehicle['make']} "
        f"{vehicle['model']} {vehicle['trim']} (ID: {vehicle_id})"
    )
    if zip_code:
        user_input += f" near zip code {zip_code}"

    data_context: dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "vehicle_summary": (
            f"{vehicle['year']} {vehicle['make']} {vehicle['model']} {vehicle['trim']}"
        ),
        "availability_status": vehicle["availability_status"],
        "dealer_name": vehicle["dealer_name"],
        "dealer_location": vehicle["dealer_location"],
        "price": vehicle["price"],
        "customer_zip_code": zip_code,
    }

    result = await cip.run(
        user_input, tool_name="check_availability", data_context=data_context
    )
    return result.response.content
