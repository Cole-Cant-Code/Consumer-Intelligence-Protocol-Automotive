"""Vehicle comparison tool implementation."""

from __future__ import annotations

from typing import Any

from cip_protocol import CIP

from auto_mcp.data.inventory import get_vehicle
from auto_mcp.tools.orchestration import run_tool_with_orchestration


async def compare_vehicles_impl(
    cip: CIP,
    *,
    vehicle_ids: list[str],
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Compare 2-3 vehicles side by side."""
    if len(vehicle_ids) < 2:
        return "Please provide at least 2 vehicle IDs to compare."
    if len(vehicle_ids) > 3:
        return "Comparison supports a maximum of 3 vehicles at a time."

    vehicles: list[dict[str, Any]] = []
    for vid in vehicle_ids:
        v = get_vehicle(vid)
        if v is None:
            return f"Vehicle with ID '{vid}' not found in inventory."
        vehicles.append(v)

    labels = [
        f"{v['year']} {v['make']} {v['model']} {v['trim']}" for v in vehicles
    ]
    user_input = f"Compare these vehicles: {', '.join(labels)}"

    data_context: dict[str, Any] = {
        "vehicles": vehicles,
        "comparison_count": len(vehicles),
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="compare_vehicles",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )
