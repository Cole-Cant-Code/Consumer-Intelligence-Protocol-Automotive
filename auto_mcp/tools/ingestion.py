"""Inventory ingestion tool implementations — pure CRUD, no CIP calls."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from urllib import error, parse, request

from auto_mcp.data.inventory import (
    get_store,
    record_vehicle_lead,
    remove_expired_vehicles,
)

_REQUIRED_FIELDS = ("id", "year", "make", "model", "body_type", "price", "fuel_type")
_REQUIRED_STRING_FIELDS = ("id", "make", "model", "body_type", "fuel_type")

_CANONICAL_ALIASES = {
    "vehicle_id": "id",
    "stock_id": "id",
    "model_year": "year",
    "bodyStyle": "body_type",
    "body_class": "body_type",
    "type": "body_type",
    "fuelType": "fuel_type",
    "fuel": "fuel_type",
    "msrp": "price",
    "asking_price": "price",
    "list_price": "price",
    "internet_price": "price",
    "odometer": "mileage",
    "miles": "mileage",
    "displayColor": "exterior_color",
    "exteriorColor": "exterior_color",
    "interiorColor": "interior_color",
    "dealerZip": "dealer_zip",
    "zip": "dealer_zip",
    "postal_code": "dealer_zip",
    "sourceUrl": "source_url",
    "url": "source_url",
}

_BODY_TYPE_MAP = {
    "sedan": "sedan",
    "coupe": "coupe",
    "hatchback": "hatchback",
    "suv": "suv",
    "crossover": "suv",
    "truck": "truck",
    "pickup": "truck",
    "van": "van",
    "minivan": "minivan",
    "wagon": "wagon",
    "convertible": "convertible",
}

_FUEL_TYPE_MAP = {
    "gasoline": "gasoline",
    "diesel": "diesel",
    "electric": "electric",
    "hybrid": "hybrid",
    "plug-in hybrid": "hybrid",
    "flex fuel": "gasoline",
}

_VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_VIN_YEAR_CODES = "ABCDEFGHJKLMNPRSTVWXY123456789"

_WMI_TO_MAKE = {
    "1HG": "Honda",
    "1FT": "Ford",
    "1FA": "Ford",
    "1C4": "Chrysler",
    "1G1": "Chevrolet",
    "1G6": "Cadillac",
    "2HG": "Honda",
    "2T3": "Toyota",
    "3FA": "Ford",
    "3GN": "Chevrolet",
    "5YJ": "Tesla",
    "JN1": "Nissan",
    "JTD": "Toyota",
    "KM8": "Hyundai",
    "SAL": "Land Rover",
    "SCB": "Bentley",
    "WAU": "Audi",
    "WBA": "BMW",
    "WDC": "Mercedes-Benz",
}


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _clean_numeric_string(raw: str) -> str:
    return "".join(c for c in raw if c.isdigit() or c in {".", "-"})


def _parse_price(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        cleaned = _clean_numeric_string(stripped)
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _parse_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        parsed = _parse_price(stripped)
        if parsed is None:
            return None
        return int(parsed)
    return None


def _parse_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _normalize_body_type(raw: str | None) -> str:
    if not raw:
        return ""
    normalized = raw.strip().lower()
    return _BODY_TYPE_MAP.get(normalized, normalized)


def _normalize_fuel_type(raw: str | None) -> str:
    if not raw:
        return ""
    normalized = raw.strip().lower()
    return _FUEL_TYPE_MAP.get(normalized, normalized)


def _decode_model_year_from_vin(vin: str) -> int | None:
    if len(vin) != 17:
        return None
    code = vin[9]
    idx = _VIN_YEAR_CODES.find(code)
    if idx == -1:
        return None
    base_year = 1980 + idx
    current_plus_one = datetime.now(timezone.utc).year + 1
    resolved = base_year
    while resolved + 30 <= current_plus_one:
        resolved += 30
    if resolved < 1886 or resolved > current_plus_one:
        return None
    return resolved


def _decode_make_from_wmi(vin: str) -> str:
    if len(vin) < 3:
        return ""
    return _WMI_TO_MAKE.get(vin[:3], "")


@lru_cache(maxsize=1024)
def _decode_vin_nhtsa(vin: str) -> dict[str, Any]:
    """Decode VIN via NHTSA vPIC and map to AutoCIP canonical fields."""
    url = (
        "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVINValuesExtended/"
        f"{parse.quote(vin)}?format=json"
    )
    req = request.Request(url, headers={"User-Agent": "AutoCIP/1.0"})

    try:
        with request.urlopen(req, timeout=4) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except (error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return {}

    results = payload.get("Results")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return {}
    raw = results[0]

    decoded: dict[str, Any] = {}
    make = str(raw.get("Make", "")).strip().title()
    model = str(raw.get("Model", "")).strip().title()
    trim = str(raw.get("Trim", "")).strip()
    transmission = str(raw.get("TransmissionStyle", "")).strip()
    drivetrain = str(raw.get("DriveType", "")).strip()

    if make:
        decoded["make"] = make
    if model:
        decoded["model"] = model
    if trim:
        decoded["trim"] = trim
    if transmission:
        decoded["transmission"] = transmission
    if drivetrain:
        decoded["drivetrain"] = drivetrain

    model_year = _parse_int(raw.get("ModelYear"))
    if model_year is not None:
        decoded["year"] = model_year

    body_type = _normalize_body_type(str(raw.get("BodyClass", "")).strip())
    if body_type:
        decoded["body_type"] = body_type

    fuel_type = _normalize_fuel_type(str(raw.get("FuelTypePrimary", "")).strip())
    if fuel_type:
        decoded["fuel_type"] = fuel_type

    displacement = str(raw.get("DisplacementL", "")).strip()
    engine_model = str(raw.get("EngineModel", "")).strip()
    engine_configuration = str(raw.get("EngineConfiguration", "")).strip()
    engine_parts = [part for part in (displacement, engine_model, engine_configuration) if part]
    if engine_parts:
        decoded["engine"] = " ".join(engine_parts)

    return decoded


def _canonicalize_vehicle(vehicle: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(vehicle)

    for alias, canonical in _CANONICAL_ALIASES.items():
        if canonical in normalized and not _is_blank(normalized.get(canonical)):
            continue
        if alias in normalized and not _is_blank(normalized.get(alias)):
            normalized[canonical] = normalized[alias]

    for field in (
        "id",
        "vin",
        "make",
        "model",
        "trim",
        "body_type",
        "fuel_type",
        "dealer_name",
        "dealer_location",
        "dealer_zip",
        "source",
        "source_url",
        "availability_status",
        "exterior_color",
        "interior_color",
        "transmission",
        "drivetrain",
    ):
        if field in normalized and isinstance(normalized[field], str):
            normalized[field] = normalized[field].strip()

    if "price" in normalized and isinstance(normalized["price"], str):
        parsed_price = _parse_price(normalized["price"])
        if parsed_price is not None:
            normalized["price"] = parsed_price
    for integer_field in ("mileage", "mpg_city", "mpg_highway", "safety_rating"):
        if integer_field in normalized and isinstance(normalized[integer_field], str):
            parsed_int = _parse_int(normalized[integer_field])
            if parsed_int is not None:
                normalized[integer_field] = parsed_int
    for float_field in ("latitude", "longitude"):
        if float_field in normalized and isinstance(normalized[float_field], str):
            parsed_float = _parse_float(normalized[float_field])
            if parsed_float is not None:
                normalized[float_field] = parsed_float

    if "body_type" in normalized and isinstance(normalized["body_type"], str):
        normalized["body_type"] = _normalize_body_type(normalized["body_type"])
    if "fuel_type" in normalized and isinstance(normalized["fuel_type"], str):
        normalized["fuel_type"] = _normalize_fuel_type(normalized["fuel_type"])
    if "vin" in normalized and isinstance(normalized["vin"], str):
        normalized["vin"] = normalized["vin"].upper()

    if "features" in normalized and isinstance(normalized["features"], str):
        normalized["features"] = [
            feature.strip()
            for feature in normalized["features"].split(",")
            if feature.strip()
        ]

    return normalized


def _maybe_apply_vin_enrichment(
    vehicle: dict[str, Any],
    *,
    warnings: list[str],
) -> bool:
    vin = str(vehicle.get("vin", "")).strip().upper()
    if not vin:
        warnings.append("VIN is missing; saved as low-confidence.")
        return True

    vehicle["vin"] = vin
    if not _VIN_PATTERN.fullmatch(vin):
        warnings.append("VIN format is invalid; decode skipped and record marked low-confidence.")
        return True

    decode_targets = ("year", "make", "model", "body_type", "fuel_type")
    needs_decode = any(_is_blank(vehicle.get(field)) for field in decode_targets)
    if needs_decode:
        decoded = _decode_vin_nhtsa(vin)
        if decoded:
            for field, value in decoded.items():
                if _is_blank(vehicle.get(field)):
                    vehicle[field] = value
        else:
            warnings.append("VIN decode unavailable; using provided fields.")
            # Still try lightweight local fallback for model year/make.
            fallback_year = _decode_model_year_from_vin(vin)
            if fallback_year is not None and _is_blank(vehicle.get("year")):
                vehicle["year"] = fallback_year
            fallback_make = _decode_make_from_wmi(vin)
            if fallback_make and _is_blank(vehicle.get("make")):
                vehicle["make"] = fallback_make
            return True

    if _is_blank(vehicle.get("year")):
        fallback_year = _decode_model_year_from_vin(vin)
        if fallback_year is not None:
            vehicle["year"] = fallback_year
    if _is_blank(vehicle.get("make")):
        fallback_make = _decode_make_from_wmi(vin)
        if fallback_make:
            vehicle["make"] = fallback_make

    return False


def _validate_vehicle_schema(
    vehicle: dict[str, Any], *, index: int | None = None
) -> tuple[dict[str, Any] | None, str | None, list[str], bool]:
    target = f"vehicle at index {index}" if index is not None else "vehicle"
    normalized = _canonicalize_vehicle(vehicle)
    warnings: list[str] = []
    low_confidence = _maybe_apply_vin_enrichment(normalized, warnings=warnings)

    missing = [field for field in _REQUIRED_FIELDS if _is_blank(normalized.get(field))]
    if missing:
        missing_fields = ", ".join(missing)
        return (
            None,
            f"Error: {target} is missing required field(s): {missing_fields}.",
            warnings,
            low_confidence,
        )

    for field in _REQUIRED_STRING_FIELDS:
        value = normalized[field]
        if not isinstance(value, str) or not value.strip():
            return (
                None,
                f"Error: {target} field '{field}' must be a non-empty string.",
                warnings,
                low_confidence,
            )

    year = normalized["year"]
    if isinstance(year, bool) or not isinstance(year, int):
        return None, f"Error: {target} field 'year' must be an integer.", warnings, low_confidence
    current_year = datetime.now(timezone.utc).year
    if year < 1886 or year > current_year + 1:
        return (
            None,
            f"Error: {target} field 'year' must be between 1886 and {current_year + 1}.",
            warnings,
            low_confidence,
        )

    price = normalized["price"]
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return None, f"Error: {target} field 'price' must be a number.", warnings, low_confidence
    if price < 0:
        return (
            None,
            f"Error: {target} field 'price' must be greater than or equal to 0.",
            warnings,
            low_confidence,
        )

    source = str(normalized.get("source", "")).strip() or "manual"
    if low_confidence:
        source = f"{source}_low_confidence"
    normalized["source"] = source

    return normalized, None, warnings, low_confidence


def upsert_vehicle_impl(vehicle: Any) -> str:
    """Validate and upsert a single vehicle into the store."""
    if not isinstance(vehicle, dict):
        return "Error: vehicle payload must be a dict."
    validated_vehicle, schema_error, warnings, _ = _validate_vehicle_schema(vehicle)
    if schema_error or validated_vehicle is None:
        return schema_error

    get_store().upsert(validated_vehicle)
    if warnings:
        return (
            f"Vehicle {validated_vehicle['id']} upserted with {len(warnings)} warning(s): "
            f"{'; '.join(warnings)}"
        )
    return f"Vehicle {validated_vehicle['id']} upserted successfully."


def bulk_upsert_vehicles_impl(vehicles: Any) -> str:
    """Validate and upsert a batch of vehicles into the store."""
    if not isinstance(vehicles, list):
        return "Error: vehicles payload must be a list of dicts."

    validated_vehicles: list[dict[str, Any]] = []
    warning_summaries: list[str] = []
    for i, v in enumerate(vehicles):
        if not isinstance(v, dict):
            return f"Error: vehicle at index {i} must be a dict."
        validated_vehicle, schema_error, warnings, _ = _validate_vehicle_schema(v, index=i)
        if schema_error or validated_vehicle is None:
            return schema_error
        if warnings:
            warning_summaries.extend([f"index {i}: {w}" for w in warnings])
        validated_vehicles.append(validated_vehicle)

    get_store().upsert_many(validated_vehicles)
    if warning_summaries:
        preview = "; ".join(warning_summaries[:5])
        suffix = " ..." if len(warning_summaries) > 5 else ""
        return (
            f"{len(validated_vehicles)} vehicle(s) upserted with "
            f"{len(warning_summaries)} warning(s): {preview}{suffix}"
        )
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
