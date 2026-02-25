"""Tool implementation tests — 2+ tests per tool (16+ total)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from cip_protocol import CIP
from cip_protocol.llm.providers.mock import MockProvider

from auto_mcp.tools.availability import check_availability_impl
from auto_mcp.tools.compare import compare_vehicles_impl
from auto_mcp.tools.details import get_vehicle_details_impl
from auto_mcp.tools.financing import estimate_financing_impl, estimate_trade_in_impl
from auto_mcp.tools.scheduling import (
    assess_purchase_readiness_impl,
    schedule_test_drive_impl,
)
from auto_mcp.tools.search import search_vehicles_impl

# ── search_vehicles ─────────────────────────────────────────────


class TestSearchVehicles:
    async def test_returns_string(self, mock_cip: CIP):
        result = await search_vehicles_impl(mock_cip, make="Toyota")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_provider_called(self, mock_cip: CIP, mock_provider: MockProvider):
        await search_vehicles_impl(mock_cip, body_type="truck")
        assert mock_provider.call_count == 1
        assert "truck" in mock_provider.last_user_message.lower()

    async def test_no_filters_returns_all(self, mock_cip: CIP, mock_provider: MockProvider):
        await search_vehicles_impl(mock_cip)
        assert mock_provider.call_count == 1
        assert "all vehicles" in mock_provider.last_user_message.lower()

    async def test_includes_vehicle_id_instruction(
        self, mock_cip: CIP, mock_provider: MockProvider
    ):
        await search_vehicles_impl(mock_cip, make="Toyota")
        assert "vehicle id" in mock_provider.last_user_message.lower()

    async def test_pagination_controls_pass_through(
        self, mock_cip: CIP, mock_provider: MockProvider
    ):
        await search_vehicles_impl(mock_cip, make="Toyota", limit=5, offset=10)
        assert "limit: 5" in mock_provider.last_user_message.lower()
        assert "offset: 10" in mock_provider.last_user_message.lower()

    async def test_rejects_invalid_limit(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await search_vehicles_impl(mock_cip, limit=0)
        assert "positive limit" in result.lower()
        assert mock_provider.call_count == 0

    async def test_raw_mode_returns_envelope_and_skips_provider(
        self, mock_cip: CIP, mock_provider: MockProvider
    ):
        result = await search_vehicles_impl(
            mock_cip,
            make="Toyota",
            raw=True,
            context_notes="Do not include this in raw output.",
        )
        payload = json.loads(result)
        assert payload["_raw"] is True
        assert payload["_tool"] == "search_vehicles"
        assert payload["_meta"]["schema_version"] == 1
        assert "data" in payload
        assert "orchestrator_notes" not in result
        assert mock_provider.call_count == 0

    async def test_context_notes_are_passed_to_prompt(
        self, mock_cip: CIP, mock_provider: MockProvider
    ):
        await search_vehicles_impl(
            mock_cip,
            make="Toyota",
            context_notes="First-time buyer; prioritize total ownership cost.",
        )
        assert "Context From Other Domains" in mock_provider.last_user_message
        assert "First-time buyer" in mock_provider.last_user_message

    async def test_policy_is_passed_to_cip(self, mock_cip: CIP, mock_provider: MockProvider):
        await search_vehicles_impl(
            mock_cip, make="Toyota", policy="skip disclaimers, compact mode"
        )
        assert "Required Disclaimers" not in mock_provider.last_system_message


# ── get_vehicle_details ─────────────────────────────────────────


class TestGetVehicleDetails:
    async def test_valid_id(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await get_vehicle_details_impl(mock_cip, vehicle_id="VH-001")
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_invalid_id_no_cip_call(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await get_vehicle_details_impl(mock_cip, vehicle_id="VH-999")
        assert "not found" in result.lower()
        assert mock_provider.call_count == 0


# ── compare_vehicles ────────────────────────────────────────────


class TestCompareVehicles:
    async def test_two_vehicles(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await compare_vehicles_impl(mock_cip, vehicle_ids=["VH-001", "VH-002"])
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_too_few_vehicles(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await compare_vehicles_impl(mock_cip, vehicle_ids=["VH-001"])
        assert "at least 2" in result.lower()
        assert mock_provider.call_count == 0

    async def test_invalid_id_in_list(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await compare_vehicles_impl(mock_cip, vehicle_ids=["VH-001", "VH-999"])
        assert "not found" in result.lower()
        assert mock_provider.call_count == 0

    async def test_too_many_vehicles(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await compare_vehicles_impl(
            mock_cip, vehicle_ids=["VH-001", "VH-002", "VH-003", "VH-004"]
        )
        assert "maximum of 3" in result.lower()
        assert mock_provider.call_count == 0


# ── estimate_financing ──────────────────────────────────────────


class TestEstimateFinancing:
    async def test_basic_calculation(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await estimate_financing_impl(
            mock_cip, vehicle_price=30000, down_payment=5000, loan_term_months=60
        )
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_down_payment_exceeds_price(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await estimate_financing_impl(
            mock_cip, vehicle_price=30000, down_payment=35000
        )
        assert "no financing" in result.lower()
        assert mock_provider.call_count == 0

    async def test_zero_apr(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await estimate_financing_impl(
            mock_cip, vehicle_price=30000, estimated_apr=0.0
        )
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_rejects_negative_vehicle_price(
        self, mock_cip: CIP, mock_provider: MockProvider
    ):
        result = await estimate_financing_impl(mock_cip, vehicle_price=-1)
        assert "vehicle price must be greater than or equal to 0" in result.lower()
        assert mock_provider.call_count == 0

    async def test_rejects_negative_down_payment(
        self, mock_cip: CIP, mock_provider: MockProvider
    ):
        result = await estimate_financing_impl(
            mock_cip, vehicle_price=30000, down_payment=-100
        )
        assert "down payment must be greater than or equal to 0" in result.lower()
        assert mock_provider.call_count == 0

    async def test_rejects_non_positive_loan_term(
        self, mock_cip: CIP, mock_provider: MockProvider
    ):
        result = await estimate_financing_impl(
            mock_cip, vehicle_price=30000, loan_term_months=0
        )
        assert "loan term must be greater than 0 months" in result.lower()
        assert mock_provider.call_count == 0

    async def test_rejects_negative_apr(
        self, mock_cip: CIP, mock_provider: MockProvider
    ):
        result = await estimate_financing_impl(
            mock_cip, vehicle_price=30000, estimated_apr=-1
        )
        assert "estimated apr must be greater than or equal to 0" in result.lower()
        assert mock_provider.call_count == 0


# ── estimate_trade_in ───────────────────────────────────────────


class TestEstimateTradeIn:
    async def test_known_vehicle(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await estimate_trade_in_impl(
            mock_cip, year=2021, make="Toyota", model="Camry", mileage=45000
        )
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_future_year(self, mock_cip: CIP, mock_provider: MockProvider):
        future_year = datetime.now(timezone.utc).year + 1
        result = await estimate_trade_in_impl(
            mock_cip, year=future_year, make="Toyota", model="Camry", mileage=100
        )
        assert "future" in result.lower()
        assert mock_provider.call_count == 0


# ── check_availability ──────────────────────────────────────────


class TestCheckAvailability:
    async def test_valid_vehicle(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await check_availability_impl(mock_cip, vehicle_id="VH-001", zip_code="78701")
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_invalid_vehicle(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await check_availability_impl(mock_cip, vehicle_id="VH-999")
        assert "not found" in result.lower()
        assert mock_provider.call_count == 0


# ── schedule_test_drive ─────────────────────────────────────────


class TestScheduleTestDrive:
    async def test_valid_request(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await schedule_test_drive_impl(
            mock_cip,
            vehicle_id="VH-001",
            preferred_date="2026-03-15",
            preferred_time="10:00 AM",
            customer_name="Jane Doe",
            customer_phone="555-0100",
        )
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_invalid_vehicle(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await schedule_test_drive_impl(
            mock_cip,
            vehicle_id="VH-999",
            preferred_date="2026-03-15",
            preferred_time="10:00 AM",
            customer_name="Jane Doe",
            customer_phone="555-0100",
        )
        assert "not found" in result.lower()
        assert mock_provider.call_count == 0


# ── assess_purchase_readiness ───────────────────────────────────


class TestAssessPurchaseReadiness:
    async def test_ready_customer(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await assess_purchase_readiness_impl(
            mock_cip,
            vehicle_id="VH-001",
            budget=35000,
            has_financing=True,
            has_insurance=True,
            has_trade_in=True,
        )
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_invalid_vehicle(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await assess_purchase_readiness_impl(
            mock_cip,
            vehicle_id="VH-999",
            budget=35000,
        )
        assert "not found" in result.lower()
        assert mock_provider.call_count == 0
