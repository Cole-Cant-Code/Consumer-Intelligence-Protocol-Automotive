"""AutoCIP ingestion pipeline — fetches, normalizes, and upserts vehicle data.

Cherry-picked from the standalone prototype with proper package imports,
no sys.path hacking, and no CLI main().
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from auto_mcp.clients.nhtsa import SHARED_NHTSA_CACHE, NHTSAClient
from auto_mcp.data.inventory import get_store
from auto_mcp.normalization import (
    normalize_body_type as _canonical_body_type,
)
from auto_mcp.normalization import (
    normalize_fuel_type as _canonical_fuel_type,
)
from auto_mcp.normalization import (
    parse_float,
)
from auto_mcp.normalization import (
    parse_int as _canonical_parse_int,
)
from auto_mcp.normalization import (
    parse_price as _canonical_parse_price,
)

logger = logging.getLogger(__name__)

# ── Metro definitions ───────────────────────────────────────────────

TOP_METROS = {
    "wave1": [
        {"name": "New York City", "zips": ["10001", "10101", "10016"], "state": "NY"},
        {"name": "Los Angeles", "zips": ["90001", "90210", "90028"], "state": "CA"},
        {"name": "Chicago", "zips": ["60601", "60616", "60611"], "state": "IL"},
        {"name": "Houston", "zips": ["77001", "77002", "77027"], "state": "TX"},
        {"name": "Phoenix", "zips": ["85001", "85004", "85016"], "state": "AZ"},
        {"name": "Dallas", "zips": ["75201", "75202", "75207"], "state": "TX"},
        {"name": "Austin", "zips": ["78701", "78704", "78731"], "state": "TX"},
        {"name": "San Antonio", "zips": ["78201", "78205", "78216"], "state": "TX"},
    ],
    "wave2": [
        {"name": "Philadelphia", "zips": ["19101", "19103", "19107"], "state": "PA"},
        {"name": "San Diego", "zips": ["92101", "92102", "92109"], "state": "CA"},
        {"name": "Jacksonville", "zips": ["32099", "32202", "32207"], "state": "FL"},
        {"name": "San Francisco", "zips": ["94102", "94103", "94109"], "state": "CA"},
        {"name": "Columbus", "zips": ["43201", "43206", "43215"], "state": "OH"},
        {"name": "Charlotte", "zips": ["28201", "28202", "28205"], "state": "NC"},
        {"name": "Indianapolis", "zips": ["46201", "46204", "46220"], "state": "IN"},
        {"name": "Seattle", "zips": ["98101", "98102", "98109"], "state": "WA"},
    ],
    "wave3": [
        {"name": "Denver", "zips": ["80201", "80202", "80205"], "state": "CO"},
        {"name": "Nashville", "zips": ["37201", "37203", "37212"], "state": "TN"},
        {"name": "Atlanta", "zips": ["30301", "30303", "30309"], "state": "GA"},
        {"name": "Miami", "zips": ["33101", "33131", "33139"], "state": "FL"},
        {"name": "Detroit", "zips": ["48201", "48207", "48226"], "state": "MI"},
        {"name": "Portland", "zips": ["97201", "97205", "97209"], "state": "OR"},
        {"name": "Las Vegas", "zips": ["89101", "89102", "89109"], "state": "NV"},
        {"name": "Minneapolis", "zips": ["55401", "55403", "55408"], "state": "MN"},
        {"name": "Tampa", "zips": ["33601", "33602", "33606"], "state": "FL"},
    ],
}


# ── Configuration ───────────────────────────────────────────────────


@dataclass
class IngestConfig:
    """Configuration for an ingestion run."""
    source: str = "auto_dev"
    metros: list[str] = field(default_factory=lambda: ["wave1"])
    radius_miles: int = 50
    ttl_days: int = 7
    batch_size: int = 100
    rate_limit_per_sec: float = 1.0
    dry_run: bool = False
    auto_dev_key: str = ""


# ── Source clients ──────────────────────────────────────────────────


class AutoDevClient:
    """Client for Auto.dev API (free tier: 1000 calls/month)."""

    BASE_URL = "https://auto.dev/api"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> AutoDevClient:
        self.session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self.session:
            await self.session.close()

    async def search_listings(
        self,
        zip_code: str,
        radius: int = 50,
        make: str | None = None,
        model: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        price_max: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self.session:
            raise RuntimeError("Client not entered as context manager")

        params: dict[str, Any] = {"zip": zip_code, "radius": radius}
        if make:
            params["make"] = make
        if model:
            params["model"] = model
        if year_min:
            params["yearMin"] = year_min
        if year_max:
            params["yearMax"] = year_max
        if price_max:
            params["priceMax"] = price_max

        try:
            async with self.session.get(
                f"{self.BASE_URL}/listings",
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 429:
                    logger.warning("Rate limited by Auto.dev API")
                    return []
                resp.raise_for_status()
                data = await resp.json()
                records = data.get("records")
                if isinstance(records, list):
                    return records
                listings = data.get("listings")
                if isinstance(listings, list):
                    return listings
                return []
        except aiohttp.ClientError as e:
            logger.error("Auto.dev API error: %s", e)
            return []

    async def decode_vin(self, vin: str) -> dict[str, Any] | None:
        if not self.session:
            raise RuntimeError("Client not entered as context manager")

        try:
            async with self.session.get(
                f"{self.BASE_URL}/vin/{vin}",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except aiohttp.ClientError:
            return None


# ── Normalization ───────────────────────────────────────────────────

def normalize_body_type(raw: str | None) -> str:
    return _canonical_body_type(raw) or "other"


def normalize_fuel_type(raw: str | None) -> str:
    return _canonical_fuel_type(raw) or "gasoline"


def parse_price(price_val: Any) -> float:
    return _canonical_parse_price(price_val) or 0.0


def parse_int(value: Any, default: int = 0) -> int:
    result = _canonical_parse_int(value)
    return result if result is not None else default


def normalize_auto_dev_listing(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Convert Auto.dev listing to AutoCIP schema."""
    vin = raw.get("vin", "").upper()
    if not vin or len(vin) != 17:
        return None

    dealer = raw.get("dealer") if isinstance(raw.get("dealer"), dict) else {}

    city = dealer.get("city") or raw.get("city") or ""
    state = dealer.get("state") or raw.get("state") or ""
    if city and state:
        dealer_location = f"{city}, {state}"
    else:
        dealer_location = city or state

    fuel_raw = raw.get("fuelType") or raw.get("fuel")
    if fuel_raw:
        fuel_type = normalize_fuel_type(str(fuel_raw))
    else:
        # Leave blank so optional NHTSA enrichment can fill it later.
        fuel_type = ""

    availability_raw = raw.get("availability_status") or raw.get("availability")
    if not availability_raw and isinstance(raw.get("active"), bool):
        availability_raw = "in_stock" if raw["active"] else "off_market"
    if not availability_raw:
        availability_raw = "in_stock"

    features = raw.get("features", [])
    if not isinstance(features, list):
        features = []

    return {
        "id": f"VIN-{vin}",
        "vin": vin,
        "year": parse_int(raw.get("year", 0)),
        "make": raw.get("make", "").title(),
        "model": raw.get("model", "").title(),
        "trim": raw.get("trim", ""),
        "body_type": normalize_body_type(
            raw.get("bodyType") or raw.get("bodyStyle") or raw.get("type"),
        ),
        "price": parse_price(raw.get("priceUnformatted", raw.get("price"))),
        "mileage": parse_int(raw.get("mileageUnformatted", raw.get("mileage", 0))),
        "exterior_color": raw.get("displayColor", raw.get("exteriorColor", "")),
        "interior_color": raw.get("interiorColor", ""),
        "fuel_type": fuel_type,
        "mpg_city": parse_int(raw.get("mpgCity", 0)),
        "mpg_highway": parse_int(raw.get("mpgHighway", 0)),
        "engine": raw.get("engine", ""),
        "transmission": raw.get("transmission", ""),
        "drivetrain": raw.get("drivetrain", ""),
        "features": features,
        "safety_rating": parse_int(raw.get("safetyRating", 0)),
        "dealer_name": dealer.get("name") or raw.get("dealerName", ""),
        "dealer_location": dealer_location,
        "dealer_zip": str(dealer.get("zip") or raw.get("zip") or raw.get("dealerZip") or ""),
        "latitude": parse_float(dealer.get("latitude") or raw.get("lat")),
        "longitude": parse_float(dealer.get("longitude") or raw.get("lon")),
        "availability_status": str(availability_raw),
        "source": "auto_dev",
        "source_url": raw.get("clickoffUrl") or raw.get("vdpUrl") or raw.get("url", ""),
    }


def enrich_with_nhtsa(
    vehicle: dict[str, Any],
    nhtsa_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Enrich vehicle data with NHTSA VIN decode results (fill missing fields only)."""
    if not nhtsa_data:
        return vehicle

    if not vehicle.get("make"):
        vehicle["make"] = nhtsa_data.get("Make", "").title()
    if not vehicle.get("model"):
        vehicle["model"] = nhtsa_data.get("Model", "").title()
    if not vehicle.get("year"):
        vehicle["year"] = parse_int(nhtsa_data.get("ModelYear", 0))
    if not vehicle.get("fuel_type"):
        vehicle["fuel_type"] = normalize_fuel_type(nhtsa_data.get("FuelTypePrimary"))
    if not vehicle.get("engine"):
        disp = nhtsa_data.get("DisplacementL", "")
        conf = nhtsa_data.get("EngineConfiguration", "")
        vehicle["engine"] = f"{disp}L {conf}".strip()
    if not vehicle.get("body_type"):
        vehicle["body_type"] = normalize_body_type(nhtsa_data.get("BodyClass"))

    return vehicle


# ── Pipeline orchestrator ───────────────────────────────────────────


class IngestionPipeline:
    """Main pipeline for ingesting vehicle data from external APIs."""

    def __init__(self, config: IngestConfig) -> None:
        self.config = config
        self.stats: dict[str, Any] = {}
        self._reset_stats()

    def _reset_stats(self) -> None:
        self.stats: dict[str, Any] = {
            "total_fetched": 0,
            "normalized": 0,
            "deduped": 0,
            "nhtsa_enriched": 0,
            "upserted": 0,
            "errors": [],
        }

    @staticmethod
    def _dedupe_by_vin(vehicles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen_vins: set[str] = set()
        unique: list[dict[str, Any]] = []
        for vehicle in vehicles:
            vin = vehicle["vin"]
            if vin not in seen_vins:
                seen_vins.add(vin)
                unique.append(vehicle)
        return unique

    async def _maybe_enrich_with_nhtsa(
        self,
        vehicles: list[dict[str, Any]],
        *,
        enabled: bool,
    ) -> None:
        if not enabled or not vehicles:
            return

        enriched_count = 0
        semaphore = asyncio.Semaphore(8)

        async def _enrich_one(vehicle: dict[str, Any], client: NHTSAClient) -> bool:
            before = {
                "make": vehicle.get("make"),
                "model": vehicle.get("model"),
                "year": vehicle.get("year"),
                "fuel_type": vehicle.get("fuel_type"),
                "engine": vehicle.get("engine"),
                "body_type": vehicle.get("body_type"),
            }
            try:
                async with semaphore:
                    nhtsa_data = await client.decode_vin(vehicle["vin"])
                enrich_with_nhtsa(vehicle, nhtsa_data)
            except Exception as exc:  # pragma: no cover - defensive path
                logger.error("NHTSA decode failed for VIN %s: %s", vehicle["vin"], exc)
                self.stats["errors"].append(f"nhtsa:{vehicle['vin']}: {exc}")
                return False

            after = {
                "make": vehicle.get("make"),
                "model": vehicle.get("model"),
                "year": vehicle.get("year"),
                "fuel_type": vehicle.get("fuel_type"),
                "engine": vehicle.get("engine"),
                "body_type": vehicle.get("body_type"),
            }
            return before != after

        async with NHTSAClient(cache=SHARED_NHTSA_CACHE) as client:
            results = await asyncio.gather(
                *(_enrich_one(v, client) for v in vehicles),
                return_exceptions=True,
            )
            for result in results:
                if result is True:
                    enriched_count += 1

        self.stats["nhtsa_enriched"] = enriched_count

    async def run_auto_dev(
        self,
        metros: list[dict[str, Any]] | None = None,
        *,
        zip_codes: list[str] | None = None,
        make: str | None = None,
        model: str | None = None,
        enrich_nhtsa_data: bool = True,
    ) -> dict[str, Any]:
        """Fetch listings from Auto.dev and optionally enrich via NHTSA."""
        self._reset_stats()

        if not self.config.auto_dev_key:
            self.stats["errors"].append("No AUTO_DEV_API_KEY configured")
            return self.stats

        target_metros = metros
        if target_metros is None:
            if zip_codes:
                target_metros = [{"name": "Custom ZIP import", "zips": zip_codes}]
            else:
                target_metros = []
                for wave in self.config.metros:
                    target_metros.extend(TOP_METROS.get(wave, []))

        if not target_metros:
            self.stats["errors"].append("No metros or ZIP codes provided")
            return self.stats

        all_vehicles: list[dict[str, Any]] = []

        async with AutoDevClient(self.config.auto_dev_key) as client:
            for metro in target_metros:
                metro_name = metro["name"]
                for zip_code in metro["zips"]:
                    logger.info("Fetching listings for %s (ZIP: %s)", metro_name, zip_code)
                    try:
                        listings = await client.search_listings(
                            zip_code=zip_code,
                            radius=self.config.radius_miles,
                            make=make,
                            model=model,
                        )
                        self.stats["total_fetched"] += len(listings)
                        for raw in listings:
                            normalized = normalize_auto_dev_listing(raw)
                            if normalized:
                                all_vehicles.append(normalized)
                        if self.config.rate_limit_per_sec > 0:
                            await asyncio.sleep(1.0 / self.config.rate_limit_per_sec)
                    except Exception as e:
                        logger.error("Error fetching %s: %s", zip_code, e)
                        self.stats["errors"].append(f"{zip_code}: {e}")

        self.stats["normalized"] = len(all_vehicles)
        unique = self._dedupe_by_vin(all_vehicles)
        self.stats["deduped"] = len(unique)
        await self._maybe_enrich_with_nhtsa(unique, enabled=enrich_nhtsa_data)

        if self.config.dry_run:
            return self.stats

        if unique:
            store = get_store()
            store.upsert_many(unique)
            self.stats["upserted"] = len(unique)

        return self.stats
