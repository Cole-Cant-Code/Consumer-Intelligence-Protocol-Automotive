"""Auto.dev tool implementations (overview, VIN decode, listings, photos)."""

from __future__ import annotations

import os
import re
from typing import Any

from cip_protocol import CIP

from auto_mcp.clients.autodev import (
    SHARED_AUTODEV_CACHE,
    AutoDevClient,
    AutoDevClientError,
)
from auto_mcp.data.inventory import get_vehicle
from auto_mcp.tools.orchestration import _build_raw_response, run_tool_with_orchestration

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.IGNORECASE)

_TOOL_OVERVIEW = "get_autodev_overview"
_TOOL_VIN_DECODE = "get_autodev_vin_decode"
_TOOL_LISTINGS = "get_autodev_listings"
_TOOL_PHOTOS = "get_autodev_vehicle_photos"


def _format_error(
    *,
    tool_name: str,
    raw: bool,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> str:
    if not raw:
        return message

    payload: dict[str, Any] = {"error": True, "code": code, "message": message}
    if details:
        payload["details"] = details
    return _build_raw_response(tool_name, payload)


def _require_api_key(*, tool_name: str, raw: bool) -> tuple[str | None, str | None]:
    api_key = os.environ.get("AUTO_DEV_API_KEY", "").strip()
    if api_key:
        return api_key, None
    return None, _format_error(
        tool_name=tool_name,
        raw=raw,
        code="MISSING_API_KEY",
        message="AUTO_DEV_API_KEY environment variable is not set.",
    )


def _normalize_vin(vin: str | None) -> tuple[str | None, str | None]:
    if not vin:
        return None, "VIN is required."
    normalized = vin.strip().upper()
    if not _VIN_RE.fullmatch(normalized):
        return None, (
            f"Invalid VIN '{vin}'. VIN must be 17 characters "
            "(letters/digits, excluding I/O/Q)."
        )
    return normalized, None


def _resolve_vin_from_vehicle(vehicle_id: str) -> tuple[str | None, str | None]:
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return None, f"Vehicle with ID '{vehicle_id}' not found in inventory."
    vin_value = str(vehicle.get("vin", "")).strip().upper()
    if not vin_value:
        return None, f"Vehicle '{vehicle_id}' is missing VIN in inventory."
    if not _VIN_RE.fullmatch(vin_value):
        return None, f"Vehicle '{vehicle_id}' has invalid VIN format in inventory."
    return vin_value, None


def _summarize_overview(payload: dict[str, Any]) -> dict[str, Any]:
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    api = payload.get("api") if isinstance(payload.get("api"), dict) else {}
    discover = (
        payload.get("discover") if isinstance(payload.get("discover"), dict) else {}
    )
    subscription = (
        user.get("subscription") if isinstance(user.get("subscription"), dict) else {}
    )
    usage = user.get("usage") if isinstance(user.get("usage"), dict) else {}
    return {
        "plan": subscription.get("plan")
        or subscription.get("name")
        or user.get("plan")
        or "",
        "tier": subscription.get("tier") or "",
        "free_api_calls_left": usage.get("freeApiCallsLeft")
        or usage.get("remaining")
        or user.get("freeApiCallsLeft"),
        "api_calls_used": usage.get("apiCallsUsed")
        or usage.get("used")
        or user.get("apiCallsUsed"),
        "cost_this_month": usage.get("costThisMonth") or user.get("costThisMonth"),
        "api_name": api.get("name", ""),
        "docs_url": api.get("docs") or "",
        "login_url": api.get("login") or "",
        "discovery_endpoint_count": len(discover),
    }


def _extract_listing_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [data]

    records = payload.get("records")
    if isinstance(records, list):
        return [r for r in records if isinstance(r, dict)]

    listings = payload.get("listings")
    if isinstance(listings, list):
        return [r for r in listings if isinstance(r, dict)]

    results = payload.get("results")
    if isinstance(results, list):
        return [r for r in results if isinstance(r, dict)]

    if payload and ("vin" in payload or "vehicle" in payload):
        return [payload]

    return []


def _compact_listing(record: dict[str, Any]) -> dict[str, Any]:
    vehicle = record.get("vehicle") if isinstance(record.get("vehicle"), dict) else {}
    listing = (
        record.get("retailListing")
        if isinstance(record.get("retailListing"), dict)
        else {}
    )
    dealer = record.get("dealer") if isinstance(record.get("dealer"), dict) else {}

    return {
        "vin": record.get("vin") or vehicle.get("vin", ""),
        "year": record.get("year") or vehicle.get("year"),
        "make": record.get("make") or vehicle.get("make"),
        "model": record.get("model") or vehicle.get("model"),
        "trim": record.get("trim") or vehicle.get("trim"),
        "price": record.get("price") or listing.get("price"),
        "mileage": (
            record.get("mileage")
            or listing.get("mileage")
            or listing.get("miles")
            or vehicle.get("mileage")
        ),
        "dealer_name": (
            dealer.get("name")
            or listing.get("dealer")
            or record.get("dealerName")
            or record.get("dealer")
        ),
        "dealer_zip": (
            dealer.get("zip")
            or listing.get("zip")
            or record.get("zip")
        ),
        "vdp_url": listing.get("vdp") or listing.get("vdpUrl") or record.get("vdpUrl"),
    }


def _extract_photo_items(payload: dict[str, Any], *, max_photos: int) -> list[dict[str, Any]]:
    photos = payload.get("photos")
    if not isinstance(photos, list):
        photos = payload.get("results")
    if not isinstance(photos, list):
        photos = payload.get("records")
    if not isinstance(photos, list):
        if "url" in payload:
            photos = [payload]
        else:
            photos = []

    extracted: list[dict[str, Any]] = []
    for item in photos:
        if isinstance(item, str):
            extracted.append({"url": item})
            continue
        if not isinstance(item, dict):
            continue
        url = (
            item.get("url")
            or item.get("href")
            or item.get("src")
            or item.get("photoUrl")
            or ""
        )
        if not url:
            continue
        extracted.append(
            {
                "url": url,
                "shot_code": item.get("shotCode", ""),
                "width": item.get("width"),
                "height": item.get("height"),
            }
        )
        if len(extracted) >= max_photos:
            break

    return extracted


def _format_autodev_exception(
    *,
    tool_name: str,
    raw: bool,
    exc: AutoDevClientError,
) -> str:
    details = {"code": exc.code}
    if exc.status is not None:
        details["status"] = exc.status
    if exc.details:
        details["details"] = exc.details
    return _format_error(
        tool_name=tool_name,
        raw=raw,
        code=exc.code,
        message=str(exc),
        details=details,
    )


async def get_autodev_overview_impl(
    cip: CIP,
    *,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Return Auto.dev account/gateway overview metadata."""
    api_key, error = _require_api_key(tool_name=_TOOL_OVERVIEW, raw=raw)
    if error:
        return error

    try:
        async with AutoDevClient(api_key or "", cache=SHARED_AUTODEV_CACHE) as client:
            payload = await client.get_overview()
    except AutoDevClientError as exc:
        return _format_autodev_exception(tool_name=_TOOL_OVERVIEW, raw=raw, exc=exc)

    summary = _summarize_overview(payload)
    user_input = "Summarize Auto.dev account and API usage overview."
    data_context: dict[str, Any] = {
        "autodev_overview": summary,
        "autodev_overview_raw": payload,
        "data_source": "Auto.dev API gateway (api.auto.dev)",
    }
    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name=_TOOL_OVERVIEW,
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )


async def get_autodev_vin_decode_impl(
    cip: CIP,
    *,
    vin: str,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Decode a VIN via Auto.dev."""
    normalized_vin, vin_error = _normalize_vin(vin)
    if vin_error:
        return _format_error(
            tool_name=_TOOL_VIN_DECODE,
            raw=raw,
            code="INVALID_INPUT",
            message=vin_error,
        )

    api_key, error = _require_api_key(tool_name=_TOOL_VIN_DECODE, raw=raw)
    if error:
        return error

    try:
        async with AutoDevClient(api_key or "", cache=SHARED_AUTODEV_CACHE) as client:
            payload = await client.decode_vin(normalized_vin or "")
    except AutoDevClientError as exc:
        return _format_autodev_exception(tool_name=_TOOL_VIN_DECODE, raw=raw, exc=exc)

    user_input = f"Decode VIN {normalized_vin} using Auto.dev."
    data_context: dict[str, Any] = {
        "vin": normalized_vin,
        "autodev_vin_decode": payload,
        "data_source": "Auto.dev VIN endpoint (api.auto.dev/vin/{vin})",
    }
    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name=_TOOL_VIN_DECODE,
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )


async def get_autodev_listings_impl(
    cip: CIP,
    *,
    vin: str | None = None,
    zip_code: str = "",
    distance_miles: int = 50,
    make: str | None = None,
    model: str | None = None,
    page: int = 1,
    limit: int = 25,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Search Auto.dev listings, or fetch one listing by VIN."""
    if page < 1:
        return _format_error(
            tool_name=_TOOL_LISTINGS,
            raw=raw,
            code="INVALID_INPUT",
            message="page must be >= 1.",
        )
    if not (1 <= limit <= 100):
        return _format_error(
            tool_name=_TOOL_LISTINGS,
            raw=raw,
            code="INVALID_INPUT",
            message="limit must be between 1 and 100.",
        )
    if not (1 <= distance_miles <= 500):
        return _format_error(
            tool_name=_TOOL_LISTINGS,
            raw=raw,
            code="INVALID_INPUT",
            message="distance_miles must be between 1 and 500.",
        )

    normalized_vin: str | None = None
    resolution_note = ""
    if vin:
        normalized_vin, vin_error = _normalize_vin(vin)
        if vin_error:
            return _format_error(
                tool_name=_TOOL_LISTINGS,
                raw=raw,
                code="INVALID_INPUT",
                message=vin_error,
            )
        ignored_parts: list[str] = []
        if zip_code.strip():
            ignored_parts.append(f"zip_code={zip_code.strip()}")
        if make:
            ignored_parts.append(f"make={make}")
        if model:
            ignored_parts.append(f"model={model}")
        if ignored_parts:
            resolution_note = (
                f"Resolved by VIN {normalized_vin}; {', '.join(ignored_parts)} ignored."
            )
    elif not zip_code.strip():
        return _format_error(
            tool_name=_TOOL_LISTINGS,
            raw=raw,
            code="INVALID_INPUT",
            message="Provide either vin or zip_code for listings lookup.",
        )

    api_key, error = _require_api_key(tool_name=_TOOL_LISTINGS, raw=raw)
    if error:
        return error

    try:
        async with AutoDevClient(api_key or "", cache=SHARED_AUTODEV_CACHE) as client:
            if normalized_vin:
                payload = await client.get_listing_by_vin(normalized_vin)
            else:
                payload = await client.search_listings_raw(
                    zip_code=zip_code.strip(),
                    distance_miles=distance_miles,
                    make=make,
                    model=model,
                    page=page,
                    limit=limit,
                )
    except AutoDevClientError as exc:
        return _format_autodev_exception(tool_name=_TOOL_LISTINGS, raw=raw, exc=exc)

    records = _extract_listing_records(payload)
    compact = [_compact_listing(r) for r in records[:limit]]
    query_summary = {
        "vin": normalized_vin,
        "zip_code": zip_code.strip() or None,
        "distance_miles": distance_miles,
        "make": make,
        "model": model,
        "page": page,
        "limit": limit,
    }
    user_input = (
        f"Fetch Auto.dev listings for {query_summary}. "
        "Summarize key vehicles and notable pricing/mileage patterns."
    )
    data_context: dict[str, Any] = {
        "autodev_query": query_summary,
        "autodev_listings_count": len(records),
        "autodev_listings": compact,
        "autodev_listings_raw": payload,
        "data_source": "Auto.dev listings endpoint (api.auto.dev/listings)",
    }
    if resolution_note:
        data_context["resolution_note"] = resolution_note
    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name=_TOOL_LISTINGS,
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )


async def get_autodev_vehicle_photos_impl(
    cip: CIP,
    *,
    vin: str | None = None,
    vehicle_id: str | None = None,
    max_photos: int = 12,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Fetch Auto.dev vehicle photos by VIN (or inventory vehicle_id)."""
    if not (1 <= max_photos <= 50):
        return _format_error(
            tool_name=_TOOL_PHOTOS,
            raw=raw,
            code="INVALID_INPUT",
            message="max_photos must be between 1 and 50.",
        )

    normalized_vin: str | None = None
    resolution_note = ""
    if vin:
        normalized_vin, vin_error = _normalize_vin(vin)
        if vin_error:
            return _format_error(
                tool_name=_TOOL_PHOTOS,
                raw=raw,
                code="INVALID_INPUT",
                message=vin_error,
            )
        if vehicle_id:
            resolution_note = (
                f"Resolved from VIN {normalized_vin}; vehicle_id={vehicle_id} ignored."
            )
    elif vehicle_id:
        normalized_vin, resolve_error = _resolve_vin_from_vehicle(vehicle_id)
        if resolve_error:
            return _format_error(
                tool_name=_TOOL_PHOTOS,
                raw=raw,
                code="INVALID_INPUT",
                message=resolve_error,
            )
        resolution_note = f"Resolved VIN {normalized_vin} from vehicle_id={vehicle_id}."
    else:
        return _format_error(
            tool_name=_TOOL_PHOTOS,
            raw=raw,
            code="INVALID_INPUT",
            message="Provide vin or vehicle_id for photo lookup.",
        )

    api_key, error = _require_api_key(tool_name=_TOOL_PHOTOS, raw=raw)
    if error:
        return error

    try:
        async with AutoDevClient(api_key or "", cache=SHARED_AUTODEV_CACHE) as client:
            payload = await client.get_vehicle_photos(normalized_vin or "")
    except AutoDevClientError as exc:
        return _format_autodev_exception(tool_name=_TOOL_PHOTOS, raw=raw, exc=exc)

    photos = _extract_photo_items(payload, max_photos=max_photos)
    user_input = f"Fetch Auto.dev vehicle photos for VIN {normalized_vin}."
    data_context: dict[str, Any] = {
        "vehicle": {"vin": normalized_vin},
        "autodev_photos_count": len(photos),
        "autodev_photos": photos,
        "autodev_photos_raw": payload,
        "data_source": "Auto.dev photos endpoint (api.auto.dev/photos/{vin})",
    }
    if vehicle_id:
        data_context["vehicle"]["vehicle_id"] = vehicle_id
    if resolution_note:
        data_context["resolution_note"] = resolution_note

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name=_TOOL_PHOTOS,
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )
