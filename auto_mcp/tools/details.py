"""Vehicle details tool implementation."""

from __future__ import annotations

from cip_protocol import CIP

from auto_mcp.data.inventory import get_vehicle
from auto_mcp.tools.orchestration import run_tool_with_orchestration


async def get_vehicle_details_impl(
    cip: CIP,
    *,
    vehicle_id: str,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Get detailed information about a specific vehicle."""
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    user_input = (
        f"Tell me about the {vehicle['year']} {vehicle['make']} {vehicle['model']} "
        f"{vehicle['trim']} (ID: {vehicle_id})"
    )

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="get_vehicle_details",
        data_context={"vehicle": vehicle},
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )
