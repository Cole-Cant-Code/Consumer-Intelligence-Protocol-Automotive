"""In-memory customer journey state for non-inventory funnel actions."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

_lock = threading.RLock()

_saved_searches: dict[str, list[dict[str, Any]]] = {}
_favorites: dict[str, list[dict[str, Any]]] = {}
_reservations: list[dict[str, Any]] = []
_dealer_messages: list[dict[str, Any]] = []
_purchase_deposits: list[dict[str, Any]] = []
_service_requests: list[dict[str, Any]] = []
_follow_ups: list[dict[str, Any]] = []

_MAX_LIST_SIZE = 10_000
_MAX_TTL_DAYS = 90


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _as_customer(customer_id: str) -> str:
    value = customer_id.strip()
    return value or "guest"


def _prune_list(items: list[dict[str, Any]]) -> None:
    """Remove entries older than _MAX_TTL_DAYS and cap at _MAX_LIST_SIZE."""
    cutoff = (_now() - timedelta(days=_MAX_TTL_DAYS)).isoformat()
    items[:] = [r for r in items if r.get("created_at", "") >= cutoff]
    if len(items) > _MAX_LIST_SIZE:
        items[:] = items[-_MAX_LIST_SIZE:]


def reset_customer_journey() -> None:
    """Clear all customer journey records. Intended for tests."""
    with _lock:
        _saved_searches.clear()
        _favorites.clear()
        _reservations.clear()
        _dealer_messages.clear()
        _purchase_deposits.clear()
        _service_requests.clear()
        _follow_ups.clear()


def save_search(
    *,
    customer_id: str,
    search_name: str,
    filters: dict[str, Any],
) -> dict[str, Any]:
    """Persist a saved search for a customer."""
    normalized_customer = _as_customer(customer_id)
    now_iso = _now_iso()

    record = {
        "id": f"search-{uuid.uuid4().hex[:10]}",
        "customer_id": normalized_customer,
        "search_name": search_name,
        "filters": filters,
        "created_at": now_iso,
        "last_used_at": now_iso,
    }

    with _lock:
        searches = _saved_searches.setdefault(normalized_customer, [])
        for existing in searches:
            if existing["search_name"] == search_name:
                existing["filters"] = filters
                existing["last_used_at"] = now_iso
                return existing
        searches.append(record)

    return record


def list_saved_searches(customer_id: str) -> list[dict[str, Any]]:
    """Return saved searches for a customer."""
    normalized_customer = _as_customer(customer_id)
    with _lock:
        items = list(_saved_searches.get(normalized_customer, []))
    return sorted(items, key=lambda item: item["created_at"], reverse=True)


def save_favorite(
    *,
    customer_id: str,
    vehicle_id: str,
    note: str = "",
) -> dict[str, Any]:
    """Save or update a favorite vehicle for a customer."""
    normalized_customer = _as_customer(customer_id)
    now_iso = _now_iso()

    with _lock:
        favorites = _favorites.setdefault(normalized_customer, [])
        for existing in favorites:
            if existing["vehicle_id"] == vehicle_id:
                if note:
                    existing["note"] = note
                existing["updated_at"] = now_iso
                return existing

        record = {
            "id": f"fav-{uuid.uuid4().hex[:10]}",
            "customer_id": normalized_customer,
            "vehicle_id": vehicle_id,
            "note": note,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        favorites.append(record)
        return record


def list_favorites(customer_id: str) -> list[dict[str, Any]]:
    """Return a customer's favorite vehicles."""
    normalized_customer = _as_customer(customer_id)
    with _lock:
        items = list(_favorites.get(normalized_customer, []))
    return sorted(items, key=lambda item: item["created_at"], reverse=True)


def reserve_vehicle(
    *,
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    hold_hours: int,
    notes: str = "",
) -> dict[str, Any]:
    """Create a soft hold reservation for a vehicle if no active hold exists."""
    now = _now()
    now_iso = now.isoformat()

    with _lock:
        _prune_list(_reservations)
        for existing in _reservations:
            if existing["vehicle_id"] != vehicle_id:
                continue
            if existing["status"] != "active":
                continue
            hold_until = datetime.fromisoformat(existing["hold_until"])
            if hold_until > now:
                return {
                    **existing,
                    "status": "already_reserved",
                }

        hold_until = now + timedelta(hours=hold_hours)
        record = {
            "id": f"hold-{uuid.uuid4().hex[:10]}",
            "vehicle_id": vehicle_id,
            "customer_name": customer_name,
            "customer_contact": customer_contact,
            "hold_until": hold_until.isoformat(),
            "notes": notes,
            "status": "active",
            "created_at": now_iso,
        }
        _reservations.append(record)
        return record


def contact_dealer(
    *,
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    message: str,
    preferred_channel: str,
) -> dict[str, Any]:
    """Create a dealer contact request."""
    record = {
        "id": f"msg-{uuid.uuid4().hex[:10]}",
        "vehicle_id": vehicle_id,
        "customer_name": customer_name,
        "customer_contact": customer_contact,
        "message": message,
        "preferred_channel": preferred_channel,
        "status": "new",
        "created_at": _now_iso(),
    }

    with _lock:
        _prune_list(_dealer_messages)
        _dealer_messages.append(record)

    return record


def submit_purchase_deposit(
    *,
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    deposit_amount: float,
    financing_intent: str,
    paperwork_started: bool,
) -> dict[str, Any]:
    """Create a deposit + paperwork intake record."""
    record = {
        "id": f"deal-{uuid.uuid4().hex[:10]}",
        "vehicle_id": vehicle_id,
        "customer_name": customer_name,
        "customer_contact": customer_contact,
        "deposit_amount": round(deposit_amount, 2),
        "financing_intent": financing_intent,
        "paperwork_started": paperwork_started,
        "paperwork_status": "in_progress" if paperwork_started else "not_started",
        "status": "submitted",
        "created_at": _now_iso(),
    }

    with _lock:
        _prune_list(_purchase_deposits)
        _purchase_deposits.append(record)

    return record


def schedule_service(
    *,
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    preferred_date: str,
    service_type: str,
    notes: str,
) -> dict[str, Any]:
    """Create a post-purchase service request."""
    record = {
        "id": f"svc-{uuid.uuid4().hex[:10]}",
        "vehicle_id": vehicle_id,
        "customer_name": customer_name,
        "customer_contact": customer_contact,
        "preferred_date": preferred_date,
        "service_type": service_type,
        "notes": notes,
        "status": "requested",
        "created_at": _now_iso(),
    }

    with _lock:
        _prune_list(_service_requests)
        _service_requests.append(record)

    return record


def request_follow_up(
    *,
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    topic: str,
    preferred_channel: str,
) -> dict[str, Any]:
    """Create a post-purchase follow-up request."""
    record = {
        "id": f"follow-{uuid.uuid4().hex[:10]}",
        "vehicle_id": vehicle_id,
        "customer_name": customer_name,
        "customer_contact": customer_contact,
        "topic": topic,
        "preferred_channel": preferred_channel,
        "status": "queued",
        "created_at": _now_iso(),
    }

    with _lock:
        _prune_list(_follow_ups)
        _follow_ups.append(record)

    return record
