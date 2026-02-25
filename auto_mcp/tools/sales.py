"""Dealer sales/outcome recording tool implementation."""

from __future__ import annotations

from datetime import datetime

from auto_mcp.data.inventory import record_vehicle_sale


def record_sale_impl(
    *,
    vehicle_id: str,
    sold_price: float,
    sold_at: str,
    lead_id: str = "",
    source_channel: str = "direct",
    salesperson_id: str = "",
    keep_vehicle_record: bool = True,
) -> str:
    """Record a sale outcome and link it to inventory + lead lifecycle."""
    if not vehicle_id.strip():
        return "Error: vehicle_id is required."
    if sold_price < 0:
        return "Error: sold_price must be greater than or equal to 0."

    try:
        datetime.fromisoformat(sold_at)
    except ValueError:
        return "Error: sold_at must be a valid ISO datetime string."

    try:
        result = record_vehicle_sale(
            vehicle_id=vehicle_id.strip(),
            sold_price=sold_price,
            sold_at=sold_at,
            lead_id=lead_id.strip(),
            source_channel=source_channel,
            salesperson_id=salesperson_id,
            keep_vehicle_record=keep_vehicle_record,
        )
        return (
            f"Sale {result['sale_id']} recorded for vehicle {result['vehicle_id']} at "
            f"${result['sold_price']:,.2f}."
        )
    except ValueError as exc:
        return f"Error: {exc}"
