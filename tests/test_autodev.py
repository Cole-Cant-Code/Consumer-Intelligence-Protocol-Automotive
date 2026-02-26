"""Tests for Auto.dev client-backed tool implementations and MCP wrappers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from cip_protocol import CIP

from auto_mcp.clients.autodev import AutoDevClientError
from auto_mcp.server import (
    get_autodev_listings,
    get_autodev_overview,
    get_autodev_vehicle_photos,
    get_autodev_vin_decode,
)
from auto_mcp.tools.autodev import (
    get_autodev_listings_impl,
    get_autodev_overview_impl,
    get_autodev_vehicle_photos_impl,
    get_autodev_vin_decode_impl,
)


class TestAutoDevToolImpls:
    async def test_overview_success(self, mock_cip: CIP, monkeypatch):
        monkeypatch.setenv("AUTO_DEV_API_KEY", "test-key")
        with patch("auto_mcp.tools.autodev.AutoDevClient") as mock_client:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.get_overview = AsyncMock(
                return_value={
                    "user": {
                        "subscription": {"name": "Starter"},
                        "usage": {"freeApiCallsLeft": 991, "apiCallsUsed": 9},
                    }
                }
            )
            mock_client.return_value = instance

            result = await get_autodev_overview_impl(mock_cip)
            assert isinstance(result, str)
            instance.get_overview.assert_called_once()

    async def test_missing_api_key_returns_error(self, mock_cip: CIP, monkeypatch):
        monkeypatch.delenv("AUTO_DEV_API_KEY", raising=False)
        result = await get_autodev_overview_impl(mock_cip)
        assert "auto_dev_api_key" in result.lower()

    async def test_missing_api_key_raw_returns_structured(self, mock_cip: CIP, monkeypatch):
        monkeypatch.delenv("AUTO_DEV_API_KEY", raising=False)
        result = await get_autodev_overview_impl(mock_cip, raw=True)
        payload = json.loads(result)
        assert payload["_raw"] is True
        assert payload["_tool"] == "get_autodev_overview"
        assert payload["data"]["error"] is True
        assert payload["data"]["code"] == "MISSING_API_KEY"

    async def test_vin_decode_success(self, mock_cip: CIP, monkeypatch):
        monkeypatch.setenv("AUTO_DEV_API_KEY", "test-key")
        with patch("auto_mcp.tools.autodev.AutoDevClient") as mock_client:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.decode_vin = AsyncMock(
                return_value={"vin": "1HGCV1F39NA000001", "year": 2024, "make": "Honda"}
            )
            mock_client.return_value = instance

            result = await get_autodev_vin_decode_impl(mock_cip, vin="1HGCV1F39NA000001")
            assert isinstance(result, str)
            instance.decode_vin.assert_called_once_with("1HGCV1F39NA000001")

    async def test_vin_decode_invalid_vin(self, mock_cip: CIP):
        result = await get_autodev_vin_decode_impl(mock_cip, vin="BADVIN")
        assert "invalid vin" in result.lower()

    async def test_listings_by_zip_success(self, mock_cip: CIP, monkeypatch):
        monkeypatch.setenv("AUTO_DEV_API_KEY", "test-key")
        with patch("auto_mcp.tools.autodev.AutoDevClient") as mock_client:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.search_listings_raw = AsyncMock(
                return_value={
                    "records": [
                        {
                            "vin": "1HGCV1F39NA000001",
                            "year": 2024,
                            "make": "Honda",
                            "model": "Civic",
                        }
                    ]
                }
            )
            mock_client.return_value = instance

            result = await get_autodev_listings_impl(mock_cip, zip_code="78701")
            assert isinstance(result, str)
            instance.search_listings_raw.assert_called_once()

    async def test_listings_by_vin_takes_precedence(self, mock_cip: CIP, monkeypatch):
        monkeypatch.setenv("AUTO_DEV_API_KEY", "test-key")
        with patch("auto_mcp.tools.autodev.AutoDevClient") as mock_client:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.get_listing_by_vin = AsyncMock(return_value={"vin": "1HGCV1F39NA000001"})
            mock_client.return_value = instance

            result = await get_autodev_listings_impl(
                mock_cip,
                vin="1HGCV1F39NA000001",
                zip_code="78701",
                make="Honda",
            )
            assert isinstance(result, str)
            instance.get_listing_by_vin.assert_called_once_with("1HGCV1F39NA000001")
            instance.search_listings_raw.assert_not_called()

    async def test_listings_requires_zip_or_vin(self, mock_cip: CIP):
        result = await get_autodev_listings_impl(mock_cip)
        assert "provide either vin or zip_code" in result.lower()

    async def test_photos_by_vehicle_id_success(self, mock_cip: CIP, monkeypatch):
        monkeypatch.setenv("AUTO_DEV_API_KEY", "test-key")
        with patch("auto_mcp.tools.autodev.AutoDevClient") as mock_client:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.get_vehicle_photos = AsyncMock(
                return_value={"photos": [{"url": "https://example.com/photo1.jpg"}]}
            )
            mock_client.return_value = instance

            result = await get_autodev_vehicle_photos_impl(mock_cip, vehicle_id="VH-001")
            assert isinstance(result, str)
            instance.get_vehicle_photos.assert_called_once()

    async def test_photos_requires_vin_or_vehicle_id(self, mock_cip: CIP):
        result = await get_autodev_vehicle_photos_impl(mock_cip)
        assert "provide vin or vehicle_id" in result.lower()

    async def test_raw_client_error_returns_structured(self, mock_cip: CIP, monkeypatch):
        monkeypatch.setenv("AUTO_DEV_API_KEY", "test-key")
        with patch("auto_mcp.tools.autodev.AutoDevClient") as mock_client:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            instance.decode_vin = AsyncMock(
                side_effect=AutoDevClientError(
                    "Auto.dev unavailable",
                    code="NETWORK_ERROR",
                )
            )
            mock_client.return_value = instance

            result = await get_autodev_vin_decode_impl(
                mock_cip, vin="1HGCV1F39NA000001", raw=True
            )
            payload = json.loads(result)
            assert payload["_raw"] is True
            assert payload["data"]["error"] is True
            assert payload["data"]["code"] == "NETWORK_ERROR"


class TestAutoDevMCPWrappers:
    async def test_get_autodev_overview_wrapper_returns_string(self, monkeypatch):
        async def _fake(*_args, **_kwargs):
            return "overview-ok"

        monkeypatch.setattr("auto_mcp.server.get_autodev_overview_impl", _fake)
        result = await get_autodev_overview()
        assert isinstance(result, str)
        assert "overview-ok" in result

    async def test_get_autodev_vin_decode_wrapper_returns_string(self, monkeypatch):
        async def _fake(*_args, **_kwargs):
            return "decode-ok"

        monkeypatch.setattr("auto_mcp.server.get_autodev_vin_decode_impl", _fake)
        result = await get_autodev_vin_decode(vin="1HGCV1F39NA000001")
        assert isinstance(result, str)
        assert "decode-ok" in result

    async def test_get_autodev_listings_wrapper_returns_string(self, monkeypatch):
        async def _fake(*_args, **_kwargs):
            return "listings-ok"

        monkeypatch.setattr("auto_mcp.server.get_autodev_listings_impl", _fake)
        result = await get_autodev_listings(zip_code="78701")
        assert isinstance(result, str)
        assert "listings-ok" in result

    async def test_get_autodev_vehicle_photos_wrapper_returns_string(self, monkeypatch):
        async def _fake(*_args, **_kwargs):
            return "photos-ok"

        monkeypatch.setattr("auto_mcp.server.get_autodev_vehicle_photos_impl", _fake)
        result = await get_autodev_vehicle_photos(vin="1HGCV1F39NA000001")
        assert isinstance(result, str)
        assert "photos-ok" in result
