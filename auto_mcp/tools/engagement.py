"""Customer engagement tools across discovery, conversion, and post-purchase."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from auto_mcp.data.inventory import get_vehicle, get_vehicles
from auto_mcp.data.journey import (
    contact_dealer,
    list_favorites,
    list_saved_searches,
    request_follow_up,
    reserve_vehicle,
    save_favorite,
    save_search,
    schedule_service,
    submit_purchase_deposit,
)


def _render_filters(filters: dict[str, Any]) -> str:
    if not filters:
        return "all vehicles"
    return ", ".join(f"{key}: {value}" for key, value in filters.items())


def save_search_impl(
    *,
    search_name: str,
    customer_id: str = "guest",
    make: str | None = None,
    model: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    body_type: str | None = None,
    fuel_type: str | None = None,
) -> str:
    """Save a named inventory search for a customer."""
    name = search_name.strip()
    if not name:
        return "Please provide a search name."

    filters: dict[str, Any] = {}
    if make:
        filters["make"] = make
    if model:
        filters["model"] = model
    if year_min is not None:
        filters["year_min"] = year_min
    if year_max is not None:
        filters["year_max"] = year_max
    if price_min is not None:
        filters["price_min"] = price_min
    if price_max is not None:
        filters["price_max"] = price_max
    if body_type:
        filters["body_type"] = body_type
    if fuel_type:
        filters["fuel_type"] = fuel_type

    if not filters:
        return "Please include at least one filter before saving a search."

    record = save_search(customer_id=customer_id, search_name=name, filters=filters)
    return (
        f"Saved search '{name}' ({record['id']}) for customer '{record['customer_id']}' "
        f"with filters: {_render_filters(filters)}."
    )


def list_saved_searches_impl(*, customer_id: str = "guest") -> str:
    """List saved searches for a customer."""
    records = list_saved_searches(customer_id)
    if not records:
        return f"No saved searches found for customer '{customer_id or 'guest'}'."

    lines = [f"Saved searches for '{records[0]['customer_id']}':"]
    for item in records:
        lines.append(
            f"- {item['search_name']} ({item['id']}): {_render_filters(item['filters'])}"
        )
    return "\n".join(lines)


def save_favorite_impl(
    *,
    vehicle_id: str,
    customer_id: str = "guest",
    note: str = "",
) -> str:
    """Save a vehicle as a customer favorite."""
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    record = save_favorite(customer_id=customer_id, vehicle_id=vehicle_id, note=note)
    return (
        f"Saved {vehicle['year']} {vehicle['make']} {vehicle['model']} ({vehicle_id}) "
        f"as favorite '{record['id']}' for customer '{record['customer_id']}'."
    )


def list_favorites_impl(*, customer_id: str = "guest") -> str:
    """List favorite vehicles for a customer."""
    favorites = list_favorites(customer_id)
    if not favorites:
        return f"No favorites found for customer '{customer_id or 'guest'}'."

    vehicle_ids = [item["vehicle_id"] for item in favorites]
    vehicles_list = get_vehicles(vehicle_ids)
    vehicles_by_id = {v["id"]: v for v in vehicles_list}

    lines = [f"Favorites for '{favorites[0]['customer_id']}':"]
    for item in favorites:
        vehicle = vehicles_by_id.get(item["vehicle_id"])
        if vehicle is None:
            lines.append(f"- {item['vehicle_id']} (listing no longer in inventory)")
            continue
        lines.append(
            f"- {vehicle['id']}: {vehicle['year']} {vehicle['make']} {vehicle['model']} "
            f"{vehicle['trim']} at ${vehicle['price']:,.0f}"
        )
    return "\n".join(lines)


def reserve_vehicle_impl(
    *,
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    hold_hours: int = 48,
    notes: str = "",
) -> str:
    """Create a soft reservation hold for a vehicle."""
    if hold_hours <= 0:
        return "Hold hours must be greater than 0."
    if hold_hours > 168:
        return "Hold hours must be 168 or fewer (7 days max)."

    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."
    if vehicle["availability_status"] not in {"in_stock", "in_transit"}:
        return (
            f"Vehicle {vehicle_id} is currently marked '{vehicle['availability_status']}' "
            "and cannot be held online."
        )

    record = reserve_vehicle(
        vehicle_id=vehicle_id,
        customer_name=customer_name,
        customer_contact=customer_contact,
        hold_hours=hold_hours,
        notes=notes,
    )

    if record["status"] == "already_reserved":
        return (
            f"Vehicle {vehicle_id} already has an active hold until {record['hold_until']}. "
            "Please contact the dealer for availability."
        )

    return (
        f"Reservation hold created ({record['id']}) for vehicle {vehicle_id} until "
        f"{record['hold_until']}."
    )


def contact_dealer_impl(
    *,
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    question: str,
    preferred_channel: str = "sms",
) -> str:
    """Send a low-commitment dealer question about a vehicle."""
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    cleaned_question = question.strip()
    if not cleaned_question:
        return "Please provide a question for the dealer."

    channel = preferred_channel.strip().lower() or "sms"
    if channel not in {"sms", "phone", "email"}:
        return "Preferred channel must be one of: sms, phone, email."

    record = contact_dealer(
        vehicle_id=vehicle_id,
        customer_name=customer_name,
        customer_contact=customer_contact,
        message=cleaned_question,
        preferred_channel=channel,
    )

    dealer_name = vehicle['dealer_name'] or 'the dealer'
    return (
        f"Message {record['id']} sent to {dealer_name} regarding vehicle {vehicle_id}. "
        f"Preferred reply channel: {channel}."
    )


_VALID_FINANCING_INTENTS = {"undecided", "cash", "finance", "lease"}


def submit_purchase_deposit_impl(
    *,
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    deposit_amount: float,
    financing_intent: str = "undecided",
    paperwork_started: bool = False,
) -> str:
    """Submit a deposit and start digital paperwork intake."""
    if deposit_amount <= 0:
        return "Deposit amount must be greater than 0."

    normalized_intent = financing_intent.strip().lower() if financing_intent else "undecided"
    if normalized_intent not in _VALID_FINANCING_INTENTS:
        return (
            f"Invalid financing intent '{financing_intent}'. "
            f"Must be one of: {', '.join(sorted(_VALID_FINANCING_INTENTS))}."
        )

    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    record = submit_purchase_deposit(
        vehicle_id=vehicle_id,
        customer_name=customer_name,
        customer_contact=customer_contact,
        deposit_amount=deposit_amount,
        financing_intent=normalized_intent,
        paperwork_started=paperwork_started,
    )

    return (
        f"Deposit intake submitted ({record['id']}) for vehicle {vehicle_id}. "
        f"Amount: ${record['deposit_amount']:,.2f}. "
        f"Paperwork status: {record['paperwork_status']}."
    )


def schedule_service_impl(
    *,
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    preferred_date: str,
    service_type: str = "maintenance",
    notes: str = "",
) -> str:
    """Schedule a post-purchase service request."""
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    if not preferred_date.strip():
        return "Please provide a preferred service date."

    try:
        datetime.fromisoformat(preferred_date)
    except ValueError:
        return "Preferred date must be in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)."

    record = schedule_service(
        vehicle_id=vehicle_id,
        customer_name=customer_name,
        customer_contact=customer_contact,
        preferred_date=preferred_date,
        service_type=service_type,
        notes=notes,
    )

    return (
        f"Service request {record['id']} submitted for vehicle {vehicle_id} on {preferred_date} "
        f"({service_type})."
    )


def request_follow_up_impl(
    *,
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    topic: str = "ownership check-in",
    preferred_channel: str = "email",
) -> str:
    """Request a post-purchase follow-up from the dealership."""
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    channel = preferred_channel.strip().lower() or "email"
    if channel not in {"sms", "phone", "email"}:
        return "Preferred channel must be one of: sms, phone, email."

    cleaned_topic = topic.strip() or "ownership check-in"
    record = request_follow_up(
        vehicle_id=vehicle_id,
        customer_name=customer_name,
        customer_contact=customer_contact,
        topic=cleaned_topic,
        preferred_channel=channel,
    )

    dealer_name = vehicle['dealer_name'] or 'the dealer'
    return (
        f"Follow-up request {record['id']} queued with {dealer_name} "
        f"for topic '{cleaned_topic}' via {channel}."
    )
