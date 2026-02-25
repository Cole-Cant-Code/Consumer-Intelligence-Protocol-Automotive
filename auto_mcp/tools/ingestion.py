"""Inventory ingestion tool implementations — pure CRUD, no CIP calls."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from auto_mcp.data.inventory import (
    get_store,
    record_vehicle_lead,
    remove_expired_vehicles,
)

_REQUIRED_FIELDS = ("id", "year", "make", "model", "body_type", "price", "fuel_type")
_REQUIRED_STRING_FIELDS = ("id", "make", "model", "body_type", "fuel_type")


def _validate_vehicle_schema(vehicle: dict[str, Any], *, index: int | None = None) -> str | None:
    target = f"vehicle at index {index}" if index is not None else "vehicle"

    missing = [field for field in _REQUIRED_FIELDS if field not in vehicle]
    if missing:
        missing_fields = ", ".join(missing)
        return f"Error: {target} is missing required field(s): {missing_fields}."

    for field in _REQUIRED_STRING_FIELDS:
        value = vehicle[field]
        if not isinstance(value, str) or not value.strip():
            return f"Error: {target} field '{field}' must be a non-empty string."

    year = vehicle["year"]
    if isinstance(year, bool) or not isinstance(year, int):
        return f"Error: {target} field 'year' must be an integer."
    current_year = datetime.now(timezone.utc).year
    if year < 1886 or year > current_year + 1:
        return f"Error: {target} field 'year' must be between 1886 and {current_year + 1}."

    price = vehicle["price"]
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return f"Error: {target} field 'price' must be a number."
    if price < 0:
        return f"Error: {target} field 'price' must be greater than or equal to 0."

    return None


def upsert_vehicle_impl(vehicle: Any) -> str:
    """Validate and upsert a single vehicle into the store."""
    if not isinstance(vehicle, dict):
        return "Error: vehicle payload must be a dict."
    schema_error = _validate_vehicle_schema(vehicle)
    if schema_error:
        return schema_error

    get_store().upsert(vehicle)
    return f"Vehicle {vehicle['id']} upserted successfully."


def bulk_upsert_vehicles_impl(vehicles: Any) -> str:
    """Validate and upsert a batch of vehicles into the store."""
    if not isinstance(vehicles, list):
        return "Error: vehicles payload must be a list of dicts."

    validated_vehicles: list[dict[str, Any]] = []
    for i, v in enumerate(vehicles):
        if not isinstance(v, dict):
            return f"Error: vehicle at index {i} must be a dict."
        schema_error = _validate_vehicle_schema(v, index=i)
        if schema_error:
            return schema_error
        validated_vehicles.append(v)

    get_store().upsert_many(validated_vehicles)
    return f"{len(validated_vehicles)} vehicle(s) upserted successfully."


def remove_vehicle_impl(vehicle_id: str) -> str:
    """Remove a vehicle by ID. Returns a status message."""
    removed = get_store().remove(vehicle_id)
    if removed:
        return f"Vehicle {vehicle_id} removed successfully."
    return f"Vehicle {vehicle_id} not found — nothing to remove."


# ── New tools: leads, TTL expiration, bulk import ───────────────────

_VALID_LEAD_ACTIONS = {
    "viewed",
    "compared",
    "financed",
    "availability_check",
    "test_drive",
    "reserve_vehicle",
    "contact_dealer",
    "purchase_deposit",
    "save_favorite",
    "get_similar_vehicles",
    "compare_financing_scenarios",
    "estimate_financing",
    "estimate_out_the_door_price",
    "sale_closed",
}


def record_lead_impl(
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
) -> str:
    """Record a user engagement lead for a vehicle."""
    if not vehicle_id or not vehicle_id.strip():
        return "Error: vehicle_id is required."
    if action not in _VALID_LEAD_ACTIONS:
        return (
            f"Error: invalid action '{action}'. "
            f"Must be one of: {', '.join(sorted(_VALID_LEAD_ACTIONS))}."
        )
    try:
        resolved_lead_id = record_vehicle_lead(
            vehicle_id.strip(),
            action,
            user_query,
            lead_id=lead_id,
            customer_id=customer_id,
            session_id=session_id,
            customer_name=customer_name,
            customer_contact=customer_contact,
            source_channel=source_channel,
        )
        return (
            f"Lead event recorded for vehicle {vehicle_id} "
            f"(action: {action}, lead_id: {resolved_lead_id})."
        )
    except ValueError as exc:
        return f"Error: {exc}"


def expire_stale_impl() -> str:
    """Remove vehicles past their TTL expiration."""
    count = remove_expired_vehicles()
    if count == 0:
        return "No expired listings found."
    return f"Removed {count} expired listing(s)."


async def bulk_import_impl(
    source: str = "auto_dev",
    zip_code: str = "78701",
    radius_miles: int = 50,
    make: str | None = None,
    model: str | None = None,
    dry_run: bool = False,
) -> str:
    """Import vehicles from an external API (Auto.dev)."""
    normalized_source = source.strip().lower()
    if normalized_source != "auto_dev":
        return (
            f"Error: unsupported source '{source}'. "
            "Currently supported sources: auto_dev."
        )

    api_key = os.environ.get("AUTO_DEV_API_KEY", "")
    if not api_key:
        return "Error: AUTO_DEV_API_KEY environment variable not set."

    from auto_mcp.ingestion.pipeline import IngestConfig, IngestionPipeline

    config = IngestConfig(
        source=normalized_source,
        metros=[],
        radius_miles=radius_miles,
        dry_run=dry_run,
        auto_dev_key=api_key,
    )
    pipeline = IngestionPipeline(config)
    stats = await pipeline.run_auto_dev(
        zip_codes=[zip_code],
        make=make,
        model=model,
        enrich_nhtsa_data=True,
    )

    errors: list[str] = stats.get("errors", [])
    if errors:
        preview = "; ".join(errors[:3])
        suffix = " ..." if len(errors) > 3 else ""
        return f"Import completed with {len(errors)} warning(s): {preview}{suffix}"

    if dry_run:
        return (
            f"DRY RUN: Would import {stats['deduped']} vehicles from {normalized_source} "
            f"(fetched {stats['total_fetched']}, normalized {stats['normalized']}, "
            f"NHTSA enriched {stats['nhtsa_enriched']})."
        )

    return (
        f"Imported {stats['upserted']} vehicles from {normalized_source} "
        f"(fetched {stats['total_fetched']}, normalized {stats['normalized']}, "
        f"deduped {stats['deduped']}, NHTSA enriched {stats['nhtsa_enriched']})."
    )
