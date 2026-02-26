"""Ingestion pipeline normalization tests."""

from __future__ import annotations

import pytest

from auto_mcp.ingestion.pipeline import AutoDevClient, normalize_auto_dev_listing
from auto_mcp.normalization import (
    BODY_TYPE_MAP,
    FUEL_TYPE_MAP,
    clean_numeric_string,
    normalize_body_type,
    normalize_fuel_type,
    parse_float,
    parse_int,
    parse_price,
)


class _FakeResponse:
    def __init__(self, payload):
        self.status = 200
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def raise_for_status(self):
        return None

    async def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        return _FakeResponse(self._payload)


def test_normalize_auto_dev_listing_tolerates_empty_numeric_fields():
    raw = {
        "vin": "1HGCM82633A004352",
        "year": "",
        "make": "honda",
        "model": "accord",
        "type": "Sedan",
        "price": "$12,000",
        "mileage": "",
        "fuelType": "Gasoline",
        "mpgCity": "",
        "mpgHighway": "",
        "safetyRating": "",
        "features": "not-a-list",
        "dealer": {
            "name": "Dealer One",
            "city": "Austin",
            "state": "TX",
            "zip": "78701",
            "latitude": "",
            "longitude": "",
        },
    }

    normalized = normalize_auto_dev_listing(raw)
    assert normalized is not None
    assert normalized["year"] == 0
    assert normalized["mileage"] == 0
    assert normalized["mpg_city"] == 0
    assert normalized["mpg_highway"] == 0
    assert normalized["safety_rating"] == 0
    assert normalized["features"] == []
    assert normalized["latitude"] is None
    assert normalized["longitude"] is None


def test_normalize_auto_dev_listing_parses_numeric_strings():
    raw = {
        "vin": "5YJSA1E26HF000337",
        "year": "2024",
        "make": "tesla",
        "model": "model s",
        "type": "Sedan",
        "price": "$89,990",
        "mileage": "12,345",
        "fuelType": "Electric",
        "mpgCity": "120",
        "mpgHighway": "112",
        "safetyRating": "5",
        "dealer": {
            "name": "Dealer Two",
            "city": "Austin",
            "state": "TX",
            "zip": "78704",
            "latitude": "30.2672",
            "longitude": "-97.7431",
        },
    }

    normalized = normalize_auto_dev_listing(raw)
    assert normalized is not None
    assert normalized["year"] == 2024
    assert normalized["mileage"] == 12345
    assert normalized["mpg_city"] == 120
    assert normalized["mpg_highway"] == 112
    assert normalized["safety_rating"] == 5
    assert normalized["price"] == 89990.0
    assert normalized["latitude"] == 30.2672
    assert normalized["longitude"] == -97.7431


def test_normalize_auto_dev_listing_supports_records_shape():
    raw = {
        "vin": "1HGCM82633A004352",
        "year": 2020,
        "make": "ford",
        "model": "escape",
        "trim": "SE",
        "bodyType": "SUV",
        "priceUnformatted": 15888,
        "mileageUnformatted": 107266,
        "displayColor": "Blue",
        "dealerName": "Example Dealer",
        "city": "Austin",
        "state": "TX",
        "lat": "30.2672",
        "lon": "-97.7431",
        "active": True,
        "clickoffUrl": "https://example.invalid/listing",
    }

    normalized = normalize_auto_dev_listing(raw)
    assert normalized is not None
    assert normalized["body_type"] == "suv"
    assert normalized["price"] == 15888.0
    assert normalized["mileage"] == 107266
    assert normalized["exterior_color"] == "Blue"
    assert normalized["fuel_type"] == ""
    assert normalized["dealer_name"] == "Example Dealer"
    assert normalized["dealer_location"] == "Austin, TX"
    assert normalized["latitude"] == 30.2672
    assert normalized["longitude"] == -97.7431
    assert normalized["availability_status"] == "in_stock"
    assert normalized["source_url"] == "https://example.invalid/listing"


@pytest.mark.asyncio
async def test_search_listings_reads_records_key():
    client = AutoDevClient("test-key")
    client.session = _FakeSession({"records": [{"vin": "abc"}]})

    listings = await client.search_listings(zip_code="78701")
    assert listings == [{"vin": "abc"}]


@pytest.mark.asyncio
async def test_search_listings_reads_data_key():
    client = AutoDevClient("test-key")
    client.session = _FakeSession({"data": [{"vin": "xyz"}]})

    listings = await client.search_listings(zip_code="78701")
    assert listings == [{"vin": "xyz"}]


@pytest.mark.asyncio
async def test_search_listings_cache_key_is_canonical():
    session = _FakeSession({"data": [{"vin": "xyz"}]})
    client = AutoDevClient("test-key")
    client.session = session

    await client._request("/listings", params={"b": "2", "a": "1"})
    await client._request("/listings", params={"a": "1", "b": "2"})

    assert session.calls == 1


@pytest.mark.asyncio
async def test_search_listings_sends_v2_query_params():
    captured_params = {}

    class _CaptureSession:
        def get(self, _url, *, params=None, **_kwargs):
            captured_params.update(params or {})
            return _FakeResponse({"records": []})

    client = AutoDevClient("test-key")
    client.session = _CaptureSession()

    await client.search_listings(
        zip_code="78701",
        distance_miles=25,
        make="Toyota",
        model="Camry",
        price_min=15000,
        price_max=32000,
    )

    assert captured_params.get("zip") == "78701"
    assert captured_params.get("distance") == "25"
    assert captured_params.get("vehicle.make") == "Toyota"
    assert captured_params.get("vehicle.model") == "Camry"
    assert captured_params.get("retailListing.price") == "15000-32000"
    assert "radius" not in captured_params
    assert "make" not in captured_params
    assert "model" not in captured_params


# ── Shared normalization module tests ────────────────────────────


class TestCanonicalNormalization:
    """Tests for the shared normalization module (auto_mcp.normalization)."""

    def test_clean_numeric_string_strips_non_numeric(self):
        assert clean_numeric_string("$12,345.67") == "12345.67"
        assert clean_numeric_string("abc") == ""
        assert clean_numeric_string("-3.14") == "-3.14"

    def test_parse_price_returns_none_for_unparseable(self):
        assert parse_price(None) is None
        assert parse_price(True) is None
        assert parse_price("") is None
        assert parse_price("abc") is None

    def test_parse_price_handles_valid_inputs(self):
        assert parse_price(100) == 100.0
        assert parse_price(99.5) == 99.5
        assert parse_price("$12,345") == 12345.0
        assert parse_price("0") == 0.0

    def test_parse_int_returns_none_for_unparseable(self):
        assert parse_int(None) is None
        assert parse_int(True) is None
        assert parse_int("") is None
        assert parse_int("abc") is None

    def test_parse_int_handles_valid_inputs(self):
        assert parse_int(42) == 42
        assert parse_int(3.9) == 3
        assert parse_int("100") == 100

    def test_parse_float_returns_none_for_unparseable(self):
        assert parse_float(None) is None
        assert parse_float(True) is None
        assert parse_float("") is None
        assert parse_float("not_a_number") is None

    def test_parse_float_handles_valid_inputs(self):
        assert parse_float(3) == 3.0
        assert parse_float(-97.7431) == -97.7431
        assert parse_float("-97.7431") == -97.7431

    def test_normalize_body_type_empty_returns_empty(self):
        assert normalize_body_type(None) == ""
        assert normalize_body_type("") == ""

    def test_normalize_body_type_maps_correctly(self):
        assert normalize_body_type("Sedan") == "sedan"
        assert normalize_body_type("CROSSOVER") == "suv"
        assert normalize_body_type("pickup") == "truck"

    def test_normalize_body_type_passes_through_unknown(self):
        assert normalize_body_type("Roadster") == "roadster"

    def test_normalize_fuel_type_empty_returns_empty(self):
        assert normalize_fuel_type(None) == ""
        assert normalize_fuel_type("") == ""

    def test_normalize_fuel_type_maps_correctly(self):
        assert normalize_fuel_type("Gasoline") == "gasoline"
        assert normalize_fuel_type("Plug-In Hybrid") == "hybrid"
        assert normalize_fuel_type("FLEX FUEL") == "gasoline"

    def test_normalize_fuel_type_passes_through_unknown(self):
        assert normalize_fuel_type("Hydrogen") == "hydrogen"

    def test_body_type_map_all_lowercase_keys(self):
        for key in BODY_TYPE_MAP:
            assert key == key.lower()

    def test_fuel_type_map_all_lowercase_keys(self):
        for key in FUEL_TYPE_MAP:
            assert key == key.lower()

    def test_pipeline_wrappers_preserve_defaults(self):
        """Pipeline's local wrappers should still produce 0/0.0/'other'/'gasoline'."""
        from auto_mcp.ingestion.pipeline import (
            normalize_body_type as pipe_body,
        )
        from auto_mcp.ingestion.pipeline import (
            normalize_fuel_type as pipe_fuel,
        )
        from auto_mcp.ingestion.pipeline import (
            parse_int as pipe_int,
        )
        from auto_mcp.ingestion.pipeline import (
            parse_price as pipe_price,
        )
        assert pipe_body(None) == "other"
        assert pipe_fuel(None) == "gasoline"
        assert pipe_int(None) == 0
        assert pipe_price(None) == 0.0
