"""Ingestion pipeline normalization tests."""

from __future__ import annotations

import pytest

from auto_mcp.ingestion.pipeline import AutoDevClient, normalize_auto_dev_listing


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

    def get(self, *_args, **_kwargs):
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
