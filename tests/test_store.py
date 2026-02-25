"""Unit tests for VehicleStore protocol and SqliteVehicleStore implementation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from auto_mcp.data.seed import seed_demo_data
from auto_mcp.data.store import SqliteVehicleStore, VehicleStore, ZipCodeDatabase


@pytest.fixture()
def store() -> SqliteVehicleStore:
    """A fresh in-memory store for each test."""
    return SqliteVehicleStore(":memory:")


@pytest.fixture()
def seeded_store(store: SqliteVehicleStore) -> SqliteVehicleStore:
    """In-memory store pre-loaded with demo data."""
    seed_demo_data(store)
    return store


SAMPLE_VEHICLE = {
    "id": "TEST-001",
    "year": 2025,
    "make": "TestMake",
    "model": "TestModel",
    "trim": "Base",
    "body_type": "sedan",
    "price": 25_000,
    "mileage": 0,
    "exterior_color": "Red",
    "interior_color": "Black",
    "fuel_type": "gasoline",
    "mpg_city": 30,
    "mpg_highway": 40,
    "engine": "2.0L I4",
    "transmission": "6-Speed Auto",
    "drivetrain": "FWD",
    "features": ["Bluetooth", "Backup Camera"],
    "safety_rating": 5,
    "dealer_name": "Test Dealer",
    "dealer_location": "Austin, TX",
    "availability_status": "in_stock",
    "vin": "TEST00000000001",
}


# ── Protocol compliance ────────────────────────────────────────


class TestProtocolCompliance:
    def test_sqlite_store_satisfies_protocol(self, store: SqliteVehicleStore):
        assert isinstance(store, VehicleStore)

    def test_protocol_has_required_methods(self):
        methods = {"get", "search", "upsert", "upsert_many", "remove", "count"}
        protocol_methods = {
            name for name in dir(VehicleStore)
            if not name.startswith("_") and callable(getattr(VehicleStore, name, None))
        }
        assert methods.issubset(protocol_methods)


# ── CRUD operations ────────────────────────────────────────────


class TestCRUD:
    def test_empty_store_count(self, store: SqliteVehicleStore):
        assert store.count() == 0

    def test_upsert_and_get(self, store: SqliteVehicleStore):
        store.upsert(SAMPLE_VEHICLE)
        got = store.get("TEST-001")
        assert got is not None
        assert got["id"] == "TEST-001"
        assert got["make"] == "TestMake"
        assert got["price"] == 25_000

    def test_get_nonexistent(self, store: SqliteVehicleStore):
        assert store.get("DOES-NOT-EXIST") is None

    def test_get_by_vin_is_case_insensitive(self, store: SqliteVehicleStore):
        vehicle = {
            **SAMPLE_VEHICLE,
            "id": "VIN-CASE-001",
            "vin": "abc12345678901234",
        }
        store.upsert(vehicle)

        got = store.get_by_vin("ABC12345678901234")
        assert got is not None
        assert got["id"] == "VIN-CASE-001"
        assert got["vin"] == "ABC12345678901234"

    def test_upsert_tolerates_none_optional_numeric_fields(self, store: SqliteVehicleStore):
        vehicle = {
            **SAMPLE_VEHICLE,
            "id": "NONE-OPTIONALS-001",
            "vin": "NONEOPTIONALVIN01",
            "mileage": None,
            "mpg_city": None,
            "mpg_highway": None,
            "safety_rating": None,
            "latitude": None,
            "longitude": None,
        }

        store.upsert(vehicle)
        got = store.get("NONE-OPTIONALS-001")
        assert got is not None
        assert got["mileage"] == 0
        assert got["mpg_city"] == 0
        assert got["mpg_highway"] == 0
        assert got["safety_rating"] == 0
        assert got["latitude"] is None
        assert got["longitude"] is None

    def test_upsert_many_and_count(self, store: SqliteVehicleStore):
        vehicles = [
            {**SAMPLE_VEHICLE, "id": f"BATCH-{i}", "vin": f"BATCHVIN{i:09d}"}
            for i in range(5)
        ]
        store.upsert_many(vehicles)
        assert store.count() == 5

    def test_remove_existing(self, store: SqliteVehicleStore):
        store.upsert(SAMPLE_VEHICLE)
        assert store.remove("TEST-001") is True
        assert store.get("TEST-001") is None

    def test_remove_nonexistent(self, store: SqliteVehicleStore):
        assert store.remove("DOES-NOT-EXIST") is False

    def test_seed_demo_data(self, store: SqliteVehicleStore):
        count = seed_demo_data(store)
        assert count == 32
        assert store.count() == 32


# ── JSON round-trip for features ───────────────────────────────


class TestFeaturesJSON:
    def test_features_round_trip(self, store: SqliteVehicleStore):
        store.upsert(SAMPLE_VEHICLE)
        got = store.get("TEST-001")
        assert got is not None
        assert got["features"] == ["Bluetooth", "Backup Camera"]
        assert isinstance(got["features"], list)

    def test_empty_features_round_trip(self, store: SqliteVehicleStore):
        v = {**SAMPLE_VEHICLE, "id": "EMPTY-F", "features": []}
        store.upsert(v)
        got = store.get("EMPTY-F")
        assert got is not None
        assert got["features"] == []


# ── Search filters ─────────────────────────────────────────────


class TestSearch:
    def test_search_all(self, seeded_store: SqliteVehicleStore):
        results = seeded_store.search()
        assert len(results) == 32

    def test_search_by_make(self, seeded_store: SqliteVehicleStore):
        results = seeded_store.search(make="Toyota")
        assert len(results) >= 1
        assert all(r["make"] == "Toyota" for r in results)

    def test_search_by_body_type(self, seeded_store: SqliteVehicleStore):
        results = seeded_store.search(body_type="truck")
        assert len(results) >= 1
        assert all(r["body_type"] == "truck" for r in results)

    def test_search_by_fuel_type(self, seeded_store: SqliteVehicleStore):
        results = seeded_store.search(fuel_type="electric")
        assert len(results) >= 1
        assert all(r["fuel_type"] == "electric" for r in results)

    def test_search_by_price_range(self, seeded_store: SqliteVehicleStore):
        results = seeded_store.search(price_min=30_000, price_max=40_000)
        assert all(30_000 <= r["price"] <= 40_000 for r in results)
        assert len(results) >= 1

    def test_search_by_year_range(self, seeded_store: SqliteVehicleStore):
        results = seeded_store.search(year_min=2024, year_max=2024)
        assert all(r["year"] == 2024 for r in results)
        assert len(results) >= 1

    def test_search_combined_filters(self, seeded_store: SqliteVehicleStore):
        results = seeded_store.search(make="Toyota", body_type="suv")
        assert all(r["make"] == "Toyota" and r["body_type"] == "suv" for r in results)


# ── Windowed search primitives ─────────────────────────────────


class TestWindowedSearch:
    def test_count_filtered_matches_full_search(self, seeded_store: SqliteVehicleStore):
        full = seeded_store.search(make="Toyota", body_type="suv")
        count = seeded_store.count_filtered(make="Toyota", body_type="suv")
        assert count == len(full)

    def test_search_page_returns_limited_results(self, seeded_store: SqliteVehicleStore):
        page = seeded_store.search_page(make="Toyota", limit=2, offset=0)
        assert len(page) == 2
        assert all(v["make"] == "Toyota" for v in page)

    def test_search_page_offset_pages_are_distinct(self, seeded_store: SqliteVehicleStore):
        first = seeded_store.search_page(make="Toyota", limit=2, offset=0)
        second = seeded_store.search_page(make="Toyota", limit=2, offset=2)
        assert len(first) == 2
        assert len(second) == 2
        assert {v["id"] for v in first}.isdisjoint({v["id"] for v in second})


# ── Case insensitivity ─────────────────────────────────────────


class TestCaseInsensitivity:
    def test_search_make_case_insensitive(self, seeded_store: SqliteVehicleStore):
        lower = seeded_store.search(make="toyota")
        upper = seeded_store.search(make="TOYOTA")
        mixed = seeded_store.search(make="Toyota")
        assert len(lower) == len(upper) == len(mixed)
        assert len(lower) >= 1

    def test_search_body_type_case_insensitive(self, seeded_store: SqliteVehicleStore):
        assert len(seeded_store.search(body_type="SUV")) == len(
            seeded_store.search(body_type="suv")
        )

    def test_search_fuel_type_case_insensitive(self, seeded_store: SqliteVehicleStore):
        assert len(seeded_store.search(fuel_type="ELECTRIC")) == len(
            seeded_store.search(fuel_type="electric")
        )


# ── dealer_location search ─────────────────────────────────────


class TestDealerLocationSearch:
    def test_search_by_dealer_location(self, seeded_store: SqliteVehicleStore):
        results = seeded_store.search(dealer_location="Austin")
        assert len(results) >= 1
        assert all("Austin" in r["dealer_location"] for r in results)

    def test_search_by_state(self, seeded_store: SqliteVehicleStore):
        results = seeded_store.search(dealer_location="TX")
        assert len(results) == 32  # All demo vehicles are in TX


# ── Upsert idempotency ────────────────────────────────────────


class TestUpsertIdempotency:
    def test_upsert_twice_no_duplicate(self, store: SqliteVehicleStore):
        store.upsert(SAMPLE_VEHICLE)
        store.upsert(SAMPLE_VEHICLE)
        assert store.count() == 1

    def test_upsert_updates_fields(self, store: SqliteVehicleStore):
        store.upsert(SAMPLE_VEHICLE)
        updated = {**SAMPLE_VEHICLE, "price": 27_500}
        store.upsert(updated)
        got = store.get("TEST-001")
        assert got is not None
        assert got["price"] == 27_500
        assert store.count() == 1


# ── Public dict contract ──────────────────────────────────────


class TestPublicContract:
    def test_no_updated_at_in_public_dict(self, store: SqliteVehicleStore):
        """updated_at is internal metadata — never exposed to callers."""
        store.upsert(SAMPLE_VEHICLE)
        got = store.get("TEST-001")
        assert got is not None
        assert "updated_at" not in got

    def test_32_field_contract(self, seeded_store: SqliteVehicleStore):
        """Every vehicle dict from the store should have exactly 32 public fields."""
        v = seeded_store.get("VH-001")
        assert v is not None
        expected = {
            "id", "year", "make", "model", "trim", "body_type", "price",
            "mileage", "exterior_color", "interior_color", "fuel_type",
            "mpg_city", "mpg_highway", "engine", "transmission", "drivetrain",
            "features", "safety_rating", "dealer_name", "dealer_location",
            "availability_status", "vin",
            "dealer_zip", "latitude", "longitude",
            "source", "source_url",
            "ingested_at", "expires_at", "last_verified",
            "is_featured", "lead_count",
        }
        assert set(v.keys()) == expected


# ── Concurrency safety ─────────────────────────────────────────


class TestConcurrency:
    def test_concurrent_upserts_and_reads(self, store: SqliteVehicleStore):
        def writer(i: int) -> None:
            vehicle = {
                **SAMPLE_VEHICLE,
                "id": f"CONC-{i:03d}",
                "vin": f"CONCVIN{i:09d}",
            }
            store.upsert(vehicle)

        def reader() -> int:
            return len(store.search(make="TestMake"))

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = []
            for i in range(60):
                futures.append(pool.submit(writer, i))
                futures.append(pool.submit(reader))

            for future in futures:
                future.result()

        assert store.count() == 60


class TestLeadAnalytics:
    def test_top_dealers_grouped_by_name_and_zip(self, store: SqliteVehicleStore):
        common = {
            **SAMPLE_VEHICLE,
            "dealer_name": "Unified Dealer",
        }
        store.upsert({
            **common,
            "id": "LEAD-001",
            "vin": "LEADVINA000000001",
            "dealer_zip": "11111",
        })
        store.upsert({
            **common,
            "id": "LEAD-002",
            "vin": "LEADVINA000000002",
            "dealer_zip": "22222",
        })

        store.record_lead("LEAD-001", "viewed")
        store.record_lead("LEAD-002", "viewed")

        analytics = store.get_lead_analytics(days=30)
        top_dealers = {
            (entry["name"], entry["zip"], entry["leads"])
            for entry in analytics["top_dealers"]
        }
        assert ("Unified Dealer", "11111", 1) in top_dealers
        assert ("Unified Dealer", "22222", 1) in top_dealers


class TestZipCodeDatabase:
    def test_supports_top_metro_wave_zips(self):
        db = ZipCodeDatabase()
        expected = {
            "10101", "90210", "60616", "77027", "78731",
            "32202", "94109", "48226", "33606",
        }
        assert all(db.get(zip_code) is not None for zip_code in expected)


class TestLeadProfilesAndScoring:
    def test_record_lead_legacy_still_works(self, store: SqliteVehicleStore):
        store.upsert(SAMPLE_VEHICLE)
        lead_id = store.record_lead("TEST-001", "viewed")
        assert lead_id.startswith("leadprof-")

    def test_identity_resolution_prefers_customer_id(self, store: SqliteVehicleStore):
        store.upsert(SAMPLE_VEHICLE)
        first = store.record_lead("TEST-001", "viewed", customer_id="cust-abc")
        second = store.record_lead("TEST-001", "compared", customer_id="cust-abc")
        assert first == second

    def test_score_math_for_recent_events(self, store: SqliteVehicleStore):
        store.upsert(SAMPLE_VEHICLE)
        lead_id = store.record_lead("TEST-001", "viewed", customer_id="cust-score")
        store.record_lead("TEST-001", "compared", lead_id=lead_id)

        detail = store.get_lead_detail(lead_id)
        assert detail is not None
        total = detail["score_breakdown"]["total_score"]
        assert total == pytest.approx(4.0, rel=1e-5)

    def test_get_hot_leads_sorted(self, store: SqliteVehicleStore):
        store.upsert(SAMPLE_VEHICLE)
        store.upsert({**SAMPLE_VEHICLE, "id": "TEST-002", "vin": "TESTVIN0000000002"})
        a = store.record_lead("TEST-001", "test_drive", customer_id="hot-a")
        b = store.record_lead("TEST-002", "viewed", customer_id="hot-b")

        hot = store.get_hot_leads(limit=5, min_score=0, days=30)
        ids = [item["lead_id"] for item in hot]
        assert a in ids
        assert b in ids
        assert hot[0]["score"] >= hot[-1]["score"]


class TestDealerIntelligenceReports:
    def test_inventory_aging_fallback_and_summary(self, store: SqliteVehicleStore):
        old_ingested = (datetime.now(timezone.utc) - timedelta(days=50)).isoformat()
        new_ingested = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        store.upsert({
            **SAMPLE_VEHICLE,
            "id": "AGE-001",
            "vin": "AGEVIN00000000001",
            "body_type": "sedan",
            "ingested_at": old_ingested,
        })
        store.upsert({
            **SAMPLE_VEHICLE,
            "id": "AGE-002",
            "vin": "AGEVIN00000000002",
            "body_type": "sedan",
            "ingested_at": new_ingested,
        })

        report = store.get_inventory_aging_report(min_days_on_lot=30, limit=10)
        assert report["total_units_considered"] == 2
        assert any(item["stale"] for item in report["unit_rows"])
        assert any(summary["body_type"] == "sedan" for summary in report["summary_by_body_type"])

    def test_pricing_opportunities_flags_overpriced(self, store: SqliteVehicleStore):
        store.upsert({
            **SAMPLE_VEHICLE,
            "id": "PR-001",
            "vin": "PRICEVIN000000001",
            "make": "Toyota",
            "model": "Camry",
            "price": 30_000,
        })
        store.upsert({
            **SAMPLE_VEHICLE,
            "id": "PR-002",
            "vin": "PRICEVIN000000002",
            "make": "Toyota",
            "model": "Camry",
            "price": 20_000,
        })
        store.upsert({
            **SAMPLE_VEHICLE,
            "id": "PR-003",
            "vin": "PRICEVIN000000003",
            "make": "Toyota",
            "model": "Camry",
            "price": 21_000,
        })

        opportunities = store.get_pricing_opportunities(limit=10, overpriced_threshold_pct=5.0)
        flagged = {item["vehicle_id"] for item in opportunities["opportunities"]}
        assert "PR-001" in flagged


class TestSalesAndFunnel:
    def test_record_sale_updates_vehicle_status(self, store: SqliteVehicleStore):
        store.upsert({**SAMPLE_VEHICLE, "id": "SALE-001", "vin": "SALEVIN000000001"})
        lead_id = store.record_lead("SALE-001", "viewed", customer_id="sale-cust")
        result = store.record_sale(
            vehicle_id="SALE-001",
            sold_price=24_500,
            sold_at="2026-02-20T12:00:00+00:00",
            lead_id=lead_id,
        )

        assert result["vehicle_id"] == "SALE-001"
        vehicle = store.get("SALE-001")
        assert vehicle is not None
        assert vehicle["availability_status"] == "sold"

    def test_record_sale_can_remove_vehicle(self, store: SqliteVehicleStore):
        store.upsert({**SAMPLE_VEHICLE, "id": "SALE-002", "vin": "SALEVIN000000002"})
        store.record_sale(
            vehicle_id="SALE-002",
            sold_price=23_100,
            sold_at="2026-02-20T12:00:00+00:00",
            keep_vehicle_record=False,
        )
        assert store.get("SALE-002") is None

    def test_funnel_metrics_stage_counts(self, store: SqliteVehicleStore):
        store.upsert({**SAMPLE_VEHICLE, "id": "FUNNEL-001", "vin": "FNLVIN000000001"})
        lead_id = store.record_lead("FUNNEL-001", "viewed", customer_id="funnel-cust")
        store.record_lead("FUNNEL-001", "compared", lead_id=lead_id)
        store.record_lead("FUNNEL-001", "financed", lead_id=lead_id)
        store.record_lead("FUNNEL-001", "availability_check", lead_id=lead_id)
        store.record_sale(
            vehicle_id="FUNNEL-001",
            sold_price=26_000,
            sold_at="2026-02-20T12:00:00+00:00",
            lead_id=lead_id,
            source_channel="organic",
        )

        metrics = store.get_funnel_metrics(days=30, breakdown_by="source_channel")
        overall = metrics["overall"]["stage_counts"]
        assert overall["discovery"] >= 1
        assert overall["outcome"] >= 1
        assert "organic" in metrics["breakdown"]
