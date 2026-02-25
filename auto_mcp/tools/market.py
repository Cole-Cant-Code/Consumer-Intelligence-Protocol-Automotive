"""Market pricing context tool implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any

from cip_protocol import CIP

from auto_mcp.data.inventory import get_vehicle, search_vehicles


def _estimate_days_on_lot(vehicle: dict[str, Any]) -> int:
    ingested_at = str(vehicle.get("ingested_at", "") or "")
    if ingested_at:
        try:
            stamped = datetime.fromisoformat(ingested_at)
            age_days = (datetime.now(timezone.utc) - stamped).days
            if age_days >= 0:
                return age_days
        except ValueError:
            pass

    stable = sum(ord(ch) for ch in vehicle["id"])
    return 7 + (stable % 60)


def _deal_grade(price_delta_pct: float) -> str:
    if price_delta_pct <= -0.08:
        return "excellent"
    if price_delta_pct <= -0.03:
        return "good"
    if price_delta_pct < 0.03:
        return "fair"
    if price_delta_pct < 0.08:
        return "above_market"
    return "high"


async def get_market_price_context_impl(cip: CIP, *, vehicle_id: str) -> str:
    """Assess if a listing is priced below, near, or above peer market pricing."""
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    peers = [
        v
        for v in search_vehicles(make=vehicle["make"], model=vehicle["model"])
        if v["id"] != vehicle_id
    ]
    if len(peers) < 3:
        peers = [
            v
            for v in search_vehicles(
                body_type=vehicle["body_type"],
                fuel_type=vehicle["fuel_type"],
            )
            if v["id"] != vehicle_id
        ]

    if not peers:
        return "I could not find enough peer listings to compute market context yet."

    peer_prices = [float(v["price"]) for v in peers]
    market_median = float(median(peer_prices))
    market_avg = float(sum(peer_prices) / len(peer_prices))
    delta = float(vehicle["price"]) - market_median
    delta_pct = delta / market_median if market_median else 0.0

    market_rank = sum(1 for price in peer_prices if price <= float(vehicle["price"]))
    percentile = round((market_rank / len(peer_prices)) * 100, 1)

    days_on_lot = _estimate_days_on_lot(vehicle)
    grade = _deal_grade(delta_pct)

    user_input = (
        f"Evaluate market pricing context for {vehicle['year']} {vehicle['make']} "
        f"{vehicle['model']} (ID: {vehicle_id})"
    )

    data_context: dict[str, Any] = {
        "vehicle": {
            "id": vehicle["id"],
            "year": vehicle["year"],
            "make": vehicle["make"],
            "model": vehicle["model"],
            "trim": vehicle["trim"],
            "price": vehicle["price"],
            "mileage": vehicle["mileage"],
        },
        "market_sample": {
            "peer_count": len(peers),
            "median_price": round(market_median, 2),
            "average_price": round(market_avg, 2),
            "min_price": round(min(peer_prices), 2),
            "max_price": round(max(peer_prices), 2),
        },
        "price_position": {
            "price_delta": round(delta, 2),
            "price_delta_percent": round(delta_pct * 100, 2),
            "price_percentile": percentile,
            "deal_grade": grade,
            "estimated_days_on_lot": days_on_lot,
        },
    }

    result = await cip.run(
        user_input,
        tool_name="get_market_price_context",
        data_context=data_context,
    )
    return result.response.content
