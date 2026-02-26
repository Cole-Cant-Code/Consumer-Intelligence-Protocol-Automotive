"""VehicleStore protocol and SQLite implementation for live inventory."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import (
    Any,
    Protocol,
    runtime_checkable,
)

from cip_protocol.engagement.scoring import (
    LeadScoringConfig,
)
from cip_protocol.engagement.scoring import lead_score_band as _cip_lead_score_band
from cip_protocol.engagement.scoring import recency_multiplier as _cip_recency_multiplier

# 32 public fields that every vehicle dict must expose (no internal metadata).
VEHICLE_FIELDS = (
    "id", "year", "make", "model", "trim", "body_type", "price",
    "mileage", "exterior_color", "interior_color", "fuel_type",
    "mpg_city", "mpg_highway", "engine", "transmission", "drivetrain",
    "features", "safety_rating", "dealer_name", "dealer_location",
    "availability_status", "vin",
    # Geo fields
    "dealer_zip", "latitude", "longitude",
    # Source tracking
    "source", "source_url",
    # TTL fields
    "ingested_at", "expires_at", "last_verified",
    # Platform fields
    "is_featured", "lead_count",
)
PUBLIC_COLUMNS = ", ".join(VEHICLE_FIELDS)

_UPDATE_COLS = [f for f in VEHICLE_FIELDS if f != "id"]
UPSERT_SQL = (
    "INSERT INTO vehicles ("
    + ", ".join(VEHICLE_FIELDS)
    + ", updated_at) VALUES ("
    + ", ".join(["?"] * (len(VEHICLE_FIELDS) + 1))
    + ") ON CONFLICT(id) DO UPDATE SET "
    + ", ".join(f"{c}=excluded.{c}" for c in _UPDATE_COLS)
    + ", updated_at=excluded.updated_at"
)

DEFAULT_TTL_DAYS = 7
EARTH_RADIUS_MILES = 3959
ARCHIVED_SOLD_STATUS = "archived_sold"
ARCHIVED_REMOVED_STATUS = "archived_removed"
_ARCHIVED_STATUSES = (ARCHIVED_SOLD_STATUS, ARCHIVED_REMOVED_STATUS)
SOLD_STATUS = "sold"
_HIDDEN_FROM_CUSTOMER_SEARCH_STATUSES = (
    SOLD_STATUS,
    ARCHIVED_SOLD_STATUS,
    ARCHIVED_REMOVED_STATUS,
)

LEAD_SCORE_WEIGHTS: dict[str, float] = {
    "viewed": 1.0,
    "compared": 3.0,
    "financed": 6.0,
    "availability_check": 5.0,
    "test_drive": 8.0,
    "reserve_vehicle": 9.0,
    "contact_dealer": 4.0,
    "purchase_deposit": 10.0,
}

AUTO_SCORING_CONFIG = LeadScoringConfig(
    action_weights=LEAD_SCORE_WEIGHTS,
    status_thresholds=[
        (0, "new"),
        (10, "engaged"),
        (22, "qualified"),
    ],
    recency_bands=[
        (1, 1.0),
        (3, 0.85),
        (7, 0.70),
        (14, 0.50),
        (30, 0.30),
    ],
    recency_default=0.0,
    score_bands=[
        (22, "hot"),
        (10, "warm"),
        (0, "cold"),
    ],
    terminal_statuses=frozenset({"won", "lost"}),
    scoring_window_days=30,
)

FUNNEL_STAGE_ACTIONS: dict[str, tuple[str, ...]] = {
    "discovery": ("viewed",),
    "consideration": ("compared", "save_favorite", "get_similar_vehicles"),
    "financial": (
        "financed",
        "compare_financing_scenarios",
        "estimate_financing",
        "estimate_out_the_door_price",
    ),
    "intent": (
        "availability_check",
        "test_drive",
        "reserve_vehicle",
        "contact_dealer",
        "purchase_deposit",
    ),
    "outcome": ("sale_closed",),
}


# ── Zip-code coordinate lookup ──────────────────────────────────────


@dataclass
class ZipCoord:
    """Latitude/longitude for a ZIP code."""
    zip_code: str
    lat: float
    lng: float
    city: str
    state: str


class ZipCodeDatabase:
    """In-memory ZIP code -> lat/lng lookup for top US metros."""

    def __init__(self) -> None:
        self._coords: dict[str, ZipCoord] = {}
        self._load()

    def _load(self) -> None:
        # Keep ZIP coverage in sync with ingestion TOP_METROS.
        metro_specs = [
            ("New York City", "NY", 40.7505, -73.9934, ["10001", "10101", "10016"]),
            ("Los Angeles", "CA", 33.9739, -118.2484, ["90001", "90210", "90028"]),
            ("Chicago", "IL", 41.8853, -87.6221, ["60601", "60616", "60611"]),
            ("Houston", "TX", 29.8131, -95.3098, ["77001", "77002", "77027"]),
            ("Phoenix", "AZ", 33.4484, -112.0740, ["85001", "85004", "85016"]),
            ("Dallas", "TX", 32.7842, -96.7975, ["75201", "75202", "75207"]),
            ("Austin", "TX", 30.2672, -97.7431, ["78701", "78704", "78731"]),
            ("San Antonio", "TX", 29.4680, -98.5375, ["78201", "78205", "78216"]),
            ("Philadelphia", "PA", 39.9526, -75.1652, ["19101", "19103", "19107"]),
            ("San Diego", "CA", 32.7157, -117.1611, ["92101", "92102", "92109"]),
            ("Jacksonville", "FL", 30.3322, -81.6557, ["32099", "32202", "32207"]),
            ("San Francisco", "CA", 37.7849, -122.4194, ["94102", "94103", "94109"]),
            ("Columbus", "OH", 39.9894, -83.0115, ["43201", "43206", "43215"]),
            ("Charlotte", "NC", 35.2271, -80.8431, ["28201", "28202", "28205"]),
            ("Indianapolis", "IN", 39.7684, -86.1581, ["46201", "46204", "46220"]),
            ("Seattle", "WA", 47.6062, -122.3321, ["98101", "98102", "98109"]),
            ("Denver", "CO", 39.7392, -104.9903, ["80201", "80202", "80205"]),
            ("Nashville", "TN", 36.1627, -86.7816, ["37201", "37203", "37212"]),
            ("Atlanta", "GA", 33.7490, -84.3880, ["30301", "30303", "30309"]),
            ("Miami", "FL", 25.7743, -80.1937, ["33101", "33131", "33139"]),
            ("Detroit", "MI", 42.3314, -83.0458, ["48201", "48207", "48226"]),
            ("Portland", "OR", 45.5051, -122.6309, ["97201", "97205", "97209"]),
            ("Las Vegas", "NV", 36.1716, -115.1391, ["89101", "89102", "89109"]),
            ("Minneapolis", "MN", 44.9833, -93.2667, ["55401", "55403", "55408"]),
            ("Tampa", "FL", 27.9506, -82.4572, ["33601", "33602", "33606"]),
            # Seed-data metros not in TOP_METROS.
            ("Fort Worth", "TX", 32.7511, -97.3296, ["76101"]),
            ("Round Rock", "TX", 30.5083, -97.6789, ["78664"]),
            ("Georgetown", "TX", 30.6333, -97.6780, ["78626"]),
        ]
        for city, state, lat, lng, zip_codes in metro_specs:
            for zip_code in zip_codes:
                self._coords[zip_code] = ZipCoord(zip_code, lat, lng, city, state)

    def get(self, zip_code: str) -> ZipCoord | None:
        return self._coords.get(zip_code)

    def get_all(self) -> dict[str, ZipCoord]:
        return self._coords.copy()


# ── Protocol ────────────────────────────────────────────────────────


@runtime_checkable
class VehicleStore(Protocol):
    """Minimal interface for vehicle persistence."""

    def get(self, vehicle_id: str) -> dict[str, Any] | None: ...
    def get_many(self, vehicle_ids: list[str]) -> list[dict[str, Any]]: ...
    def get_by_vin(self, vin: str) -> dict[str, Any] | None: ...
    def search(
        self,
        *,
        make: str | None = None,
        model: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        body_type: str | None = None,
        fuel_type: str | None = None,
        dealer_location: str | None = None,
        dealer_zip: str | None = None,
        include_sold: bool = False,
    ) -> list[dict[str, Any]]: ...
    def search_by_location(
        self,
        *,
        center_lat: float,
        center_lng: float,
        radius_miles: float,
        make: str | None = None,
        model: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        body_type: str | None = None,
        fuel_type: str | None = None,
        max_results: int = 25,
        include_sold: bool = False,
    ) -> list[dict[str, Any]]: ...
    def upsert(self, vehicle: dict[str, Any]) -> None: ...
    def upsert_many(self, vehicles: list[dict[str, Any]]) -> None: ...
    def remove(self, vehicle_id: str) -> bool: ...
    def remove_expired(self) -> int: ...
    def count(self) -> int: ...
    def get_stats(self) -> dict[str, Any]: ...
    def record_lead(
        self,
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
    ) -> str: ...
    def get_lead_analytics(self, days: int = 30) -> dict[str, Any]: ...
    def get_hot_leads(
        self,
        *,
        limit: int = 10,
        min_score: float = 10.0,
        dealer_zip: str = "",
        days: int = 30,
    ) -> list[dict[str, Any]]: ...
    def get_lead_detail(self, lead_id: str, *, days: int = 90) -> dict[str, Any] | None: ...
    def get_inventory_aging_report(
        self,
        *,
        min_days_on_lot: int = 30,
        limit: int = 100,
        dealer_zip: str = "",
    ) -> dict[str, Any]: ...
    def get_pricing_opportunities(
        self,
        *,
        limit: int = 25,
        stale_days_threshold: int = 45,
        overpriced_threshold_pct: float = 5.0,
        underpriced_threshold_pct: float = -5.0,
    ) -> dict[str, Any]: ...
    def record_sale(
        self,
        *,
        vehicle_id: str,
        sold_price: float,
        sold_at: str,
        lead_id: str = "",
        source_channel: str = "direct",
        salesperson_id: str = "",
        keep_vehicle_record: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
    def get_funnel_metrics(
        self,
        *,
        days: int = 30,
        dealer_zip: str = "",
        breakdown_by: str = "none",
    ) -> dict[str, Any]: ...


class SqliteVehicleStore:
    """SQLite-backed vehicle store with WAL mode and NOCASE indexes."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._escalation_store: object | None = None
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute("PRAGMA cache_size=-20000")
            self._create_schema()

    # ── Escalation opt-in ──────────────────────────────────────────

    def enable_escalations(self) -> object:
        """Enable escalation detection. Returns the EscalationStore for tool use."""
        from auto_mcp.escalation.store import EscalationStore as _EscStore

        if self._escalation_store is None:
            self._escalation_store = _EscStore(
                self._conn, self._lock, entity_id_field="vehicle_id",
            )
        return self._escalation_store

    # ── Schema ─────────────────────────────────────────────────────

    def _create_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS vehicles (
                id              TEXT PRIMARY KEY,
                year            INTEGER NOT NULL,
                make            TEXT NOT NULL COLLATE NOCASE,
                model           TEXT NOT NULL COLLATE NOCASE,
                trim            TEXT NOT NULL DEFAULT '',
                body_type       TEXT NOT NULL COLLATE NOCASE,
                price           REAL NOT NULL,
                mileage         INTEGER NOT NULL DEFAULT 0,
                exterior_color  TEXT NOT NULL DEFAULT '',
                interior_color  TEXT NOT NULL DEFAULT '',
                fuel_type       TEXT NOT NULL COLLATE NOCASE,
                mpg_city        INTEGER NOT NULL DEFAULT 0,
                mpg_highway     INTEGER NOT NULL DEFAULT 0,
                engine          TEXT NOT NULL DEFAULT '',
                transmission    TEXT NOT NULL DEFAULT '',
                drivetrain      TEXT NOT NULL DEFAULT '',
                features        TEXT NOT NULL DEFAULT '[]',
                safety_rating   INTEGER NOT NULL DEFAULT 0,
                dealer_name     TEXT NOT NULL DEFAULT '',
                dealer_location TEXT NOT NULL DEFAULT '' COLLATE NOCASE,
                availability_status TEXT NOT NULL DEFAULT 'in_stock',
                vin             TEXT NOT NULL DEFAULT '',
                updated_at      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_vehicles_make
                ON vehicles(make COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_vehicles_body_type
                ON vehicles(body_type COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_vehicles_fuel_type
                ON vehicles(fuel_type COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_vehicles_dealer_location
                ON vehicles(dealer_location COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_vehicles_make_model
                ON vehicles(make COLLATE NOCASE, model COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_vehicles_price
                ON vehicles(price);
            CREATE INDEX IF NOT EXISTS idx_vehicles_year
                ON vehicles(year);
            -- Composite covering indexes for common multi-column search patterns
            CREATE INDEX IF NOT EXISTS idx_vehicles_make_body_price
                ON vehicles(make COLLATE NOCASE, body_type COLLATE NOCASE, price);
            CREATE INDEX IF NOT EXISTS idx_vehicles_body_fuel_price
                ON vehicles(body_type COLLATE NOCASE, fuel_type COLLATE NOCASE, price);
            CREATE INDEX IF NOT EXISTS idx_vehicles_make_model_year
                ON vehicles(make COLLATE NOCASE, model COLLATE NOCASE, year);
        """)

        # Migration: add new columns to existing databases
        new_columns = [
            ("dealer_zip", "TEXT NOT NULL DEFAULT ''"),
            ("latitude", "REAL"),
            ("longitude", "REAL"),
            ("source", "TEXT NOT NULL DEFAULT 'seed'"),
            ("source_url", "TEXT NOT NULL DEFAULT ''"),
            ("ingested_at", "TEXT NOT NULL DEFAULT ''"),
            ("expires_at", "TEXT NOT NULL DEFAULT ''"),
            ("last_verified", "TEXT NOT NULL DEFAULT ''"),
            ("is_featured", "INTEGER NOT NULL DEFAULT 0"),
            ("lead_count", "INTEGER NOT NULL DEFAULT 0"),
        ]
        for col_name, col_def in new_columns:
            try:
                self._conn.execute(f"ALTER TABLE vehicles ADD COLUMN {col_name} {col_def}")
            except sqlite3.OperationalError:
                pass  # column already exists

        # New tables + indexes for new columns
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS leads (
                id              TEXT PRIMARY KEY,
                vehicle_id      TEXT NOT NULL,
                vehicle_vin     TEXT,
                dealer_name     TEXT,
                dealer_zip      TEXT,
                action          TEXT NOT NULL,
                user_query      TEXT DEFAULT '',
                created_at      TEXT NOT NULL,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS lead_profiles (
                id              TEXT PRIMARY KEY,
                customer_id     TEXT NOT NULL DEFAULT '',
                session_id      TEXT NOT NULL DEFAULT '',
                customer_name   TEXT NOT NULL DEFAULT '',
                customer_contact TEXT NOT NULL DEFAULT '',
                status          TEXT NOT NULL DEFAULT 'new',
                score           REAL NOT NULL DEFAULT 0,
                first_seen_at   TEXT NOT NULL,
                last_activity_at TEXT NOT NULL,
                last_vehicle_id TEXT NOT NULL DEFAULT '',
                source_channel  TEXT NOT NULL DEFAULT 'direct',
                notes           TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS sales (
                id              TEXT PRIMARY KEY,
                vehicle_id      TEXT NOT NULL,
                lead_id         TEXT NOT NULL DEFAULT '',
                dealer_name     TEXT NOT NULL DEFAULT '',
                dealer_zip      TEXT NOT NULL DEFAULT '',
                sold_price      REAL NOT NULL,
                listed_price    REAL NOT NULL,
                source_channel  TEXT NOT NULL DEFAULT 'direct',
                salesperson_id  TEXT NOT NULL DEFAULT '',
                sold_at         TEXT NOT NULL,
                recorded_at     TEXT NOT NULL,
                metadata        TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS ingestion_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                source          TEXT NOT NULL,
                started_at      TEXT NOT NULL,
                completed_at    TEXT,
                vehicles_added  INTEGER DEFAULT 0,
                vehicles_updated INTEGER DEFAULT 0,
                vehicles_removed INTEGER DEFAULT 0,
                errors          TEXT DEFAULT '[]',
                status          TEXT DEFAULT 'running'
            );

            CREATE INDEX IF NOT EXISTS idx_vehicles_dealer_zip
                ON vehicles(dealer_zip);
            CREATE INDEX IF NOT EXISTS idx_vehicles_expires_at
                ON vehicles(expires_at);
            CREATE INDEX IF NOT EXISTS idx_vehicles_source
                ON vehicles(source);
            CREATE INDEX IF NOT EXISTS idx_vehicles_featured
                ON vehicles(is_featured);
            CREATE INDEX IF NOT EXISTS idx_leads_vehicle_id
                ON leads(vehicle_id);
            CREATE INDEX IF NOT EXISTS idx_leads_dealer_zip
                ON leads(dealer_zip);
            CREATE INDEX IF NOT EXISTS idx_leads_created_at
                ON leads(created_at);
            CREATE INDEX IF NOT EXISTS idx_leads_action
                ON leads(action);
            CREATE INDEX IF NOT EXISTS idx_lead_profiles_score
                ON lead_profiles(score);
            CREATE INDEX IF NOT EXISTS idx_lead_profiles_last_activity
                ON lead_profiles(last_activity_at);
            CREATE INDEX IF NOT EXISTS idx_lead_profiles_status
                ON lead_profiles(status);
            CREATE INDEX IF NOT EXISTS idx_sales_sold_at
                ON sales(sold_at);
            CREATE INDEX IF NOT EXISTS idx_sales_dealer_zip
                ON sales(dealer_zip);
            CREATE INDEX IF NOT EXISTS idx_sales_lead_id
                ON sales(lead_id);
            CREATE INDEX IF NOT EXISTS idx_sales_source_channel
                ON sales(source_channel);
        """)

        leads_new_columns = [
            ("lead_id", "TEXT NOT NULL DEFAULT ''"),
            ("customer_id", "TEXT NOT NULL DEFAULT ''"),
            ("session_id", "TEXT NOT NULL DEFAULT ''"),
            ("customer_name", "TEXT NOT NULL DEFAULT ''"),
            ("customer_contact", "TEXT NOT NULL DEFAULT ''"),
            ("source_channel", "TEXT NOT NULL DEFAULT 'direct'"),
            ("event_meta", "TEXT NOT NULL DEFAULT '{}'"),
        ]
        for col_name, col_def in leads_new_columns:
            try:
                self._conn.execute(f"ALTER TABLE leads ADD COLUMN {col_name} {col_def}")
            except sqlite3.OperationalError:
                pass  # column already exists

        self._conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_leads_lead_id
                ON leads(lead_id);
            CREATE INDEX IF NOT EXISTS idx_leads_customer_id
                ON leads(customer_id);
            CREATE INDEX IF NOT EXISTS idx_leads_session_id
                ON leads(session_id);
            CREATE INDEX IF NOT EXISTS idx_leads_source_channel
                ON leads(source_channel);
            -- Composite indexes for lead scoring and analytics hot paths
            CREATE INDEX IF NOT EXISTS idx_leads_lead_id_created
                ON leads(lead_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_leads_vehicle_created
                ON leads(vehicle_id, created_at);
        """)

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a DB row to a public vehicle dict."""
        d = dict(row)
        raw_features = d["features"]
        if raw_features == "[]":
            d["features"] = []
        else:
            try:
                parsed = json.loads(raw_features)
                d["features"] = parsed if isinstance(parsed, list) else []
            except (TypeError, json.JSONDecodeError):
                d["features"] = []
        d["is_featured"] = bool(d.get("is_featured", 0))
        return d

    @staticmethod
    def _as_text(value: Any, default: str = "") -> str:
        if value is None:
            return default
        if isinstance(value, str):
            return value
        return str(value)

    @staticmethod
    def _as_int(value: Any, default: int = 0) -> int:
        if value is None or isinstance(value, bool):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _as_float(value: Any, default: float = 0.0) -> float:
        if value is None or isinstance(value, bool):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _as_optional_float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y"}:
                return True
            if lowered in {"false", "0", "no", "n", ""}:
                return False
        return default

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    @staticmethod
    def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate great-circle distance between two points in miles."""
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        return EARTH_RADIUS_MILES * 2 * math.asin(math.sqrt(a))

    @staticmethod
    def _build_filters(
        *,
        make: str | None = None,
        model: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        body_type: str | None = None,
        fuel_type: str | None = None,
        dealer_location: str | None = None,
        dealer_zip: str | None = None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if make:
            clauses.append("make = ? COLLATE NOCASE")
            params.append(make)
        if model:
            clauses.append("model = ? COLLATE NOCASE")
            params.append(model)
        if year_min is not None:
            clauses.append("year >= ?")
            params.append(year_min)
        if year_max is not None:
            clauses.append("year <= ?")
            params.append(year_max)
        if price_min is not None:
            clauses.append("price >= ?")
            params.append(price_min)
        if price_max is not None:
            clauses.append("price <= ?")
            params.append(price_max)
        if body_type:
            clauses.append("body_type = ? COLLATE NOCASE")
            params.append(body_type)
        if fuel_type:
            clauses.append("fuel_type = ? COLLATE NOCASE")
            params.append(fuel_type)
        if dealer_location:
            clauses.append("dealer_location LIKE ? COLLATE NOCASE")
            params.append(f"%{dealer_location}%")
        if dealer_zip:
            clauses.append("dealer_zip = ?")
            params.append(dealer_zip)

        where = " AND ".join(clauses) if clauses else "1=1"
        return where, params

    @staticmethod
    def _active_inventory_clause(
        *,
        include_sold: bool = False,
        status_column: str = "availability_status",
    ) -> tuple[str, tuple[str, ...]]:
        excluded = (
            _ARCHIVED_STATUSES if include_sold else _HIDDEN_FROM_CUSTOMER_SEARCH_STATUSES
        )
        placeholders = ", ".join("?" for _ in excluded)
        return f"{status_column} NOT IN ({placeholders})", excluded

    @staticmethod
    def _vehicle_to_row(vehicle: dict[str, Any], *, updated_at: str) -> tuple[Any, ...]:
        # Local refs to avoid repeated class attribute lookups (33 calls per row)
        _t = SqliteVehicleStore._as_text
        _i = SqliteVehicleStore._as_int
        _f = SqliteVehicleStore._as_float
        _of = SqliteVehicleStore._as_optional_float
        _b = SqliteVehicleStore._as_bool
        _l = SqliteVehicleStore._as_list
        g = vehicle.get

        now_iso = datetime.now(timezone.utc).isoformat()
        vin = _t(g("vin", "")).upper()

        raw_expires_at = _t(g("expires_at", ""))
        parsed_expires_at = SqliteVehicleStore._parse_iso_datetime(raw_expires_at)
        expires_at = parsed_expires_at.isoformat() if parsed_expires_at is not None else ""
        if not expires_at:
            ttl_days = max(0, _i(g("ttl_days", DEFAULT_TTL_DAYS), DEFAULT_TTL_DAYS))
            expires_at = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()

        return (
            _t(g("id", "")),
            _i(g("year", 0)),
            _t(g("make", "")),
            _t(g("model", "")),
            _t(g("trim", "")),
            _t(g("body_type", "")),
            _f(g("price", 0)),
            _i(g("mileage", 0)),
            _t(g("exterior_color", "")),
            _t(g("interior_color", "")),
            _t(g("fuel_type", "")),
            _i(g("mpg_city", 0)),
            _i(g("mpg_highway", 0)),
            _t(g("engine", "")),
            _t(g("transmission", "")),
            _t(g("drivetrain", "")),
            json.dumps(_l(g("features", []))),
            _i(g("safety_rating", 0)),
            _t(g("dealer_name", "")),
            _t(g("dealer_location", "")),
            _t(g("availability_status", "in_stock")),
            vin,
            _t(g("dealer_zip", "")),
            _of(g("latitude")),
            _of(g("longitude")),
            _t(g("source", "seed"), "seed"),
            _t(g("source_url", "")),
            _t(g("ingested_at", "")) or now_iso,
            expires_at,
            _t(g("last_verified", "")) or now_iso,
            1 if _b(g("is_featured", False)) else 0,
            _i(g("lead_count", 0)),
            updated_at,
        )

    @staticmethod
    def _parse_iso_datetime(value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _days_since(value: str, *, now: datetime) -> tuple[int, bool]:
        parsed = SqliteVehicleStore._parse_iso_datetime(value)
        if parsed is None:
            return 0, True
        delta = now - parsed
        if delta.total_seconds() < 0:
            return 0, False
        return int(delta.total_seconds() // 86_400), False

    @staticmethod
    def _recency_multiplier(age_days: float) -> float:
        return _cip_recency_multiplier(age_days, AUTO_SCORING_CONFIG)

    @staticmethod
    def _lead_score_band(score: float) -> str:
        return _cip_lead_score_band(score, AUTO_SCORING_CONFIG)

    def _lookup_lead_profile_id(
        self,
        *,
        lead_id: str,
        customer_id: str,
        customer_contact: str,
        session_id: str,
    ) -> str | None:
        normalized_lead_id = lead_id.strip()
        normalized_customer_id = customer_id.strip()
        normalized_contact = customer_contact.strip().lower()
        normalized_session_id = session_id.strip()

        if normalized_lead_id:
            row = self._conn.execute(
                """SELECT id, customer_id, customer_contact, session_id
                   FROM lead_profiles
                   WHERE id = ?""",
                (normalized_lead_id,),
            ).fetchone()
            if row:
                # Treat caller-provided lead_id as untrusted unless ownership is verified.
                if (
                    (normalized_customer_id and normalized_customer_id == row["customer_id"])
                    or (normalized_contact and normalized_contact == row["customer_contact"])
                    or (normalized_session_id and normalized_session_id == row["session_id"])
                ):
                    return row["id"]

        if normalized_customer_id:
            row = self._conn.execute(
                """SELECT id FROM lead_profiles
                   WHERE customer_id = ?
                   ORDER BY last_activity_at DESC
                   LIMIT 1""",
                (normalized_customer_id,),
            ).fetchone()
            if row:
                return row[0]

        if normalized_contact:
            row = self._conn.execute(
                """SELECT id FROM lead_profiles
                   WHERE customer_contact = ?
                   ORDER BY last_activity_at DESC
                   LIMIT 1""",
                (normalized_contact,),
            ).fetchone()
            if row:
                return row[0]

        if normalized_session_id:
            row = self._conn.execute(
                """SELECT id FROM lead_profiles
                   WHERE session_id = ?
                   ORDER BY last_activity_at DESC
                   LIMIT 1""",
                (normalized_session_id,),
            ).fetchone()
            if row:
                return row[0]

        return None

    def _resolve_or_create_lead_profile(
        self,
        *,
        vehicle_id: str,
        now_iso: str,
        lead_id: str,
        customer_id: str,
        session_id: str,
        customer_name: str,
        customer_contact: str,
        source_channel: str,
    ) -> str:
        resolved = self._lookup_lead_profile_id(
            lead_id=lead_id,
            customer_id=customer_id,
            customer_contact=customer_contact,
            session_id=session_id,
        )

        normalized_customer_id = customer_id.strip()
        normalized_session_id = session_id.strip()
        normalized_name = customer_name.strip()
        normalized_contact = customer_contact.strip().lower()
        normalized_source = source_channel.strip() or "direct"

        if not resolved:
            resolved = f"leadprof-{uuid.uuid4().hex[:12]}"
            self._conn.execute(
                """INSERT INTO lead_profiles (
                    id, customer_id, session_id, customer_name, customer_contact,
                    status, score, first_seen_at, last_activity_at, last_vehicle_id,
                    source_channel, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    resolved,
                    normalized_customer_id,
                    normalized_session_id,
                    normalized_name,
                    normalized_contact,
                    "new",
                    0.0,
                    now_iso,
                    now_iso,
                    vehicle_id,
                    normalized_source,
                    "",
                ),
            )
            return resolved

        existing = self._conn.execute(
            "SELECT * FROM lead_profiles WHERE id = ?",
            (resolved,),
        ).fetchone()
        if not existing:
            return resolved

        merged_customer_id = normalized_customer_id or existing["customer_id"]
        merged_session_id = normalized_session_id or existing["session_id"]
        merged_name = normalized_name or existing["customer_name"]
        merged_contact = normalized_contact or existing["customer_contact"]
        merged_source = normalized_source or existing["source_channel"]

        self._conn.execute(
            """UPDATE lead_profiles
               SET customer_id = ?, session_id = ?, customer_name = ?, customer_contact = ?,
                   source_channel = ?, last_activity_at = ?, last_vehicle_id = ?
               WHERE id = ?""",
            (
                merged_customer_id,
                merged_session_id,
                merged_name,
                merged_contact,
                merged_source,
                now_iso,
                vehicle_id,
                resolved,
            ),
        )
        return resolved

    def _compute_lead_score(self, *, lead_id: str, now_dt: datetime, days: int = 30) -> float:
        since_iso = (now_dt - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            """SELECT action, created_at
               FROM leads
               WHERE lead_id = ? AND created_at > ?""",
            (lead_id, since_iso),
        ).fetchall()

        score = 0.0
        for row in rows:
            weight = LEAD_SCORE_WEIGHTS.get(row["action"], 0.0)
            if weight <= 0:
                continue
            created_at = self._parse_iso_datetime(row["created_at"])
            if created_at is None:
                continue
            age_days = max(0.0, (now_dt - created_at).total_seconds() / 86_400)
            score += weight * self._recency_multiplier(age_days)
        return round(score, 2)

    def _insert_lead_event(
        self,
        *,
        event_id: str,
        vehicle: dict[str, Any],
        action: str,
        user_query: str,
        created_at: str,
        lead_id: str,
        customer_id: str,
        session_id: str,
        customer_name: str,
        customer_contact: str,
        source_channel: str,
        event_meta: dict[str, Any],
    ) -> None:
        self._conn.execute(
            """INSERT INTO leads
                (
                    id, vehicle_id, vehicle_vin, dealer_name, dealer_zip,
                    action, user_query, created_at, lead_id, customer_id,
                    session_id, customer_name, customer_contact, source_channel,
                    event_meta
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                vehicle.get("id", ""),
                vehicle.get("vin", ""),
                vehicle.get("dealer_name", ""),
                vehicle.get("dealer_zip", ""),
                action,
                user_query,
                created_at,
                lead_id,
                customer_id,
                session_id,
                customer_name,
                customer_contact,
                source_channel,
                json.dumps(event_meta),
            ),
        )

    # ── Public API ─────────────────────────────────────────────────

    def get(self, vehicle_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                f"""SELECT {PUBLIC_COLUMNS} FROM vehicles
                    WHERE id = ? AND availability_status NOT IN (?, ?)""",
                (vehicle_id, *_ARCHIVED_STATUSES),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_many(self, vehicle_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch multiple vehicles in one query.  Returns results in input order, skips missing."""
        if not vehicle_ids:
            return []
        placeholders = ", ".join("?" for _ in vehicle_ids)
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT {PUBLIC_COLUMNS} FROM vehicles
                    WHERE id IN ({placeholders})
                    AND availability_status NOT IN (?, ?)""",
                (*vehicle_ids, *_ARCHIVED_STATUSES),
            ).fetchall()
        by_id = {row["id"]: self._row_to_dict(row) for row in rows}
        return [by_id[vid] for vid in vehicle_ids if vid in by_id]

    def get_by_vin(self, vin: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                f"""SELECT {PUBLIC_COLUMNS} FROM vehicles
                    WHERE vin = ? COLLATE NOCASE AND availability_status NOT IN (?, ?)""",
                (vin.upper(), *_ARCHIVED_STATUSES),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def search(
        self,
        *,
        make: str | None = None,
        model: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        body_type: str | None = None,
        fuel_type: str | None = None,
        dealer_location: str | None = None,
        dealer_zip: str | None = None,
        include_sold: bool = False,
    ) -> list[dict[str, Any]]:
        where, params = self._build_filters(
            make=make,
            model=model,
            year_min=year_min,
            year_max=year_max,
            price_min=price_min,
            price_max=price_max,
            body_type=body_type,
            fuel_type=fuel_type,
            dealer_location=dealer_location,
            dealer_zip=dealer_zip,
        )
        visibility_clause, visibility_params = self._active_inventory_clause(
            include_sold=include_sold
        )
        sql = (
            f"SELECT {PUBLIC_COLUMNS} FROM vehicles "
            f"WHERE {where} AND {visibility_clause} ORDER BY id"
        )  # noqa: S608

        with self._lock:
            rows = self._conn.execute(sql, [*params, *visibility_params]).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search_by_location(
        self,
        *,
        center_lat: float,
        center_lng: float,
        radius_miles: float,
        make: str | None = None,
        model: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        body_type: str | None = None,
        fuel_type: str | None = None,
        max_results: int = 25,
        include_sold: bool = False,
    ) -> list[dict[str, Any]]:
        """Search vehicles within radius using bounding-box pre-filter + Haversine."""
        lat_delta = radius_miles / 69.0
        lng_delta = radius_miles / (69.0 * math.cos(math.radians(center_lat)))

        sql = (
            f"SELECT {PUBLIC_COLUMNS} FROM vehicles"
            " WHERE latitude IS NOT NULL"
            " AND latitude BETWEEN ? AND ?"
            " AND longitude BETWEEN ? AND ?"
        )
        params: list[Any] = [
            center_lat - lat_delta,
            center_lat + lat_delta,
            center_lng - lng_delta,
            center_lng + lng_delta,
        ]

        if make:
            sql += " AND make = ? COLLATE NOCASE"
            params.append(make)
        if model:
            sql += " AND model = ? COLLATE NOCASE"
            params.append(model)
        if year_min is not None:
            sql += " AND year >= ?"
            params.append(year_min)
        if year_max is not None:
            sql += " AND year <= ?"
            params.append(year_max)
        if price_min is not None:
            sql += " AND price >= ?"
            params.append(price_min)
        if price_max is not None:
            sql += " AND price <= ?"
            params.append(price_max)
        if body_type:
            sql += " AND body_type = ? COLLATE NOCASE"
            params.append(body_type)
        if fuel_type:
            sql += " AND fuel_type = ? COLLATE NOCASE"
            params.append(fuel_type)
        visibility_clause, visibility_params = self._active_inventory_clause(
            include_sold=include_sold
        )
        sql += f" AND {visibility_clause}"
        params.extend(visibility_params)

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            vehicle = self._row_to_dict(row)
            dist = self.haversine_miles(
                center_lat, center_lng,
                vehicle["latitude"], vehicle["longitude"],
            )
            if dist <= radius_miles:
                vehicle["distance_miles"] = round(dist, 1)
                results.append(vehicle)

        results.sort(key=lambda v: (v["distance_miles"], v["price"]))
        return results[:max_results]

    def count_filtered(
        self,
        *,
        make: str | None = None,
        model: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        body_type: str | None = None,
        fuel_type: str | None = None,
        dealer_location: str | None = None,
        dealer_zip: str | None = None,
        include_sold: bool = False,
    ) -> int:
        where, params = self._build_filters(
            make=make,
            model=model,
            year_min=year_min,
            year_max=year_max,
            price_min=price_min,
            price_max=price_max,
            body_type=body_type,
            fuel_type=fuel_type,
            dealer_location=dealer_location,
            dealer_zip=dealer_zip,
        )
        visibility_clause, visibility_params = self._active_inventory_clause(
            include_sold=include_sold
        )
        with self._lock:
            row = self._conn.execute(
                f"""SELECT COUNT(*) FROM vehicles
                    WHERE {where} AND {visibility_clause}""",  # noqa: S608
                [*params, *visibility_params],
            ).fetchone()
        return row[0]

    def search_page(
        self,
        *,
        make: str | None = None,
        model: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        body_type: str | None = None,
        fuel_type: str | None = None,
        dealer_location: str | None = None,
        dealer_zip: str | None = None,
        limit: int = 10,
        offset: int = 0,
        include_sold: bool = False,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        where, params = self._build_filters(
            make=make,
            model=model,
            year_min=year_min,
            year_max=year_max,
            price_min=price_min,
            price_max=price_max,
            body_type=body_type,
            fuel_type=fuel_type,
            dealer_location=dealer_location,
            dealer_zip=dealer_zip,
        )
        visibility_clause, visibility_params = self._active_inventory_clause(
            include_sold=include_sold
        )
        sql = (
            f"SELECT {PUBLIC_COLUMNS} FROM vehicles WHERE {where} "
            f"AND {visibility_clause} ORDER BY id LIMIT ? OFFSET ?"
        )  # noqa: S608
        with self._lock:
            rows = self._conn.execute(
                sql, [*params, *visibility_params, limit, offset]
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search_page_with_count(
        self,
        *,
        make: str | None = None,
        model: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        body_type: str | None = None,
        fuel_type: str | None = None,
        dealer_location: str | None = None,
        dealer_zip: str | None = None,
        limit: int = 10,
        offset: int = 0,
        include_sold: bool = False,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Single-query windowed search: returns (total_count, page_rows).

        Uses COUNT(*) OVER() to get total in the same query as the page,
        eliminating the duplicate WHERE clause evaluation.
        """
        if limit <= 0:
            return 0, []

        where, params = self._build_filters(
            make=make,
            model=model,
            year_min=year_min,
            year_max=year_max,
            price_min=price_min,
            price_max=price_max,
            body_type=body_type,
            fuel_type=fuel_type,
            dealer_location=dealer_location,
            dealer_zip=dealer_zip,
        )
        visibility_clause, visibility_params = self._active_inventory_clause(
            include_sold=include_sold
        )
        sql = (
            f"SELECT {PUBLIC_COLUMNS}, COUNT(*) OVER() AS _total "
            f"FROM vehicles WHERE {where} AND {visibility_clause} "
            "ORDER BY id LIMIT ? OFFSET ?"
        )  # noqa: S608
        with self._lock:
            rows = self._conn.execute(
                sql, [*params, *visibility_params, limit, offset]
            ).fetchall()

        if not rows:
            # No rows in page — need separate count for total
            total = self.count_filtered(
                make=make, model=model, year_min=year_min, year_max=year_max,
                price_min=price_min, price_max=price_max, body_type=body_type,
                fuel_type=fuel_type, dealer_location=dealer_location, dealer_zip=dealer_zip,
                include_sold=include_sold,
            )
            return total, []

        total = rows[0]["_total"]
        return total, [self._row_to_dict(r) for r in rows]

    def upsert(self, vehicle: dict[str, Any]) -> None:
        now = self._now()
        with self._lock:
            self._conn.execute(UPSERT_SQL, self._vehicle_to_row(vehicle, updated_at=now))
            self._conn.commit()

    def upsert_many(self, vehicles: list[dict[str, Any]]) -> None:
        if not vehicles:
            return
        now = self._now()
        rows = (self._vehicle_to_row(v, updated_at=now) for v in vehicles)
        with self._lock:
            with self._conn:
                self._conn.executemany(UPSERT_SQL, rows)

    def remove(self, vehicle_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                """UPDATE vehicles
                   SET availability_status = ?, expires_at = ''
                   WHERE id = ? AND availability_status NOT IN (?, ?)""",
                (ARCHIVED_REMOVED_STATUS, vehicle_id, *_ARCHIVED_STATUSES),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def remove_expired(self) -> int:
        """Archive vehicles past their TTL while preserving analytics history."""
        now = self._now()
        visibility_clause, visibility_params = self._active_inventory_clause(
            include_sold=False
        )
        with self._lock:
            cursor = self._conn.execute(
                f"""UPDATE vehicles
                   SET availability_status = ?, expires_at = ''
                   WHERE {visibility_clause}
                     AND expires_at != ''
                     AND julianday(expires_at) IS NOT NULL
                     AND julianday(expires_at) < julianday(?)""",
                (ARCHIVED_REMOVED_STATUS, *visibility_params, now),
            )
            self._conn.commit()
        return cursor.rowcount

    def count(self) -> int:
        visibility_clause, visibility_params = self._active_inventory_clause(
            include_sold=False
        )
        with self._lock:
            row = self._conn.execute(
                f"SELECT COUNT(*) FROM vehicles WHERE {visibility_clause}",
                visibility_params,
            ).fetchone()
        return row[0]

    def get_stats(self) -> dict[str, Any]:
        """Comprehensive inventory analytics."""
        visibility_clause, visibility_params = self._active_inventory_clause(
            include_sold=False
        )
        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) FROM vehicles WHERE {visibility_clause}",
                visibility_params,
            ).fetchone()[0]

            expired_count = self._conn.execute(
                f"""SELECT COUNT(*) FROM vehicles
                   WHERE {visibility_clause}
                     AND expires_at != ''
                     AND julianday(expires_at) IS NOT NULL
                     AND julianday(expires_at) < julianday(?)""",
                (*visibility_params, self._now()),
            ).fetchone()[0]

            source_counts = dict(self._conn.execute(
                f"""SELECT source, COUNT(*) FROM vehicles
                   WHERE {visibility_clause}
                   GROUP BY source""",
                visibility_params,
            ).fetchall())

            metro_counts = dict(self._conn.execute(
                "SELECT dealer_location, COUNT(*) FROM vehicles "
                f"WHERE {visibility_clause} AND dealer_location != '' "
                "GROUP BY dealer_location",
                visibility_params,
            ).fetchall())

            price_stats = self._conn.execute(
                """SELECT
                    MIN(price), MAX(price), AVG(price),
                    SUM(CASE WHEN price < 20000 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN price BETWEEN 20000 AND 40000 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN price > 40000 THEN 1 ELSE 0 END)
                FROM vehicles"""
                f" WHERE {visibility_clause}",
                visibility_params,
            ).fetchone()

            lead_stats = self._conn.execute(
                """SELECT
                    COUNT(*),
                    COUNT(DISTINCT vehicle_id),
                    COUNT(DISTINCT dealer_zip)
                FROM leads"""
            ).fetchone()

            freshness = self._conn.execute(
                """SELECT
                    AVG(julianday('now') - julianday(ingested_at)),
                    MAX(julianday('now') - julianday(ingested_at))
                FROM vehicles
                """
                f"WHERE {visibility_clause} AND ingested_at != ''",
                visibility_params,
            ).fetchone()

        return {
            "total_vehicles": total,
            "expired_vehicles": expired_count,
            "by_source": source_counts,
            "by_metro": metro_counts,
            "price_range": {
                "min": price_stats[0],
                "max": price_stats[1],
                "avg": round(price_stats[2], 2) if price_stats[2] else 0,
            },
            "price_distribution": {
                "under_20k": price_stats[3] or 0,
                "20k_to_40k": price_stats[4] or 0,
                "over_40k": price_stats[5] or 0,
            },
            "leads": {
                "total": lead_stats[0] or 0,
                "unique_vehicles": lead_stats[1] or 0,
                "dealers_reached": lead_stats[2] or 0,
            },
            "freshness_days": {
                "average": round(freshness[0] or 0, 1),
                "oldest": round(freshness[1] or 0, 1),
            },
        }

    def record_lead(
        self,
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
        """Record a lead event and stitch it into a lead profile."""
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        normalized_source = source_channel.strip() or "direct"
        normalized_customer_id = customer_id.strip()
        normalized_session_id = session_id.strip()
        normalized_customer_name = customer_name.strip()
        normalized_customer_contact = customer_contact.strip().lower()
        resolved_event_meta = event_meta if isinstance(event_meta, dict) else {}
        visibility_clause, visibility_params = self._active_inventory_clause(
            include_sold=False
        )

        # Single lock acquisition for the entire operation (vehicle lookup + lead insert + score)
        with self._lock:
            row = self._conn.execute(
                f"""SELECT {PUBLIC_COLUMNS} FROM vehicles
                    WHERE id = ? AND {visibility_clause}""",
                (vehicle_id, *visibility_params),
            ).fetchone()
            if not row:
                raise ValueError(f"Vehicle {vehicle_id} not found")
            vehicle = self._row_to_dict(row)

            resolved_lead_id = self._resolve_or_create_lead_profile(
                vehicle_id=vehicle_id,
                now_iso=now_iso,
                lead_id=lead_id,
                customer_id=normalized_customer_id,
                session_id=normalized_session_id,
                customer_name=normalized_customer_name,
                customer_contact=normalized_customer_contact,
                source_channel=normalized_source,
            )

            event_id = f"lead-{uuid.uuid4().hex[:12]}"
            self._insert_lead_event(
                event_id=event_id,
                vehicle=vehicle,
                action=action,
                user_query=user_query,
                created_at=now_iso,
                lead_id=resolved_lead_id,
                customer_id=normalized_customer_id,
                session_id=normalized_session_id,
                customer_name=normalized_customer_name,
                customer_contact=normalized_customer_contact,
                source_channel=normalized_source,
                event_meta=resolved_event_meta,
            )
            self._conn.execute(
                "UPDATE vehicles SET lead_count = lead_count + 1 WHERE id = ?",
                (vehicle_id,),
            )

            score = self._compute_lead_score(lead_id=resolved_lead_id, now_dt=now_dt)
            existing_profile = self._conn.execute(
                "SELECT status FROM lead_profiles WHERE id = ?",
                (resolved_lead_id,),
            ).fetchone()
            existing_status = existing_profile["status"] if existing_profile else "new"
            if existing_status in {"won", "lost"}:
                next_status = existing_status
            elif score >= 22:
                next_status = "qualified"
            elif score >= 10:
                next_status = "engaged"
            else:
                next_status = "new"

            self._conn.execute(
                """UPDATE lead_profiles
                   SET score = ?, status = ?, last_activity_at = ?, last_vehicle_id = ?
                   WHERE id = ?""",
                (score, next_status, now_iso, vehicle_id, resolved_lead_id),
            )
            self._conn.commit()

            # Escalation detection — fire if a threshold was crossed.
            if self._escalation_store is not None and existing_status != next_status:
                from auto_mcp.escalation.detector import check_escalation

                esc = check_escalation(
                    lead_id=resolved_lead_id,
                    old_status=existing_status,
                    new_status=next_status,
                    score=score,
                    vehicle_id=vehicle_id,
                    customer_name=normalized_customer_name,
                    customer_contact=normalized_customer_contact,
                    source_channel=normalized_source,
                    action=action,
                )
                if esc and not self._escalation_store.has_active_escalation(
                    resolved_lead_id, esc["escalation_type"]
                ):
                    self._escalation_store.save(esc)

        return resolved_lead_id

    def get_lead_analytics(self, days: int = 30) -> dict[str, Any]:
        """Lead analytics for reporting."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        with self._lock:
            actions = dict(self._conn.execute(
                "SELECT action, COUNT(*) FROM leads WHERE created_at > ? GROUP BY action",
                (since,),
            ).fetchall())

            top_vehicles = self._conn.execute(
                """SELECT vehicle_vin, dealer_name, COUNT(*) as cnt
                FROM leads WHERE created_at > ?
                GROUP BY vehicle_vin ORDER BY cnt DESC LIMIT 10""",
                (since,),
            ).fetchall()

            top_dealers = self._conn.execute(
                """SELECT dealer_name, dealer_zip, COUNT(*) as cnt
                FROM leads WHERE created_at > ?
                GROUP BY dealer_name, dealer_zip
                ORDER BY cnt DESC LIMIT 10""",
                (since,),
            ).fetchall()

            daily = self._conn.execute(
                """SELECT date(created_at) as day, COUNT(*) as cnt
                FROM leads WHERE created_at > ?
                GROUP BY day ORDER BY day""",
                (since,),
            ).fetchall()

        return {
            "period_days": days,
            "total_leads": sum(actions.values()) if actions else 0,
            "actions": actions,
            "top_vehicles": [
                {"vin": r[0], "dealer": r[1], "leads": r[2]} for r in top_vehicles
            ],
            "top_dealers": [
                {"name": r[0], "zip": r[1], "leads": r[2]} for r in top_dealers
            ],
            "daily_trend": [
                {"date": r[0], "count": r[1]} for r in daily
            ],
        }

    def get_hot_leads(
        self,
        *,
        limit: int = 10,
        min_score: float = 10.0,
        dealer_zip: str = "",
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Return highest-intent lead profiles ranked by score."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        with self._lock:
            rows = self._conn.execute(
                """SELECT lp.*,
                          v.dealer_zip AS vehicle_dealer_zip,
                          v.dealer_name AS vehicle_dealer_name
                   FROM lead_profiles lp
                   LEFT JOIN vehicles v ON v.id = lp.last_vehicle_id
                   WHERE lp.score >= ?
                     AND lp.last_activity_at > ?
                     AND (? = '' OR COALESCE(v.dealer_zip, '') = ?)
                   ORDER BY lp.score DESC, lp.last_activity_at DESC
                   LIMIT ?""",
                (min_score, since, dealer_zip, dealer_zip, limit),
            ).fetchall()

            if not rows:
                return []

            # Batch sub-queries: fetch all lead actions and vehicles for all leads at once
            # instead of 2 queries per lead (N+1 → 2 queries total).
            lead_ids = [row["id"] for row in rows]
            placeholders = ",".join("?" for _ in lead_ids)

            all_actions = self._conn.execute(
                f"""SELECT lead_id, action, COUNT(*) as cnt
                    FROM leads
                    WHERE lead_id IN ({placeholders}) AND created_at > ?
                    GROUP BY lead_id, action
                    ORDER BY lead_id, cnt DESC, action ASC""",
                [*lead_ids, since],
            ).fetchall()

            all_vehicles = self._conn.execute(
                f"""SELECT lead_id, vehicle_id, COUNT(*) as cnt
                    FROM leads
                    WHERE lead_id IN ({placeholders}) AND created_at > ?
                    GROUP BY lead_id, vehicle_id
                    ORDER BY lead_id, cnt DESC, vehicle_id ASC""",
                [*lead_ids, since],
            ).fetchall()

        # Dict assembly outside the lock — data is already fetched
        actions_by_lead: dict[str, list[dict[str, Any]]] = {}
        for item in all_actions:
            actions_by_lead.setdefault(item["lead_id"], []).append(
                {"action": item["action"], "count": item["cnt"]}
            )
        vehicles_by_lead: dict[str, list[dict[str, Any]]] = {}
        for item in all_vehicles:
            vehicles_by_lead.setdefault(item["lead_id"], []).append(
                {"vehicle_id": item["vehicle_id"], "count": item["cnt"]}
            )

        hot_leads: list[dict[str, Any]] = []
        for row in rows:
            lid = row["id"]
            hot_leads.append(
                {
                    "lead_id": lid,
                    "customer_name": row["customer_name"],
                    "customer_contact": row["customer_contact"],
                    "status": row["status"],
                    "score": round(float(row["score"]), 2),
                    "score_band": self._lead_score_band(float(row["score"])),
                    "last_activity_at": row["last_activity_at"],
                    "last_vehicle_id": row["last_vehicle_id"],
                    "dealer_zip": row["vehicle_dealer_zip"] or "",
                    "dealer_name": row["vehicle_dealer_name"] or "",
                    "top_actions": actions_by_lead.get(lid, [])[:3],
                    "top_vehicles": vehicles_by_lead.get(lid, [])[:3],
                }
            )

        return hot_leads

    def get_lead_detail(self, lead_id: str, *, days: int = 90) -> dict[str, Any] | None:
        """Return a lead profile plus event timeline and scoring breakdown."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        now_dt = datetime.now(timezone.utc)

        with self._lock:
            profile = self._conn.execute(
                "SELECT * FROM lead_profiles WHERE id = ?",
                (lead_id,),
            ).fetchone()
            if not profile:
                return None

            events = self._conn.execute(
                """SELECT id, vehicle_id, action, user_query,
                          created_at, source_channel, event_meta
                   FROM leads
                   WHERE lead_id = ? AND created_at > ?
                   ORDER BY created_at DESC
                   LIMIT 250""",
                (lead_id, since),
            ).fetchall()

        score_by_action: dict[str, float] = {}
        action_counts: dict[str, int] = {}
        recent_signal_counts: dict[str, int] = {}
        timeline: list[dict[str, Any]] = []

        for event in events:
            created_at = self._parse_iso_datetime(event["created_at"])
            if created_at:
                age_days = max(0.0, (now_dt - created_at).total_seconds() / 86_400)
            else:
                age_days = 999.0
            action = event["action"]

            weight = LEAD_SCORE_WEIGHTS.get(action, 0.0)
            contribution = weight * self._recency_multiplier(age_days)
            score_by_action[action] = round(score_by_action.get(action, 0.0) + contribution, 2)
            action_counts[action] = action_counts.get(action, 0) + 1

            if age_days <= 7:
                recent_signal_counts[action] = recent_signal_counts.get(action, 0) + 1

            event_meta: dict[str, Any] = {}
            try:
                loaded_meta = json.loads(event["event_meta"] or "{}")
                if isinstance(loaded_meta, dict):
                    event_meta = loaded_meta
            except json.JSONDecodeError:
                event_meta = {}

            timeline.append(
                {
                    "event_id": event["id"],
                    "vehicle_id": event["vehicle_id"],
                    "action": action,
                    "user_query": event["user_query"],
                    "created_at": event["created_at"],
                    "source_channel": event["source_channel"],
                    "event_meta": event_meta,
                }
            )

        recent_intent_signals = sorted(
            (
                {"action": action, "count": count}
                for action, count in recent_signal_counts.items()
            ),
            key=lambda item: (-item["count"], item["action"]),
        )

        return {
            "profile": {
                "lead_id": profile["id"],
                "customer_id": profile["customer_id"],
                "session_id": profile["session_id"],
                "customer_name": profile["customer_name"],
                "customer_contact": profile["customer_contact"],
                "status": profile["status"],
                "score": round(float(profile["score"]), 2),
                "score_band": self._lead_score_band(float(profile["score"])),
                "first_seen_at": profile["first_seen_at"],
                "last_activity_at": profile["last_activity_at"],
                "last_vehicle_id": profile["last_vehicle_id"],
                "source_channel": profile["source_channel"],
            },
            "timeline": timeline,
            "score_breakdown": {
                "by_action": score_by_action,
                "action_counts": action_counts,
                "total_score": round(float(profile["score"]), 2),
            },
            "recent_intent_signals": recent_intent_signals,
        }

    def get_inventory_aging_report(
        self,
        *,
        min_days_on_lot: int = 30,
        limit: int = 100,
        dealer_zip: str = "",
    ) -> dict[str, Any]:
        """Return unit-level and body-type aging metrics."""
        now_dt = datetime.now(timezone.utc)
        since_7d = (now_dt - timedelta(days=7)).isoformat()
        since_30d = (now_dt - timedelta(days=30)).isoformat()
        visibility_clause, visibility_params = self._active_inventory_clause(
            include_sold=False,
            status_column="v.availability_status",
        )

        # Single LEFT JOIN query instead of 2 separate queries + Python-side dict merge
        with self._lock:
            if dealer_zip:
                zip_clause = f"WHERE {visibility_clause} AND v.dealer_zip = ?"
                zip_params = [*visibility_params, dealer_zip]
            else:
                zip_clause = f"WHERE {visibility_clause}"
                zip_params = [*visibility_params]
            rows = self._conn.execute(
                f"""SELECT v.id, v.year, v.make, v.model, v.trim, v.body_type,
                          v.price, v.mileage, v.dealer_name, v.dealer_zip,
                          v.availability_status, v.ingested_at, v.updated_at,
                          COALESCE(ls.leads_7d, 0) AS leads_7d,
                          COALESCE(ls.leads_30d, 0) AS leads_30d
                   FROM vehicles v
                   LEFT JOIN (
                       SELECT vehicle_id,
                              SUM(CASE WHEN created_at > ? THEN 1 ELSE 0 END) AS leads_7d,
                              COUNT(*) AS leads_30d
                       FROM leads
                       WHERE created_at > ?
                       GROUP BY vehicle_id
                   ) ls ON ls.vehicle_id = v.id
                   {zip_clause}""",
                [since_7d, since_30d, *zip_params],
            ).fetchall()

        units: list[dict[str, Any]] = []
        summary_by_body: dict[str, dict[str, Any]] = {}
        for row in rows:
            age_days, unknown_age = self._days_since(row["ingested_at"], now=now_dt)
            if unknown_age:
                age_days, unknown_age = self._days_since(row["updated_at"], now=now_dt)

            leads_7d = int(row["leads_7d"])
            leads_30d = int(row["leads_30d"])
            if leads_7d >= 5:
                velocity = "high"
            elif leads_7d >= 2:
                velocity = "medium"
            else:
                velocity = "low"

            stale = age_days >= min_days_on_lot
            body_key = row["body_type"] or "unknown"
            summary = summary_by_body.setdefault(
                body_key,
                {
                    "body_type": body_key,
                    "vehicle_count": 0,
                    "days_on_lot_values": [],
                    "stale_count": 0,
                    "low_velocity_count": 0,
                },
            )
            summary["vehicle_count"] += 1
            if not unknown_age:
                summary["days_on_lot_values"].append(age_days)
            if stale:
                summary["stale_count"] += 1
            if velocity == "low":
                summary["low_velocity_count"] += 1

            units.append(
                {
                    "vehicle_id": row["id"],
                    "vehicle_summary": (
                        f"{row['year']} {row['make']} {row['model']} {row['trim']}".strip()
                    ),
                    "body_type": row["body_type"],
                    "dealer_name": row["dealer_name"],
                    "dealer_zip": row["dealer_zip"],
                    "price": row["price"],
                    "availability_status": row["availability_status"],
                    "days_on_lot": age_days,
                    "unknown_age": unknown_age,
                    "stale": stale,
                    "leads_7d": leads_7d,
                    "leads_30d": leads_30d,
                    "velocity_bucket": velocity,
                }
            )

        units.sort(
            key=lambda unit: (
                unit["unknown_age"],
                -unit["days_on_lot"],
                unit["vehicle_id"],
            )
        )
        unit_rows = units[:limit]

        summary_rows: list[dict[str, Any]] = []
        for summary in sorted(summary_by_body.values(), key=lambda item: item["body_type"]):
            values = summary.pop("days_on_lot_values")
            summary_rows.append(
                {
                    **summary,
                    "median_days_on_lot": round(float(median(values)), 1) if values else 0.0,
                }
            )

        return {
            "filters": {
                "min_days_on_lot": min_days_on_lot,
                "limit": limit,
                "dealer_zip": dealer_zip,
            },
            "total_units_considered": len(units),
            "unit_rows": unit_rows,
            "summary_by_body_type": summary_rows,
        }

    def get_pricing_opportunities(
        self,
        *,
        limit: int = 25,
        stale_days_threshold: int = 45,
        overpriced_threshold_pct: float = 5.0,
        underpriced_threshold_pct: float = -5.0,
    ) -> dict[str, Any]:
        """Return market-position opportunities for unit pricing actions."""
        now_dt = datetime.now(timezone.utc)
        since_7d = (now_dt - timedelta(days=7)).isoformat()
        since_30d = (now_dt - timedelta(days=30)).isoformat()
        visibility_clause, visibility_params = self._active_inventory_clause(
            include_sold=False
        )

        with self._lock:
            rows = self._conn.execute(
                """SELECT id, year, make, model, trim, body_type, fuel_type, price,
                          dealer_name, dealer_zip, ingested_at, updated_at
                   FROM vehicles
                   WHERE """
                f"{visibility_clause}",
                visibility_params,
            ).fetchall()
            lead_rows = self._conn.execute(
                """SELECT vehicle_id,
                          SUM(CASE WHEN created_at > ? THEN 1 ELSE 0 END) AS leads_7d,
                          SUM(CASE WHEN created_at > ? THEN 1 ELSE 0 END) AS leads_30d
                   FROM leads
                   GROUP BY vehicle_id""",
                (since_7d, since_30d),
            ).fetchall()

        vehicles = [dict(row) for row in rows]
        lead_map = {
            row["vehicle_id"]: {
                "leads_7d": int(row["leads_7d"] or 0),
                "leads_30d": int(row["leads_30d"] or 0),
            }
            for row in lead_rows
        }

        # Pre-group peer prices by (make, model) and (body_type, fuel_type) for O(n) lookup
        # instead of O(n²) inner loop per vehicle.
        _peer_by_mm: dict[tuple[str, str], list[tuple[str, float]]] = {}
        _peer_by_bf: dict[tuple[str, str], list[tuple[str, float]]] = {}
        for v in vehicles:
            mm_key = (v["make"].lower(), v["model"].lower())
            bf_key = (v["body_type"].lower(), v["fuel_type"].lower())
            _peer_by_mm.setdefault(mm_key, []).append((v["id"], float(v["price"])))
            _peer_by_bf.setdefault(bf_key, []).append((v["id"], float(v["price"])))

        opportunities: list[dict[str, Any]] = []
        for vehicle in vehicles:
            age_days, unknown_age = self._days_since(vehicle["ingested_at"], now=now_dt)
            if unknown_age:
                age_days, unknown_age = self._days_since(vehicle["updated_at"], now=now_dt)

            vid = vehicle["id"]
            mm_key = (vehicle["make"].lower(), vehicle["model"].lower())
            peers_primary = [p for pid, p in _peer_by_mm.get(mm_key, []) if pid != vid]
            if peers_primary:
                peer_prices = peers_primary
                peer_basis = "make_model"
            else:
                bf_key = (vehicle["body_type"].lower(), vehicle["fuel_type"].lower())
                peer_prices = [p for pid, p in _peer_by_bf.get(bf_key, []) if pid != vid]
                peer_basis = "body_fuel"

            market_median = float(median(peer_prices)) if peer_prices else 0.0
            price_delta_pct = (
                ((float(vehicle["price"]) - market_median) / market_median) * 100
                if market_median > 0
                else 0.0
            )

            lead_stats = lead_map.get(vehicle["id"], {"leads_7d": 0, "leads_30d": 0})
            leads_7d = lead_stats["leads_7d"]
            leads_30d = lead_stats["leads_30d"]
            if leads_7d >= 5:
                velocity = "high"
            elif leads_7d >= 2:
                velocity = "medium"
            else:
                velocity = "low"

            flags: list[str] = []
            if age_days >= stale_days_threshold:
                flags.append("stale")
            if market_median > 0 and price_delta_pct >= overpriced_threshold_pct:
                flags.append("overpriced")
            if market_median > 0 and price_delta_pct <= underpriced_threshold_pct:
                flags.append("underpriced")

            if not flags:
                continue

            if "overpriced" in flags:
                recommendation = "reprice_down"
            elif "stale" in flags and velocity == "low":
                recommendation = "promote_listing"
            else:
                recommendation = "hold_price"

            opportunities.append(
                {
                    "vehicle_id": vehicle["id"],
                    "vehicle_summary": (
                        f"{vehicle['year']} {vehicle['make']} {vehicle['model']} "
                        f"{vehicle['trim']}"
                    ).strip(),
                    "dealer_name": vehicle["dealer_name"],
                    "dealer_zip": vehicle["dealer_zip"],
                    "price": float(vehicle["price"]),
                    "market_median_price": round(market_median, 2),
                    "price_delta_percent": round(price_delta_pct, 2),
                    "peer_basis": peer_basis,
                    "peer_count": len(peer_prices),
                    "days_on_lot": age_days,
                    "unknown_age": unknown_age,
                    "leads_7d": leads_7d,
                    "leads_30d": leads_30d,
                    "velocity_bucket": velocity,
                    "flags": flags,
                    "recommendation": recommendation,
                }
            )

        priority_rank = {
            "reprice_down": 0,
            "promote_listing": 1,
            "hold_price": 2,
        }
        opportunities.sort(
            key=lambda item: (
                priority_rank.get(item["recommendation"], 3),
                -abs(float(item["price_delta_percent"])),
                -int(item["days_on_lot"]),
                item["vehicle_id"],
            )
        )

        summary = {
            "reprice_down": 0,
            "promote_listing": 0,
            "hold_price": 0,
            "stale": 0,
            "overpriced": 0,
            "underpriced": 0,
        }
        for item in opportunities:
            summary[item["recommendation"]] += 1
            for flag in item["flags"]:
                if flag in summary:
                    summary[flag] += 1

        return {
            "filters": {
                "limit": limit,
                "stale_days_threshold": stale_days_threshold,
                "overpriced_threshold_pct": overpriced_threshold_pct,
                "underpriced_threshold_pct": underpriced_threshold_pct,
            },
            "total_opportunities": len(opportunities),
            "summary": summary,
            "opportunities": opportunities[:limit],
        }

    def record_sale(
        self,
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
        """Persist a sale outcome and mark inventory status accordingly."""
        sold_at_parsed = self._parse_iso_datetime(sold_at)
        if sold_at_parsed is None:
            raise ValueError("sold_at must be a valid ISO-8601 datetime string")

        vehicle = self.get(vehicle_id)
        if not vehicle:
            raise ValueError(f"Vehicle {vehicle_id} not found")

        if sold_price < 0:
            raise ValueError("sold_price must be greater than or equal to 0")

        sale_id = f"sale-{uuid.uuid4().hex[:12]}"
        now_iso = self._now()
        normalized_source = source_channel.strip() or "direct"
        normalized_lead_id = lead_id.strip()
        normalized_salesperson = salesperson_id.strip()
        resolved_metadata = metadata if isinstance(metadata, dict) else {}

        with self._lock:
            self._conn.execute(
                """INSERT INTO sales (
                    id, vehicle_id, lead_id, dealer_name, dealer_zip, sold_price, listed_price,
                    source_channel, salesperson_id, sold_at, recorded_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sale_id,
                    vehicle_id,
                    normalized_lead_id,
                    vehicle.get("dealer_name", ""),
                    vehicle.get("dealer_zip", ""),
                    float(sold_price),
                    float(vehicle.get("price", 0)),
                    normalized_source,
                    normalized_salesperson,
                    sold_at_parsed.isoformat(),
                    now_iso,
                    json.dumps(resolved_metadata),
                ),
            )

            self._conn.execute(
                "UPDATE vehicles SET availability_status = 'sold' WHERE id = ?",
                (vehicle_id,),
            )

            if normalized_lead_id:
                self._conn.execute(
                    """UPDATE lead_profiles
                       SET status = 'won', last_activity_at = ?, last_vehicle_id = ?
                       WHERE id = ?""",
                    (now_iso, vehicle_id, normalized_lead_id),
                )

            self._insert_lead_event(
                event_id=f"lead-{uuid.uuid4().hex[:12]}",
                vehicle=vehicle,
                action="sale_closed",
                user_query="Sale recorded",
                created_at=now_iso,
                lead_id=normalized_lead_id,
                customer_id="",
                session_id="",
                customer_name="",
                customer_contact="",
                source_channel=normalized_source,
                event_meta={"sale_id": sale_id, "sold_price": float(sold_price)},
            )

            if keep_vehicle_record is False:
                # Keep row for lead-FK integrity while hiding it from active inventory.
                self._conn.execute(
                    """UPDATE vehicles
                       SET availability_status = ?, expires_at = ''
                       WHERE id = ?""",
                    (ARCHIVED_SOLD_STATUS, vehicle_id),
                )

            self._conn.commit()

        return {
            "sale_id": sale_id,
            "vehicle_id": vehicle_id,
            "lead_id": normalized_lead_id,
            "sold_price": round(float(sold_price), 2),
            "listed_price": round(float(vehicle.get("price", 0)), 2),
            "sold_at": sold_at_parsed.isoformat(),
            "source_channel": normalized_source,
            "salesperson_id": normalized_salesperson,
            "vehicle_record_kept": keep_vehicle_record,
        }

    def get_funnel_metrics(
        self,
        *,
        days: int = 30,
        dealer_zip: str = "",
        breakdown_by: str = "none",
    ) -> dict[str, Any]:
        """Compute stage counts and conversion rates from lead events and sales."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        normalized_breakdown = breakdown_by.strip().lower()
        if normalized_breakdown not in {"none", "source_channel"}:
            normalized_breakdown = "none"

        stage_order = ("discovery", "consideration", "financial", "intent", "outcome")
        stage_actions = FUNNEL_STAGE_ACTIONS

        with self._lock:
            if dealer_zip:
                event_rows = self._conn.execute(
                    """SELECT lead_id, action, source_channel
                       FROM leads
                       WHERE created_at > ? AND dealer_zip = ?""",
                    (since, dealer_zip),
                ).fetchall()
                sales_rows = self._conn.execute(
                    """SELECT lead_id, source_channel, sold_price
                       FROM sales
                       WHERE sold_at > ? AND dealer_zip = ?""",
                    (since, dealer_zip),
                ).fetchall()
            else:
                event_rows = self._conn.execute(
                    """SELECT lead_id, action, source_channel
                       FROM leads
                       WHERE created_at > ?""",
                    (since,),
                ).fetchall()
                sales_rows = self._conn.execute(
                    """SELECT lead_id, source_channel, sold_price
                       FROM sales
                       WHERE sold_at > ?""",
                    (since,),
                ).fetchall()

        all_channels = {row["source_channel"] or "direct" for row in event_rows}
        all_channels.update({row["source_channel"] or "direct" for row in sales_rows})
        channels = sorted(all_channels) if normalized_breakdown == "source_channel" else ["all"]

        def _init_channel_bucket() -> dict[str, Any]:
            return {
                "lead_actions": {},
                "sales_count": 0,
                "revenue": 0.0,
            }

        channel_data: dict[str, dict[str, Any]] = {
            channel: _init_channel_bucket() for channel in channels
        }
        if "all" not in channel_data:
            channel_data["all"] = _init_channel_bucket()

        for row in event_rows:
            lead_key = row["lead_id"] or ""
            if not lead_key:
                continue
            channel = row["source_channel"] or "direct"
            action = row["action"]
            channel_targets = [channel, "all"] if channel in channel_data else ["all"]
            for target in channel_targets:
                actions = channel_data[target]["lead_actions"].setdefault(lead_key, set())
                actions.add(action)

        for row in sales_rows:
            channel = row["source_channel"] or "direct"
            channel_targets = [channel, "all"] if channel in channel_data else ["all"]
            for target in channel_targets:
                channel_data[target]["sales_count"] += 1
                channel_data[target]["revenue"] += float(row["sold_price"] or 0.0)

        def _stage_counts(actions_by_lead: dict[str, set[str]]) -> dict[str, int]:
            counts: dict[str, int] = {}
            for stage in stage_order:
                actions = stage_actions[stage]
                counts[stage] = sum(
                    1 for lead_actions in actions_by_lead.values()
                    if any(action in lead_actions for action in actions)
                )
            return counts

        def _conversion_rates(counts: dict[str, int]) -> dict[str, float]:
            conversions: dict[str, float] = {}
            pairs = [
                ("discovery", "consideration"),
                ("consideration", "financial"),
                ("financial", "intent"),
                ("intent", "outcome"),
            ]
            for source_stage, target_stage in pairs:
                source_count = counts[source_stage]
                target_count = counts[target_stage]
                if source_count <= 0:
                    conversions[f"{source_stage}_to_{target_stage}"] = 0.0
                else:
                    conversions[f"{source_stage}_to_{target_stage}"] = round(
                        (target_count / source_count) * 100,
                        2,
                    )
            return conversions

        breakdown: dict[str, Any] = {}
        for channel, details in channel_data.items():
            if normalized_breakdown != "source_channel" and channel != "all":
                continue

            counts = _stage_counts(details["lead_actions"])
            breakdown[channel] = {
                "stage_counts": counts,
                "conversions_pct": _conversion_rates(counts),
                "sales_count": details["sales_count"],
                "sold_revenue": round(details["revenue"], 2),
            }

        overall = breakdown.get("all", {})
        return {
            "period_days": days,
            "dealer_zip": dealer_zip,
            "breakdown_by": normalized_breakdown,
            "overall": overall,
            "breakdown": (
                {
                    key: value
                    for key, value in breakdown.items()
                    if key != "all"
                }
                if normalized_breakdown == "source_channel"
                else {}
            ),
        }
