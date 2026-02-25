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


def record_vehicle_lead(
    vehicle_id: str,
    action: str,
    user_query: str = "",
    *,
    lead_id: str = "",
    customer_id: str = "",
    session_id: str = "",
    customer_name: str = "",
    customer_contact: str = "",
    source_channel: str = "direct",
    event_meta: dict[str, Any] | None = None,
) -> str:
    """Record a user engagement lead. Returns lead profile id."""
    return get_store().record_lead(
        vehicle_id,
        action,
        user_query,
        lead_id=lead_id,
        customer_id=customer_id,
        session_id=session_id,
        customer_name=customer_name,
        customer_contact=customer_contact,
        source_channel=source_channel,
        event_meta=event_meta,
    )


def get_lead_analytics(days: int = 30) -> dict[str, Any]:
    """Get lead analytics for reporting."""
    return get_store().get_lead_analytics(days)


def get_hot_leads(
    *,
    limit: int = 10,
    min_score: float = 10.0,
    dealer_zip: str = "",
    days: int = 30,
) -> list[dict[str, Any]]:
    """Get highest-intent lead profiles ranked by score."""
    return get_store().get_hot_leads(
        limit=limit,
        min_score=min_score,
        dealer_zip=dealer_zip,
        days=days,
    )


def get_lead_detail(lead_id: str, *, days: int = 90) -> dict[str, Any] | None:
    """Get detail for one lead profile."""
    return get_store().get_lead_detail(lead_id, days=days)


def get_inventory_aging_report(
    *,
    min_days_on_lot: int = 30,
    limit: int = 100,
    dealer_zip: str = "",
) -> dict[str, Any]:
    """Get inventory aging metrics and unit-level report."""
    return get_store().get_inventory_aging_report(
        min_days_on_lot=min_days_on_lot,
        limit=limit,
        dealer_zip=dealer_zip,
    )


def get_pricing_opportunities(
    *,
    limit: int = 25,
    stale_days_threshold: int = 45,
    overpriced_threshold_pct: float = 5.0,
    underpriced_threshold_pct: float = -5.0,
) -> dict[str, Any]:
    """Get pricing opportunities based on market context and aging."""
    return get_store().get_pricing_opportunities(
        limit=limit,
        stale_days_threshold=stale_days_threshold,
        overpriced_threshold_pct=overpriced_threshold_pct,
        underpriced_threshold_pct=underpriced_threshold_pct,
    )


def record_vehicle_sale(
    *,
    vehicle_id: str,
    sold_price: float,
    sold_at: str,
    lead_id: str = "",
    source_channel: str = "direct",
    salesperson_id: str = "",
    keep_vehicle_record: bool = True,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a completed sale and link it to an optional lead."""
    return get_store().record_sale(
        vehicle_id=vehicle_id,
        sold_price=sold_price,
        sold_at=sold_at,
        lead_id=lead_id,
        source_channel=source_channel,
        salesperson_id=salesperson_id,
        keep_vehicle_record=keep_vehicle_record,
        metadata=metadata,
    )


def get_funnel_metrics(
    *,
    days: int = 30,
    dealer_zip: str = "",
    breakdown_by: str = "none",
) -> dict[str, Any]:
    """Get closed-loop conversion funnel metrics."""
    return get_store().get_funnel_metrics(
        days=days,
        dealer_zip=dealer_zip,
        breakdown_by=breakdown_by,
    )
