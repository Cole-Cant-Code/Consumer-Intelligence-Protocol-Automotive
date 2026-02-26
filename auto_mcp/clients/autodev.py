"""Shared async Auto.dev API client."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.IGNORECASE)
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=12)
_CACHE_TTL_SECONDS = 300  # 5 minutes


class AutoDevClientError(RuntimeError):
    """Raised for Auto.dev request/config errors with structured metadata."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details or {}


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


SHARED_AUTODEV_CACHE = _TTLCache()


def _normalize_vin(vin: str) -> str:
    normalized = vin.strip().upper()
    if not _VIN_RE.fullmatch(normalized):
        raise ValueError(
            f"Invalid VIN '{vin}'. VIN must be exactly 17 characters "
            "(letters/digits, excluding I/O/Q)."
        )
    return normalized


class AutoDevClient:
    """Async client for Auto.dev public endpoints."""

    BASE_URL = "https://api.auto.dev"

    def __init__(self, api_key: str, *, cache: _TTLCache | None = None) -> None:
        self.api_key = api_key.strip()
        self.session: aiohttp.ClientSession | None = None
        self._cache = cache or _TTLCache()

    async def __aenter__(self) -> AutoDevClient:
        if not self.api_key:
            raise AutoDevClientError(
                "AUTO_DEV_API_KEY is not configured.",
                code="MISSING_API_KEY",
            )
        self.session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self.session:
            await self.session.close()

    async def _request(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        if not self.session:
            raise RuntimeError("Client not entered as context manager")

        url = f"{self.BASE_URL}{path}"
        cache_key = f"{url}|{params}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            async with self.session.get(
                url,
                params=params,
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                payload: Any
                if hasattr(resp, "text"):
                    raw_text = await resp.text()
                    if raw_text:
                        try:
                            payload = json.loads(raw_text)
                        except json.JSONDecodeError:
                            payload = {"raw": raw_text}
                    else:
                        payload = {}
                elif hasattr(resp, "json"):
                    payload = await resp.json()
                else:
                    payload = {}

                if resp.status >= 400:
                    message = f"Auto.dev request failed with HTTP {resp.status}."
                    if isinstance(payload, dict):
                        message = str(
                            payload.get("error")
                            or payload.get("message")
                            or payload.get("detail")
                            or message
                        )
                    raise AutoDevClientError(
                        message,
                        code="AUTO_DEV_HTTP_ERROR",
                        status=resp.status,
                        details=payload if isinstance(payload, dict) else {"response": payload},
                    )

                self._cache.set(cache_key, payload)
                return payload
        except AutoDevClientError:
            raise
        except TimeoutError as exc:
            raise AutoDevClientError(
                "Auto.dev request timed out.",
                code="TIMEOUT",
                details={"path": path, "params": params or {}},
            ) from exc
        except aiohttp.ClientError as exc:
            logger.error("Auto.dev client error (%s): %s", path, exc)
            raise AutoDevClientError(
                "Auto.dev request failed due to a network/client error.",
                code="NETWORK_ERROR",
                details={"path": path, "params": params or {}, "error": str(exc)},
            ) from exc

    async def get_overview(self) -> dict[str, Any]:
        """Return gateway-level user context from Auto.dev."""
        data = await self._request("")
        return data if isinstance(data, dict) else {"data": data}

    async def decode_vin(self, vin: str) -> dict[str, Any]:
        """Decode a VIN using Auto.dev VIN endpoint."""
        normalized = _normalize_vin(vin)
        data = await self._request(f"/vin/{normalized}")
        return data if isinstance(data, dict) else {"data": data}

    async def get_listing_by_vin(self, vin: str) -> dict[str, Any]:
        """Fetch a listing by VIN from Auto.dev listings endpoint."""
        normalized = _normalize_vin(vin)
        data = await self._request(f"/listings/{normalized}")
        return data if isinstance(data, dict) else {"data": data}

    async def search_listings_raw(
        self,
        *,
        zip_code: str = "",
        distance_miles: int = 50,
        make: str | None = None,
        model: str | None = None,
        page: int = 1,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Search listings from Auto.dev and return raw payload."""
        params: dict[str, str] = {
            "page": str(page),
            "limit": str(limit),
        }
        if zip_code:
            params["zip"] = zip_code
            params["distance"] = str(distance_miles)
        if make:
            normalized_make = make.strip()
            params["vehicle.make"] = normalized_make
        if model:
            normalized_model = model.strip()
            params["vehicle.model"] = normalized_model

        data = await self._request("/listings", params=params)
        return data if isinstance(data, dict) else {"data": data}

    async def search_listings(
        self,
        *,
        zip_code: str = "",
        distance_miles: int = 50,
        make: str | None = None,
        model: str | None = None,
        page: int = 1,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Search listings from Auto.dev and return extracted records list."""
        payload = await self.search_listings_raw(
            zip_code=zip_code,
            distance_miles=distance_miles,
            make=make,
            model=model,
            page=page,
            limit=limit,
        )
        records = payload.get("records")
        if isinstance(records, list):
            return [r for r in records if isinstance(r, dict)]
        listings = payload.get("listings")
        if isinstance(listings, list):
            return [r for r in listings if isinstance(r, dict)]
        results = payload.get("results")
        if isinstance(results, list):
            return [r for r in results if isinstance(r, dict)]
        return []

    async def get_vehicle_photos(self, vin: str) -> dict[str, Any]:
        """Fetch vehicle photos by VIN from Auto.dev."""
        normalized = _normalize_vin(vin)
        data = await self._request(f"/photos/{normalized}")
        return data if isinstance(data, dict) else {"data": data}
