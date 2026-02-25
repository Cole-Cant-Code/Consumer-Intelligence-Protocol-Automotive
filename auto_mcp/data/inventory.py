"""Vehicle inventory facade — delegates to a VehicleStore backend.

All existing tool modules import ``get_vehicle`` and ``search_vehicles`` from
this module, so the public API is kept **exactly the same**.  Under the hood
the data now lives in SQLite (via :class:`SqliteVehicleStore`) instead of a
hardcoded list.
"""

from __future__ import annotations

import os
from typing import Any

from auto_mcp.data.store import SqliteVehicleStore, VehicleStore, ZipCodeDatabase

_store: VehicleStore | None = None
_zip_db: ZipCodeDatabase | None = None

_DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "inventory.db")


def get_store() -> VehicleStore:
    """Return the active VehicleStore singleton, creating + seeding if needed."""
    global _store  # noqa: PLW0603
    if _store is None:
        db_path = os.environ.get("AUTOCIP_DB_PATH", _DEFAULT_DB_PATH)
        store = SqliteVehicleStore(db_path)
        if store.count() == 0:
            from auto_mcp.data.seed import seed_demo_data
            seed_demo_data(store)
        _store = store
    return _store


def set_store(store: VehicleStore | None) -> None:
    """Inject a store instance for testing (mirrors ``set_cip_override``)."""
    global _store  # noqa: PLW0603
    _store = store


def get_zip_database() -> ZipCodeDatabase:
    """Return the ZipCodeDatabase singleton."""
    global _zip_db  # noqa: PLW0603
    if _zip_db is None:
        _zip_db = ZipCodeDatabase()
    return _zip_db


# ── Public helpers (unchanged signatures) ──────────────────────────


def get_vehicle(vehicle_id: str) -> dict[str, Any] | None:
    """Look up a single vehicle by ID. Returns None if not found."""
    return get_store().get(vehicle_id)


def get_vehicle_by_vin(vin: str) -> dict[str, Any] | None:
    """Look up a single vehicle by VIN. Returns None if not found."""
    return get_store().get_by_vin(vin)


def search_vehicles(
    *,
    make: str | None = None,
    model: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    body_type: str | None = None,
    fuel_type: str | None = None,
) -> list[dict[str, Any]]:
    """Filter vehicles by the given criteria. All filters are optional and ANDed together."""
    return get_store().search(
        make=make,
        model=model,
        year_min=year_min,
        year_max=year_max,
        price_min=price_min,
        price_max=price_max,
        body_type=body_type,
        fuel_type=fuel_type,
    )


def search_vehicles_windowed(
    *,
    make: str | None = None,
    model: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    body_type: str | None = None,
    fuel_type: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """Return total matches plus a small page of vehicles for high-volume search paths."""
    store = get_store()
    if isinstance(store, SqliteVehicleStore):
        total = store.count_filtered(
            make=make,
            model=model,
            year_min=year_min,
            year_max=year_max,
            price_min=price_min,
            price_max=price_max,
            body_type=body_type,
            fuel_type=fuel_type,
        )
        page = store.search_page(
            make=make,
            model=model,
            year_min=year_min,
            year_max=year_max,
            price_min=price_min,
            price_max=price_max,
            body_type=body_type,
            fuel_type=fuel_type,
            limit=limit,
            offset=offset,
        )
        return total, page

    matches = store.search(
        make=make,
        model=model,
        year_min=year_min,
        year_max=year_max,
        price_min=price_min,
        price_max=price_max,
        body_type=body_type,
        fuel_type=fuel_type,
    )
    return len(matches), matches[offset:offset + max(limit, 0)]


def search_vehicles_by_location(**kwargs: Any) -> list[dict[str, Any]]:
    """Geo search — delegates to store.search_by_location()."""
    return get_store().search_by_location(**kwargs)


def remove_expired_vehicles() -> int:
    """Remove vehicles past their TTL. Returns count removed."""
    return get_store().remove_expired()


def get_inventory_stats() -> dict[str, Any]:
    """Get comprehensive inventory analytics."""
    return get_store().get_stats()


def record_vehicle_lead(vehicle_id: str, action: str, user_query: str = "") -> str:
    """Record a user engagement lead. Returns lead_id."""
    return get_store().record_lead(vehicle_id, action, user_query)


def get_lead_analytics(days: int = 30) -> dict[str, Any]:
    """Get lead analytics for reporting."""
    return get_store().get_lead_analytics(days)
