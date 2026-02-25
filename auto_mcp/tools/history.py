"""Vehicle history tool implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cip_protocol import CIP

from auto_mcp.data.inventory import get_vehicle


def _seed(text: str) -> int:
    return sum((idx + 1) * ord(ch) for idx, ch in enumerate(text))


def _build_history(vehicle: dict[str, Any]) -> dict[str, Any]:
    current_year = datetime.now(timezone.utc).year
    age_years = max(0, current_year - int(vehicle["year"]))
    base = _seed(vehicle["vin"])

    owner_count = min(4, 1 + (base % 4))
    accident_roll = base % 8
    accident_count = 0 if accident_roll < 5 else 1 if accident_roll < 7 else 2

    if accident_count == 0:
        title_status = "clean"
    elif accident_count == 1 and (base % 3 != 0):
        title_status = "clean"
    elif accident_count == 1:
        title_status = "rebuilt"
    else:
        title_status = "salvage"

    service_records = max(2, age_years * 2 + (base % 5))

    open_recalls = []
    if (base % 6) == 0:
        open_recalls.append("OEM recall campaign pending dealer service")

    odometer_flag = "consistent"
    if age_years > 7 and int(vehicle["mileage"]) < 25_000:
        odometer_flag = "review_recommended"

    return {
        "report_source": "AutoCIP synthetic preview (demo only)",
        "report_generated_at": datetime.now(timezone.utc).date().isoformat(),
        "title_status": title_status,
        "owner_count": owner_count,
        "accident_count": accident_count,
        "service_records_reported": service_records,
        "open_recalls": open_recalls,
        "odometer_consistency": odometer_flag,
    }


async def get_vehicle_history_impl(cip: CIP, *, vehicle_id: str) -> str:
    """Return a Carfax-style synthetic vehicle history summary."""
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    history = _build_history(vehicle)

    user_input = (
        f"Summarize history for {vehicle['year']} {vehicle['make']} {vehicle['model']} "
        f"(ID: {vehicle_id})"
    )

    data_context: dict[str, Any] = {
        "vehicle": {
            "id": vehicle["id"],
            "vin": vehicle["vin"],
            "year": vehicle["year"],
            "make": vehicle["make"],
            "model": vehicle["model"],
            "trim": vehicle["trim"],
            "mileage": vehicle["mileage"],
            "dealer_name": vehicle["dealer_name"],
            "dealer_location": vehicle["dealer_location"],
        },
        "history": history,
        "history_disclaimer": (
            "Demo synthetic history only. For a purchase decision, obtain an official "
            "third-party history report."
        ),
    }

    result = await cip.run(
        user_input,
        tool_name="get_vehicle_history",
        data_context=data_context,
    )
    return result.response.content
