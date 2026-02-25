"""Similar-vehicle recommendation tool implementation."""

from __future__ import annotations

from typing import Any

from cip_protocol import CIP

from auto_mcp.data.inventory import get_vehicle, search_vehicles
from auto_mcp.tools.orchestration import run_tool_with_orchestration


def _score_similarity(source: dict[str, Any], candidate: dict[str, Any]) -> float:
    score = 0.0

    if source["make"].lower() == candidate["make"].lower():
        score += 4.0
    if source["model"].lower() == candidate["model"].lower():
        score += 5.0
    if source["body_type"].lower() == candidate["body_type"].lower():
        score += 2.0
    if source["fuel_type"].lower() == candidate["fuel_type"].lower():
        score += 1.5

    year_diff = abs(source["year"] - candidate["year"])
    score += max(0.0, 2.0 - (0.5 * year_diff))

    source_price = max(float(source["price"]), 1.0)
    price_gap = abs(float(candidate["price"]) - source_price) / source_price
    score += max(0.0, 3.5 - (price_gap * 10.0))

    mileage_gap = abs(int(candidate["mileage"]) - int(source["mileage"]))
    score += max(0.0, 1.5 - (mileage_gap / 50_000))

    return round(score, 4)


async def get_similar_vehicles_impl(
    cip: CIP,
    *,
    vehicle_id: str,
    limit: int = 5,
    prefer_lower_price: bool = True,
    max_price: float | None = None,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Recommend vehicles similar to a target listing."""
    if limit <= 0:
        return "Please provide a positive limit."
    if limit > 20:
        return "Please use a limit of 20 or fewer recommendations per request."
    if max_price is not None and max_price < 0:
        return "Maximum price must be greater than or equal to 0."

    source_vehicle = get_vehicle(vehicle_id)
    if source_vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    candidate_pool = search_vehicles(body_type=source_vehicle["body_type"])
    if len(candidate_pool) < 3:
        candidate_pool = search_vehicles(fuel_type=source_vehicle["fuel_type"])

    resolved_price_cap = max_price
    if resolved_price_cap is None and prefer_lower_price:
        resolved_price_cap = float(source_vehicle["price"])

    filtered: list[dict[str, Any]] = []
    for candidate in candidate_pool:
        if candidate["id"] == vehicle_id:
            continue
        if resolved_price_cap is not None and float(candidate["price"]) > resolved_price_cap:
            continue
        filtered.append(candidate)

    if not filtered:
        for candidate in candidate_pool:
            if candidate["id"] != vehicle_id:
                filtered.append(candidate)

    scored = [
        {
            **candidate,
            "similarity_score": _score_similarity(source_vehicle, candidate),
            "price_delta": round(float(candidate["price"]) - float(source_vehicle["price"]), 2),
        }
        for candidate in filtered
    ]
    scored.sort(key=lambda v: (-v["similarity_score"], float(v["price"]), v["id"]))
    top = scored[:limit]

    if not top:
        return "I could not find similar vehicles right now. Please try broadening your criteria."

    user_input = (
        f"Recommend vehicles similar to {source_vehicle['year']} {source_vehicle['make']} "
        f"{source_vehicle['model']} (ID: {vehicle_id})."
    )

    data_context: dict[str, Any] = {
        "source_vehicle": {
            "id": source_vehicle["id"],
            "year": source_vehicle["year"],
            "make": source_vehicle["make"],
            "model": source_vehicle["model"],
            "trim": source_vehicle["trim"],
            "price": source_vehicle["price"],
            "mileage": source_vehicle["mileage"],
            "body_type": source_vehicle["body_type"],
            "fuel_type": source_vehicle["fuel_type"],
        },
        "prefer_lower_price": prefer_lower_price,
        "max_price": resolved_price_cap,
        "recommendations": [
            {
                "id": vehicle["id"],
                "year": vehicle["year"],
                "make": vehicle["make"],
                "model": vehicle["model"],
                "trim": vehicle["trim"],
                "price": vehicle["price"],
                "mileage": vehicle["mileage"],
                "body_type": vehicle["body_type"],
                "fuel_type": vehicle["fuel_type"],
                "dealer_name": vehicle["dealer_name"],
                "dealer_location": vehicle["dealer_location"],
                "availability_status": vehicle["availability_status"],
                "similarity_score": vehicle["similarity_score"],
                "price_delta": vehicle["price_delta"],
            }
            for vehicle in top
        ],
        "recommendation_count": len(top),
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="get_similar_vehicles",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )
