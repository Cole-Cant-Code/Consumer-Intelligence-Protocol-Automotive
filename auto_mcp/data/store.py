"""VehicleStore protocol and SQLite implementation for live inventory."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import (
    Any,
    Protocol,
    runtime_checkable,
)

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
    ) -> list[dict[str, Any]]: ...
    def upsert(self, vehicle: dict[str, Any]) -> None: ...
    def upsert_many(self, vehicles: list[dict[str, Any]]) -> None: ...
    def remove(self, vehicle_id: str) -> bool: ...
    def remove_expired(self) -> int: ...
    def count(self) -> int: ...
    def get_stats(self) -> dict[str, Any]: ...
    def record_lead(self, vehicle_id: str, action: str, user_query: str = "") -> str: ...
    def get_lead_analytics(self, days: int = 30) -> dict[str, Any]: ...


class SqliteVehicleStore:
    """SQLite-backed vehicle store with WAL mode and NOCASE indexes."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute("PRAGMA cache_size=-20000")
            self._create_schema()

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
    def _vehicle_to_row(vehicle: dict[str, Any], *, updated_at: str) -> tuple[Any, ...]:
        now_iso = datetime.now(timezone.utc).isoformat()
        vin = SqliteVehicleStore._as_text(vehicle.get("vin", "")).upper()

        expires_at = vehicle.get("expires_at", "")
        if not expires_at:
            ttl_days = max(
                0,
                SqliteVehicleStore._as_int(
                    vehicle.get("ttl_days", DEFAULT_TTL_DAYS),
                    DEFAULT_TTL_DAYS,
                ),
            )
            expires_at = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()

        return (
            SqliteVehicleStore._as_text(vehicle.get("id", "")),
            SqliteVehicleStore._as_int(vehicle.get("year", 0)),
            SqliteVehicleStore._as_text(vehicle.get("make", "")),
            SqliteVehicleStore._as_text(vehicle.get("model", "")),
            SqliteVehicleStore._as_text(vehicle.get("trim", "")),
            SqliteVehicleStore._as_text(vehicle.get("body_type", "")),
            SqliteVehicleStore._as_float(vehicle.get("price", 0)),
            SqliteVehicleStore._as_int(vehicle.get("mileage", 0)),
            SqliteVehicleStore._as_text(vehicle.get("exterior_color", "")),
            SqliteVehicleStore._as_text(vehicle.get("interior_color", "")),
            SqliteVehicleStore._as_text(vehicle.get("fuel_type", "")),
            SqliteVehicleStore._as_int(vehicle.get("mpg_city", 0)),
            SqliteVehicleStore._as_int(vehicle.get("mpg_highway", 0)),
            SqliteVehicleStore._as_text(vehicle.get("engine", "")),
            SqliteVehicleStore._as_text(vehicle.get("transmission", "")),
            SqliteVehicleStore._as_text(vehicle.get("drivetrain", "")),
            json.dumps(SqliteVehicleStore._as_list(vehicle.get("features", []))),
            SqliteVehicleStore._as_int(vehicle.get("safety_rating", 0)),
            SqliteVehicleStore._as_text(vehicle.get("dealer_name", "")),
            SqliteVehicleStore._as_text(vehicle.get("dealer_location", "")),
            SqliteVehicleStore._as_text(vehicle.get("availability_status", "in_stock")),
            vin,
            # New geo fields
            SqliteVehicleStore._as_text(vehicle.get("dealer_zip", "")),
            SqliteVehicleStore._as_optional_float(vehicle.get("latitude")),
            SqliteVehicleStore._as_optional_float(vehicle.get("longitude")),
            # Source tracking
            SqliteVehicleStore._as_text(vehicle.get("source", "seed"), "seed"),
            SqliteVehicleStore._as_text(vehicle.get("source_url", "")),
            # TTL fields
            SqliteVehicleStore._as_text(vehicle.get("ingested_at", "")) or now_iso,
            expires_at,
            SqliteVehicleStore._as_text(vehicle.get("last_verified", "")) or now_iso,
            # Platform
            1 if SqliteVehicleStore._as_bool(vehicle.get("is_featured", False)) else 0,
            SqliteVehicleStore._as_int(vehicle.get("lead_count", 0)),
            updated_at,
        )

    # ── Public API ─────────────────────────────────────────────────

    def get(self, vehicle_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {PUBLIC_COLUMNS} FROM vehicles WHERE id = ?", (vehicle_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_by_vin(self, vin: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {PUBLIC_COLUMNS} FROM vehicles WHERE vin = ? COLLATE NOCASE",
                (vin.upper(),),
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
        sql = f"SELECT {PUBLIC_COLUMNS} FROM vehicles WHERE {where} ORDER BY id"  # noqa: S608

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
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
        with self._lock:
            row = self._conn.execute(
                f"SELECT COUNT(*) FROM vehicles WHERE {where}", params  # noqa: S608
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
        sql = (
            f"SELECT {PUBLIC_COLUMNS} FROM vehicles WHERE {where} "
            "ORDER BY id LIMIT ? OFFSET ?"
        )  # noqa: S608
        with self._lock:
            rows = self._conn.execute(sql, [*params, limit, offset]).fetchall()
        return [self._row_to_dict(r) for r in rows]

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
                "DELETE FROM vehicles WHERE id = ?", (vehicle_id,)
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def remove_expired(self) -> int:
        """Delete vehicles past their TTL. Returns count removed."""
        now = self._now()
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM vehicles WHERE expires_at != '' AND expires_at < ?", (now,)
            )
            self._conn.commit()
        return cursor.rowcount

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()
        return row[0]

    def get_stats(self) -> dict[str, Any]:
        """Comprehensive inventory analytics."""
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM vehicles"
            ).fetchone()[0]

            expired_count = self._conn.execute(
                "SELECT COUNT(*) FROM vehicles WHERE expires_at != '' AND expires_at < ?",
                (self._now(),),
            ).fetchone()[0]

            source_counts = dict(self._conn.execute(
                "SELECT source, COUNT(*) FROM vehicles GROUP BY source"
            ).fetchall())

            metro_counts = dict(self._conn.execute(
                "SELECT dealer_location, COUNT(*) FROM vehicles "
                "WHERE dealer_location != '' GROUP BY dealer_location"
            ).fetchall())

            price_stats = self._conn.execute(
                """SELECT
                    MIN(price), MAX(price), AVG(price),
                    SUM(CASE WHEN price < 20000 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN price BETWEEN 20000 AND 40000 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN price > 40000 THEN 1 ELSE 0 END)
                FROM vehicles"""
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
                FROM vehicles WHERE ingested_at != ''"""
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

    def record_lead(self, vehicle_id: str, action: str, user_query: str = "") -> str:
        """Record a user engagement lead. Returns lead_id."""
        lead_id = f"lead-{uuid.uuid4().hex[:12]}"
        now = self._now()

        vehicle = self.get(vehicle_id)
        if not vehicle:
            raise ValueError(f"Vehicle {vehicle_id} not found")

        with self._lock:
            self._conn.execute(
                """INSERT INTO leads
                    (
                        id, vehicle_id, vehicle_vin, dealer_name,
                        dealer_zip, action, user_query, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lead_id,
                    vehicle_id,
                    vehicle.get("vin", ""),
                    vehicle.get("dealer_name", ""),
                    vehicle.get("dealer_zip", ""),
                    action,
                    user_query,
                    now,
                ),
            )
            self._conn.execute(
                "UPDATE vehicles SET lead_count = lead_count + 1 WHERE id = ?",
                (vehicle_id,),
            )
            self._conn.commit()

        return lead_id

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
