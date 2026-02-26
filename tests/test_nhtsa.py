"""Tests for NHTSA client and tool implementations."""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cip_protocol import CIP

from auto_mcp.clients.nhtsa import (
    NHTSAClient,
    _normalize_input,
    _TTLCache,
    _validate_model_year,
)
from auto_mcp.server import (
    get_nhtsa_complaints,
    get_nhtsa_recalls,
    get_nhtsa_safety_ratings,
)
from auto_mcp.tools.nhtsa import (
    get_nhtsa_complaints_impl,
    get_nhtsa_recalls_impl,
    get_nhtsa_safety_ratings_impl,
)

# ── Fixtures ──────────────────────────────────────────────────────


def _make_recalls_response(count: int = 3) -> dict[str, Any]:
    return {
        "Count": count,
        "results": [
            {
                "NHTSACampaignNumber": f"24V{i:03d}000",
                "Component": "AIR BAGS" if i % 2 == 0 else "ELECTRICAL SYSTEM",
                "Summary": f"Recall summary {i}",
                "ReportReceivedDate": f"01/0{i + 1}/2024",
                "Manufacturer": "Test Manufacturer",
            }
            for i in range(count)
        ],
    }


def _make_complaints_response(count: int = 3) -> dict[str, Any]:
    return {
        "Count": count,
        "results": [
            {
                "odiNumber": f"1234{i}",
                "components": "ENGINE" if i % 2 == 0 else "BRAKES",
                "summary": f"Complaint summary {i}",
                "dateOfIncident": f"02/0{i + 1}/2024",
                "dateComplaintFiled": f"03/0{i + 1}/2024",
                "crash": "Y" if i == 0 else "N",
                "injuries": 1 if i == 0 else 0,
            }
            for i in range(count)
        ],
    }


def _make_safety_variants_response() -> dict[str, Any]:
    return {
        "Results": [
            {"VehicleId": 12345, "VehicleDescription": "2024 Test Model FWD"},
            {"VehicleId": 12346, "VehicleDescription": "2024 Test Model AWD"},
        ]
    }


def _make_safety_rating_response(vehicle_id: int = 12345) -> dict[str, Any]:
    return {
        "Results": [
            {
                "VehicleId": vehicle_id,
                "OverallRating": "5",
                "OverallFrontCrashRating": "4",
                "OverallSideCrashRating": "5",
                "RolloverRating": "4",
            }
        ]
    }


def _make_vin_decode_response() -> dict[str, Any]:
    return {
        "Results": [
            {
                "Make": "Toyota",
                "Model": "Camry",
                "ModelYear": "2024",
                "Trim": "LE",
                "BodyClass": "Sedan",
                "FuelTypePrimary": "Gasoline",
            }
        ]
    }


# ── TTLCache tests ────────────────────────────────────────────────


class TestTTLCache:
    def test_set_and_get(self):
        cache = _TTLCache(ttl=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_miss_returns_none(self):
        cache = _TTLCache(ttl=60)
        assert cache.get("missing") is None

    def test_expired_entry_returns_none(self):
        cache = _TTLCache(ttl=0)
        cache.set("key1", "value1")
        # TTL=0 means already expired
        time.sleep(0.01)
        assert cache.get("key1") is None

    def test_clear(self):
        cache = _TTLCache(ttl=60)
        cache.set("key1", "value1")
        cache.clear()
        assert cache.get("key1") is None


# ── Validation tests ──────────────────────────────────────────────


class TestValidation:
    def test_valid_model_year(self):
        _validate_model_year(2024)  # no exception

    def test_model_year_too_low(self):
        with pytest.raises(ValueError, match="1886"):
            _validate_model_year(1800)

    def test_model_year_too_high(self):
        with pytest.raises(ValueError, match="model_year"):
            _validate_model_year(3000)

    def test_normalize_input_preserves_acronyms(self):
        assert _normalize_input(" BMW ") == "BMW"
        assert _normalize_input("GMC") == "GMC"


# ── Client tests ──────────────────────────────────────────────────


class TestNHTSAClient:
    async def test_decode_vin(self):
        mock_resp = _make_vin_decode_response()
        client = NHTSAClient()
        client.session = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.status = 200
        mock_ctx.json = AsyncMock(return_value=mock_resp)
        mock_ctx.raise_for_status = MagicMock()
        mock_ctx.request_info = MagicMock()
        mock_ctx.history = ()
        client.session.get = MagicMock(return_value=mock_ctx)

        result = await client.decode_vin("1HGCV1F39NA000001")
        assert result is not None
        assert result["Make"] == "Toyota"

    async def test_decode_vin_error_returns_none(self):
        import aiohttp

        client = NHTSAClient()
        client.session = MagicMock()
        client.session.get = MagicMock(side_effect=aiohttp.ClientError("timeout"))

        result = await client.decode_vin("BADVIN")
        assert result is None

    async def test_get_recalls(self):
        mock_resp = _make_recalls_response(5)
        client = NHTSAClient()
        client.session = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.status = 200
        mock_ctx.json = AsyncMock(return_value=mock_resp)
        mock_ctx.raise_for_status = MagicMock()
        mock_ctx.request_info = MagicMock()
        mock_ctx.history = ()
        client.session.get = MagicMock(return_value=mock_ctx)

        result = await client.get_recalls("Toyota", "Camry", 2024)
        assert result["count"] == 5
        assert "summary" in result
        assert "records" in result
        assert len(result["records"]) <= 20

    async def test_get_complaints(self):
        mock_resp = _make_complaints_response(3)
        client = NHTSAClient()
        client.session = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.status = 200
        mock_ctx.json = AsyncMock(return_value=mock_resp)
        mock_ctx.raise_for_status = MagicMock()
        mock_ctx.request_info = MagicMock()
        mock_ctx.history = ()
        client.session.get = MagicMock(return_value=mock_ctx)

        result = await client.get_complaints("Toyota", "Camry", 2024)
        assert result["count"] == 3
        assert result["summary"]["crash_reports"] == 1
        assert result["summary"]["injury_reports"] == 1

    async def test_get_safety_ratings_two_step(self):
        client = NHTSAClient()
        client.session = MagicMock()

        call_count = 0
        variants_resp = _make_safety_variants_response()
        rating_resp_1 = _make_safety_rating_response(12345)
        rating_resp_2 = _make_safety_rating_response(12346)

        def _make_ctx(resp_data: dict) -> AsyncMock:
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=ctx)
            ctx.__aexit__ = AsyncMock(return_value=False)
            ctx.status = 200
            ctx.json = AsyncMock(return_value=resp_data)
            ctx.raise_for_status = MagicMock()
            ctx.request_info = MagicMock()
            ctx.history = ()
            return ctx

        responses = [
            _make_ctx(variants_resp),
            _make_ctx(rating_resp_1),
            _make_ctx(rating_resp_2),
        ]

        def _side_effect(*args, **kwargs):
            nonlocal call_count
            resp = responses[call_count]
            call_count += 1
            return resp

        client.session.get = MagicMock(side_effect=_side_effect)

        result = await client.get_safety_ratings("Toyota", "Camry", 2024)
        assert result["count"] == 2
        assert result["summary"]["OverallRating"] == "5"

    async def test_recalls_error_returns_error_dict(self):
        import aiohttp

        client = NHTSAClient()
        client.session = MagicMock()
        client.session.get = MagicMock(side_effect=aiohttp.ClientError("fail"))

        result = await client.get_recalls("Toyota", "Camry", 2024)
        assert result["count"] == 0
        assert "error" in result

    async def test_complaints_error_returns_error_dict(self):
        import aiohttp

        client = NHTSAClient()
        client.session = MagicMock()
        client.session.get = MagicMock(side_effect=aiohttp.ClientError("fail"))

        result = await client.get_complaints("Toyota", "Camry", 2024)
        assert result["count"] == 0
        assert "error" in result

    async def test_safety_ratings_error_returns_error_dict(self):
        import aiohttp

        client = NHTSAClient()
        client.session = MagicMock()
        client.session.get = MagicMock(side_effect=aiohttp.ClientError("fail"))

        result = await client.get_safety_ratings("Toyota", "Camry", 2024)
        assert result["count"] == 0
        assert "error" in result

    async def test_recalls_capping_at_max_records(self):
        mock_resp = _make_recalls_response(30)
        client = NHTSAClient()
        client.session = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.status = 200
        mock_ctx.json = AsyncMock(return_value=mock_resp)
        mock_ctx.raise_for_status = MagicMock()
        mock_ctx.request_info = MagicMock()
        mock_ctx.history = ()
        client.session.get = MagicMock(return_value=mock_ctx)

        result = await client.get_recalls("Toyota", "Camry", 2024)
        assert result["count"] == 30
        assert len(result["records"]) == 20

    async def test_empty_results(self):
        client = NHTSAClient()
        client.session = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.status = 200
        mock_ctx.json = AsyncMock(return_value={"Count": 0, "results": []})
        mock_ctx.raise_for_status = MagicMock()
        mock_ctx.request_info = MagicMock()
        mock_ctx.history = ()
        client.session.get = MagicMock(return_value=mock_ctx)

        result = await client.get_recalls("Nonexistent", "Car", 2024)
        assert result["count"] == 0
        assert result["records"] == []

    async def test_cache_hit_skips_request(self):
        mock_resp = _make_recalls_response(2)
        client = NHTSAClient()
        client.session = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.status = 200
        mock_ctx.json = AsyncMock(return_value=mock_resp)
        mock_ctx.raise_for_status = MagicMock()
        mock_ctx.request_info = MagicMock()
        mock_ctx.history = ()
        client.session.get = MagicMock(return_value=mock_ctx)

        # First call populates cache
        await client.get_recalls("Toyota", "Camry", 2024)
        # Second call should use cache
        await client.get_recalls("Toyota", "Camry", 2024)

        # session.get called only once (for the single recall endpoint)
        assert client.session.get.call_count == 1

    async def test_cache_key_is_canonical_for_param_order(self):
        client = NHTSAClient()
        client.session = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.status = 200
        mock_ctx.json = AsyncMock(return_value={"ok": True})
        mock_ctx.raise_for_status = MagicMock()
        mock_ctx.request_info = MagicMock()
        mock_ctx.history = ()
        client.session.get = MagicMock(return_value=mock_ctx)

        await client._request(
            "https://example.test/resource",
            params={"b": "2", "a": "1"},
        )
        await client._request(
            "https://example.test/resource",
            params={"a": "1", "b": "2"},
        )

        assert client.session.get.call_count == 1

    async def test_cache_can_be_shared_across_client_instances(self):
        shared_cache = _TTLCache(ttl=60)
        mock_resp = _make_recalls_response(2)

        first = NHTSAClient(cache=shared_cache)
        first.session = MagicMock()
        first_ctx = AsyncMock()
        first_ctx.__aenter__ = AsyncMock(return_value=first_ctx)
        first_ctx.__aexit__ = AsyncMock(return_value=False)
        first_ctx.status = 200
        first_ctx.json = AsyncMock(return_value=mock_resp)
        first_ctx.raise_for_status = MagicMock()
        first_ctx.request_info = MagicMock()
        first_ctx.history = ()
        first.session.get = MagicMock(return_value=first_ctx)

        await first.get_recalls("Toyota", "Camry", 2024)
        assert first.session.get.call_count == 1

        second = NHTSAClient(cache=shared_cache)
        second.session = MagicMock()
        second.session.get = MagicMock()
        await second.get_recalls("Toyota", "Camry", 2024)
        assert second.session.get.call_count == 0

    async def test_safety_ratings_no_variants(self):
        client = NHTSAClient()
        client.session = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.status = 200
        mock_ctx.json = AsyncMock(return_value={"Results": []})
        mock_ctx.raise_for_status = MagicMock()
        mock_ctx.request_info = MagicMock()
        mock_ctx.history = ()
        client.session.get = MagicMock(return_value=mock_ctx)

        result = await client.get_safety_ratings("Unknown", "Car", 2024)
        assert result["count"] == 0
        assert result["records"] == []


# ── Tool implementation tests ─────────────────────────────────────


class TestNHTSAToolImpls:
    """Test tool implementations with mocked NHTSA client."""

    async def test_recalls_with_vehicle_id(self, mock_cip: CIP):
        """Resolve vehicle from inventory, fetch recalls."""
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.get_recalls = AsyncMock(
                return_value={"count": 2, "summary": {}, "records": []}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_recalls_impl(
                mock_cip, vehicle_id="VH-001"
            )
            assert isinstance(result, str)
            assert len(result) > 0
            instance.get_recalls.assert_called_once()

    async def test_recalls_with_direct_params(self, mock_cip: CIP):
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.get_recalls = AsyncMock(
                return_value={"count": 0, "summary": {}, "records": []}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_recalls_impl(
                mock_cip, make="Hyundai", model="Tucson", model_year=2024
            )
            assert isinstance(result, str)
            instance.get_recalls.assert_called_once_with("Hyundai", "Tucson", 2024)

    async def test_recalls_missing_params(self, mock_cip: CIP):
        result = await get_nhtsa_recalls_impl(mock_cip, make="Toyota")
        assert "model is required" in result

    async def test_recalls_missing_make(self, mock_cip: CIP):
        result = await get_nhtsa_recalls_impl(
            mock_cip, model="Camry", model_year=2024
        )
        assert "make is required" in result

    async def test_recalls_vehicle_not_found(self, mock_cip: CIP):
        result = await get_nhtsa_recalls_impl(mock_cip, vehicle_id="NONEXISTENT")
        assert "not found" in result

    async def test_complaints_with_vehicle_id(self, mock_cip: CIP):
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.get_complaints = AsyncMock(
                return_value={"count": 1, "summary": {}, "records": []}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_complaints_impl(
                mock_cip, vehicle_id="VH-001"
            )
            assert isinstance(result, str)
            instance.get_complaints.assert_called_once()

    async def test_safety_ratings_with_vehicle_id(self, mock_cip: CIP):
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.get_safety_ratings = AsyncMock(
                return_value={"count": 1, "summary": {}, "records": []}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_safety_ratings_impl(
                mock_cip, vehicle_id="VH-001"
            )
            assert isinstance(result, str)
            instance.get_safety_ratings.assert_called_once()

    async def test_vehicle_id_takes_precedence(self, mock_cip: CIP):
        """When both vehicle_id and direct params are provided, vehicle_id wins."""
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.get_recalls = AsyncMock(
                return_value={"count": 0, "summary": {}, "records": []}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_recalls_impl(
                mock_cip,
                vehicle_id="VH-001",
                make="IgnoredMake",
                model="IgnoredModel",
                model_year=1999,
            )
            assert isinstance(result, str)
            # Should use vehicle's make/model/year, not the explicit ones
            call_args = instance.get_recalls.call_args
            assert call_args[0][0] != "IgnoredMake"

    async def test_complaints_missing_model_year(self, mock_cip: CIP):
        result = await get_nhtsa_complaints_impl(
            mock_cip, make="Toyota", model="Camry"
        )
        assert "model_year is required" in result

    async def test_safety_ratings_missing_params(self, mock_cip: CIP):
        result = await get_nhtsa_safety_ratings_impl(mock_cip)
        assert "make is required" in result

    async def test_raw_validation_error_returns_structured_payload(self, mock_cip: CIP):
        result = await get_nhtsa_recalls_impl(mock_cip, make="Toyota", raw=True)
        payload = json.loads(result)
        assert payload["_raw"] is True
        assert payload["_tool"] == "get_nhtsa_recalls"
        assert payload["data"]["error"] is True
        assert payload["data"]["code"] == "INVALID_INPUT"

    async def test_raw_vehicle_not_found_returns_structured_payload(self, mock_cip: CIP):
        result = await get_nhtsa_complaints_impl(
            mock_cip, vehicle_id="NONEXISTENT", raw=True
        )
        payload = json.loads(result)
        assert payload["_raw"] is True
        assert payload["_tool"] == "get_nhtsa_complaints"
        assert payload["data"]["error"] is True
        assert payload["data"]["code"] == "VEHICLE_NOT_FOUND"

    async def test_recalls_via_vin_decode(self, mock_cip: CIP):
        """VIN is decoded via NHTSA, then recalls fetched with decoded make/model/year."""
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.decode_vin = AsyncMock(
                return_value={"Make": "Toyota", "Model": "Camry", "ModelYear": "2024"}
            )
            instance.get_recalls = AsyncMock(
                return_value={"count": 3, "summary": {}, "records": []}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_recalls_impl(
                mock_cip, vin="1HGCV1F39NA000001"
            )
            assert isinstance(result, str)
            instance.decode_vin.assert_called_once_with("1HGCV1F39NA000001")
            instance.get_recalls.assert_called_once_with("Toyota", "Camry", 2024)

    async def test_complaints_via_vin_decode(self, mock_cip: CIP):
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.decode_vin = AsyncMock(
                return_value={"Make": "Honda", "Model": "Civic", "ModelYear": "2023"}
            )
            instance.get_complaints = AsyncMock(
                return_value={"count": 0, "summary": {}, "records": []}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_complaints_impl(
                mock_cip, vin="2HGFE1F70RN000001"
            )
            assert isinstance(result, str)
            instance.get_complaints.assert_called_once_with("Honda", "Civic", 2023)

    async def test_safety_ratings_via_vin_decode(self, mock_cip: CIP):
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.decode_vin = AsyncMock(
                return_value={"Make": "Ford", "Model": "F-150", "ModelYear": "2024"}
            )
            instance.get_safety_ratings = AsyncMock(
                return_value={"count": 1, "summary": {}, "records": []}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_safety_ratings_impl(
                mock_cip, vin="1FTFW1E80RFA00001"
            )
            assert isinstance(result, str)
            instance.get_safety_ratings.assert_called_once_with("Ford", "F-150", 2024)

    async def test_vin_takes_precedence_over_vehicle_id_and_direct(self, mock_cip: CIP):
        """VIN > vehicle_id > direct params."""
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.decode_vin = AsyncMock(
                return_value={"Make": "Hyundai", "Model": "Tucson", "ModelYear": "2024"}
            )
            instance.get_recalls = AsyncMock(
                return_value={"count": 0, "summary": {}, "records": []}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_recalls_impl(
                mock_cip,
                vin="KMHJ3814RU000001",
                vehicle_id="VH-001",
                make="IgnoredMake",
                model="IgnoredModel",
                model_year=1999,
            )
            assert isinstance(result, str)
            # VIN decode wins — vehicle_id and direct params ignored
            instance.decode_vin.assert_called_once_with("KMHJ3814RU000001")
            instance.get_recalls.assert_called_once_with("Hyundai", "Tucson", 2024)

    async def test_vin_decode_failure_returns_error(self, mock_cip: CIP):
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.decode_vin = AsyncMock(return_value=None)
            MockClient.return_value = instance

            result = await get_nhtsa_recalls_impl(
                mock_cip, vin="BADVIN12345678901"
            )
            assert "could not decode" in result.lower()

    async def test_vin_decode_incomplete_returns_error(self, mock_cip: CIP):
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.decode_vin = AsyncMock(
                return_value={"Make": "Toyota", "Model": "", "ModelYear": ""}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_recalls_impl(
                mock_cip, vin="1HGCV1F39NA000001"
            )
            assert "incomplete" in result.lower()

    async def test_raw_invalid_model_year_type_returns_structured_payload(
        self, mock_cip: CIP
    ):
        result = await get_nhtsa_safety_ratings_impl(
            mock_cip,
            make="Toyota",
            model="Camry",
            model_year="not-a-year",  # type: ignore[arg-type]
            raw=True,
        )
        payload = json.loads(result)
        assert payload["_raw"] is True
        assert payload["_tool"] == "get_nhtsa_safety_ratings"
        assert payload["data"]["error"] is True
        assert payload["data"]["code"] == "INVALID_INPUT"


# ── MCP wrapper smoke tests ──────────────────────────────────────


class TestNHTSAMCPWrappers:
    """Verify server-level MCP tool wrappers work end-to-end with mocked client."""

    async def test_get_nhtsa_recalls_returns_string(self):
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.get_recalls = AsyncMock(
                return_value={"count": 0, "summary": {}, "records": []}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_recalls(
                make="Toyota", model="Camry", model_year=2024
            )
            assert isinstance(result, str)

    async def test_get_nhtsa_complaints_returns_string(self):
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.get_complaints = AsyncMock(
                return_value={"count": 0, "summary": {}, "records": []}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_complaints(
                make="Toyota", model="Camry", model_year=2024
            )
            assert isinstance(result, str)

    async def test_get_nhtsa_safety_ratings_returns_string(self):
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.get_safety_ratings = AsyncMock(
                return_value={"count": 0, "summary": {}, "records": []}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_safety_ratings(
                make="Toyota", model="Camry", model_year=2024
            )
            assert isinstance(result, str)

    async def test_nhtsa_wrapper_sanitizes_errors(self, monkeypatch):
        async def _raise(*_args, **_kwargs):
            raise RuntimeError("simulated-failure")

        monkeypatch.setattr(
            "auto_mcp.server.get_nhtsa_recalls_impl", _raise
        )
        result = await get_nhtsa_recalls(
            make="Toyota", model="Camry", model_year=2024
        )
        assert "having trouble" in result.lower()
        assert "simulated-failure" not in result.lower()

    async def test_nhtsa_recalls_via_vin_wrapper(self):
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.decode_vin = AsyncMock(
                return_value={"Make": "Toyota", "Model": "Camry", "ModelYear": "2024"}
            )
            instance.get_recalls = AsyncMock(
                return_value={"count": 0, "summary": {}, "records": []}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_recalls(vin="1HGCV1F39NA000001")
            assert isinstance(result, str)

    async def test_nhtsa_recalls_accepts_orchestration_params(self):
        with patch("auto_mcp.tools.nhtsa.NHTSAClient") as MockClient:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.get_recalls = AsyncMock(
                return_value={"count": 0, "summary": {}, "records": []}
            )
            MockClient.return_value = instance

            result = await get_nhtsa_recalls(
                make="Toyota",
                model="Camry",
                model_year=2024,
                provider="anthropic",
                scaffold_id="nhtsa_safety",
                policy="concise",
                context_notes="Test context.",
                raw=False,
            )
            assert isinstance(result, str)
