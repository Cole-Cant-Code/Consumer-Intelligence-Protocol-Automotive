"""Test drive scheduling and purchase readiness tool implementations."""

from __future__ import annotations

from typing import Any

from cip_protocol import CIP

from auto_mcp.data.inventory import get_vehicle
from auto_mcp.tools.orchestration import run_tool_with_orchestration


async def schedule_test_drive_impl(
    cip: CIP,
    *,
    vehicle_id: str,
    preferred_date: str,
    preferred_time: str,
    customer_name: str,
    customer_phone: str,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Submit a test drive scheduling request."""
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    user_input = (
        f"Schedule a test drive for the {vehicle['year']} {vehicle['make']} "
        f"{vehicle['model']} {vehicle['trim']} on {preferred_date} at {preferred_time}"
    )

    data_context: dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "vehicle_summary": (
            f"{vehicle['year']} {vehicle['make']} {vehicle['model']} {vehicle['trim']}"
        ),
        "dealer_name": vehicle["dealer_name"],
        "dealer_location": vehicle["dealer_location"],
        "preferred_date": preferred_date,
        "preferred_time": preferred_time,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="schedule_test_drive",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )


async def assess_purchase_readiness_impl(
    cip: CIP,
    *,
    vehicle_id: str,
    budget: float,
    has_financing: bool = False,
    has_insurance: bool = False,
    has_trade_in: bool = False,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Assess how ready the customer is to purchase a specific vehicle."""
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    within_budget = vehicle["price"] <= budget
    checklist = {
        "budget_alignment": "within budget" if within_budget else "over budget",
        "financing_secured": "yes" if has_financing else "not yet",
        "insurance_arranged": "yes" if has_insurance else "not yet",
        "trade_in_evaluated": "yes" if has_trade_in else "not applicable / not yet",
    }
    ready_count = sum([
        within_budget,
        has_financing,
        has_insurance,
    ])

    user_input = (
        f"Assess purchase readiness for the {vehicle['year']} {vehicle['make']} "
        f"{vehicle['model']} {vehicle['trim']} (ID: {vehicle_id}) with a budget of "
        f"${budget:,.0f}"
    )

    data_context: dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "vehicle_summary": (
            f"{vehicle['year']} {vehicle['make']} {vehicle['model']} {vehicle['trim']}"
        ),
        "vehicle_price": vehicle["price"],
        "customer_budget": budget,
        "checklist": checklist,
        "ready_items": ready_count,
        "total_items": 3,
        "has_trade_in": has_trade_in,
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="assess_purchase_readiness",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )
