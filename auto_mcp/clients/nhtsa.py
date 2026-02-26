"""Shared async NHTSA API client.

Consolidates VIN decoding (previously duplicated in pipeline.py and ingestion.py)
and adds recalls, complaints, and safety ratings endpoints.

All NHTSA APIs are free and require no authentication.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_MAX_RECORDS = 20
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=8)
_CACHE_TTL_SECONDS = 900  # 15 minutes
_CURRENT_YEAR = datetime.now(timezone.utc).year


def _validate_model_year(model_year: int) -> None:
    if not (1886 <= model_year <= _CURRENT_YEAR + 1):
        raise ValueError(
            f"model_year must be between 1886 and {_CURRENT_YEAR + 1}, got {model_year}"
        )


def _normalize_input(value: str) -> str:
    return value.strip().title()


def _date_sort_key(value: str) -> float:
    """Return a comparable timestamp for mixed date formats; unknown dates sort last."""
    text = value.strip()
    if not text:
        return 0.0

    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return 0.0


class _TTLCache:
    """Simple in-memory cache with per-entry TTL."""

    def __init__(self, ttl: int = _CACHE_TTL_SECONDS) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._ttl = ttl

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        self._store.clear()


SHARED_NHTSA_CACHE = _TTLCache()


class NHTSAClient:
    """Async client for NHTSA public APIs (recalls, complaints, safety ratings, VIN decode)."""

    VPIC_BASE = "https://vpic.nhtsa.dot.gov/api/vehicles"
    API_BASE = "https://api.nhtsa.gov"

    def __init__(self, *, cache: _TTLCache | None = None) -> None:
        self.session: aiohttp.ClientSession | None = None
        self._cache = cache or _TTLCache()

    async def __aenter__(self) -> NHTSAClient:
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self.session:
            await self.session.close()

    async def _request(self, url: str, params: dict[str, str] | None = None) -> Any:
        """Make a GET request with retry on transient failures."""
        if not self.session:
            raise RuntimeError("Client not entered as context manager")

        cache_key = f"{url}|{params}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        last_exc: Exception | None = None
        for attempt in range(2):  # 1 retry
            try:
                async with self.session.get(
                    url, params=params, timeout=_REQUEST_TIMEOUT
                ) as resp:
                    if resp.status >= 500:
                        last_exc = aiohttp.ClientResponseError(
                            resp.request_info,
                            resp.history,
                            status=resp.status,
                        )
                        if attempt == 0:
                            continue
                        raise last_exc
                    resp.raise_for_status()
                    data = await resp.json()
                    self._cache.set(cache_key, data)
                    return data
            except (aiohttp.ClientError, TimeoutError) as exc:
                last_exc = exc
                if attempt == 0:
                    continue
                raise

        raise last_exc  # type: ignore[misc]  # pragma: no cover

    # ── VIN Decode ──────────────────────────────────────────────────

    async def decode_vin(self, vin: str) -> dict[str, Any] | None:
        """Decode a VIN via the NHTSA vPIC API."""
        try:
            data = await self._request(
                f"{self.VPIC_BASE}/DecodeVINValuesExtended/{vin}",
                params={"format": "json"},
            )
            results = data.get("Results", [])
            return results[0] if results else None
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.error("NHTSA VIN decode error for %s: %s", vin, exc)
            return None

    # ── Recalls ─────────────────────────────────────────────────────

    async def get_recalls(
        self, make: str, model: str, model_year: int
    ) -> dict[str, Any]:
        """Get recall data for a vehicle by make/model/year."""
        make = _normalize_input(make)
        model = _normalize_input(model)
        _validate_model_year(model_year)

        try:
            data = await self._request(
                f"{self.API_BASE}/recalls/recallsByVehicle",
                params={"make": make, "model": model, "modelYear": str(model_year)},
            )
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.error("NHTSA recalls error: %s", exc)
            return {"count": 0, "summary": {}, "records": [], "error": str(exc)}

        raw_results = data.get("results", [])
        results = [dict(r) for r in raw_results if isinstance(r, dict)]
        count = data.get("Count", len(results))

        # Sort by date descending, cap at _MAX_RECORDS
        for r in results:
            r["_sort_ts"] = _date_sort_key(str(r.get("ReportReceivedDate", "")))
        results.sort(key=lambda r: r["_sort_ts"], reverse=True)

        records = []
        for r in results[:_MAX_RECORDS]:
            r.pop("_sort_ts", None)
            records.append(r)

        # Build summary
        components = {}
        for r in results:
            comp = r.get("Component", "Unknown")
            components[comp] = components.get(comp, 0) + 1

        summary = {
            "total_recalls": count,
            "top_components": dict(
                sorted(components.items(), key=lambda x: x[1], reverse=True)[:5]
            ),
        }
        if results:
            summary["latest_date"] = results[0].get("ReportReceivedDate", "")

        return {"count": count, "summary": summary, "records": records}

    # ── Complaints ──────────────────────────────────────────────────

    async def get_complaints(
        self, make: str, model: str, model_year: int
    ) -> dict[str, Any]:
        """Get complaint data for a vehicle by make/model/year."""
        make = _normalize_input(make)
        model = _normalize_input(model)
        _validate_model_year(model_year)

        try:
            data = await self._request(
                f"{self.API_BASE}/complaints/complaintsByVehicle",
                params={"make": make, "model": model, "modelYear": str(model_year)},
            )
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.error("NHTSA complaints error: %s", exc)
            return {"count": 0, "summary": {}, "records": [], "error": str(exc)}

        raw_results = data.get("results", [])
        results = [dict(r) for r in raw_results if isinstance(r, dict)]
        count = data.get("Count", len(results))

        # Sort by date descending, cap
        for r in results:
            date_text = str(r.get("dateOfIncident", r.get("dateComplaintFiled", "")) or "")
            r["_sort_ts"] = _date_sort_key(date_text)
        results.sort(key=lambda r: r["_sort_ts"], reverse=True)

        records = []
        for r in results[:_MAX_RECORDS]:
            r.pop("_sort_ts", None)
            records.append(r)

        # Build summary
        components = {}
        crash_count = 0
        injury_count = 0
        for r in results:
            comp = r.get("components", "Unknown")
            components[comp] = components.get(comp, 0) + 1
            if r.get("crash", "").upper() == "Y":
                crash_count += 1
            if r.get("injuries", 0):
                try:
                    injury_count += int(r["injuries"])
                except (ValueError, TypeError):
                    pass

        summary: dict[str, Any] = {
            "total_complaints": count,
            "top_components": dict(
                sorted(components.items(), key=lambda x: x[1], reverse=True)[:5]
            ),
            "crash_reports": crash_count,
            "injury_reports": injury_count,
        }
        if results:
            summary["latest_date"] = results[0].get(
                "dateOfIncident", results[0].get("dateComplaintFiled", "")
            )

        return {"count": count, "summary": summary, "records": records}

    # ── Safety Ratings ──────────────────────────────────────────────

    async def get_safety_ratings(
        self, make: str, model: str, model_year: int
    ) -> dict[str, Any]:
        """Get NHTSA safety ratings (2-step: resolve VehicleId variants, then fetch ratings)."""
        make = _normalize_input(make)
        model = _normalize_input(model)
        _validate_model_year(model_year)

        # Step 1: Get VehicleId variants
        try:
            data = await self._request(
                f"{self.API_BASE}/SafetyRatings/modelyear/{model_year}"
                f"/make/{make}/model/{model}",
            )
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.error("NHTSA safety ratings lookup error: %s", exc)
            return {"count": 0, "summary": {}, "records": [], "error": str(exc)}

        variants = data.get("Results", [])
        if not variants:
            return {"count": 0, "summary": {}, "records": []}

        # Step 2: Fetch ratings for each variant
        records = []
        for variant in variants[:_MAX_RECORDS]:
            vehicle_id = variant.get("VehicleId")
            if not vehicle_id:
                continue
            try:
                rating_data = await self._request(
                    f"{self.API_BASE}/SafetyRatings/VehicleId/{vehicle_id}",
                )
                rating_results = rating_data.get("Results", [])
                if rating_results:
                    record = dict(rating_results[0])
                    record["VehicleVariant"] = variant.get("VehicleDescription", "")
                    records.append(record)
            except (aiohttp.ClientError, TimeoutError) as exc:
                logger.error(
                    "NHTSA safety rating fetch error for VehicleId %s: %s",
                    vehicle_id,
                    exc,
                )

        # Build summary from first record (primary variant)
        summary: dict[str, Any] = {"variants_found": len(variants)}
        if records:
            primary = records[0]
            for key in (
                "OverallRating",
                "OverallFrontCrashRating",
                "OverallSideCrashRating",
                "RolloverRating",
            ):
                val = primary.get(key, "Not Rated")
                summary[key] = val

        return {"count": len(records), "summary": summary, "records": records}
