"""Tests for newly added funnel-expansion tool implementations."""

from __future__ import annotations

import json

from cip_protocol import CIP
from cip_protocol.llm.providers.mock import MockProvider

from auto_mcp.tools.engagement import (
    contact_dealer_impl,
    list_favorites_impl,
    list_saved_searches_impl,
    request_follow_up_impl,
    reserve_vehicle_impl,
    save_favorite_impl,
    save_search_impl,
    schedule_service_impl,
    submit_purchase_deposit_impl,
)
from auto_mcp.tools.financing_scenarios import compare_financing_scenarios_impl
from auto_mcp.tools.history import get_vehicle_history_impl
from auto_mcp.tools.market import get_market_price_context_impl
from auto_mcp.tools.ownership import (
    estimate_cost_of_ownership_impl,
    estimate_insurance_impl,
    estimate_out_the_door_price_impl,
)
from auto_mcp.tools.recommendations import get_similar_vehicles_impl
from auto_mcp.tools.warranty import get_warranty_info_impl


class TestSimilarVehicles:
    async def test_valid_request_calls_provider(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await get_similar_vehicles_impl(mock_cip, vehicle_id="VH-001", limit=3)
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_invalid_vehicle_id_skips_provider(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        result = await get_similar_vehicles_impl(mock_cip, vehicle_id="VH-999")
        assert "not found" in result.lower()
        assert mock_provider.call_count == 0

    async def test_raw_mode_skips_provider(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await get_similar_vehicles_impl(mock_cip, vehicle_id="VH-001", raw=True)
        payload = json.loads(result)
        assert payload["_raw"] is True
        assert payload["_tool"] == "get_similar_vehicles"
        assert payload["_meta"]["schema_version"] == 1
        assert mock_provider.call_count == 0


class TestVehicleHistory:
    async def test_valid_history(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await get_vehicle_history_impl(mock_cip, vehicle_id="VH-003")
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_missing_vehicle(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await get_vehicle_history_impl(mock_cip, vehicle_id="VH-999")
        assert "not found" in result.lower()
        assert mock_provider.call_count == 0


class TestOwnershipTools:
    async def test_cost_of_ownership(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await estimate_cost_of_ownership_impl(
            mock_cip,
            vehicle_id="VH-001",
            ownership_years=5,
        )
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_cost_of_ownership_rejects_years(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        result = await estimate_cost_of_ownership_impl(
            mock_cip,
            vehicle_id="VH-001",
            ownership_years=0,
        )
        assert "ownership years" in result.lower()
        assert mock_provider.call_count == 0

    async def test_market_price_context(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await get_market_price_context_impl(mock_cip, vehicle_id="VH-001")
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_market_context_passes_context_notes(
        self, mock_cip: CIP, mock_provider: MockProvider
    ):
        await get_market_price_context_impl(
            mock_cip,
            vehicle_id="VH-001",
            context_notes="Dealer wants repricing guidance only.",
        )
        assert "Context From Other Domains" in mock_provider.last_user_message
        assert "repricing guidance" in mock_provider.last_user_message

    async def test_out_the_door(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await estimate_out_the_door_price_impl(
            mock_cip,
            vehicle_id="VH-001",
            state="TX",
            trade_in_value=1000,
        )
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_insurance_estimate(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await estimate_insurance_impl(mock_cip, vehicle_id="VH-001", driver_age=33)
        assert isinstance(result, str)
        assert mock_provider.call_count == 1


class TestFinancingScenarios:
    async def test_compare_scenarios(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await compare_financing_scenarios_impl(
            mock_cip,
            vehicle_price=32000,
            down_payment_options=[0, 5000],
            loan_term_options=[48, 72],
        )
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_rejects_invalid_price(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await compare_financing_scenarios_impl(mock_cip, vehicle_price=0)
        assert "vehicle price" in result.lower()
        assert mock_provider.call_count == 0


class TestWarranty:
    async def test_warranty_info(self, mock_cip: CIP, mock_provider: MockProvider):
        result = await get_warranty_info_impl(mock_cip, vehicle_id="VH-017")
        assert isinstance(result, str)
        assert mock_provider.call_count == 1


class TestEngagementTools:
    def test_save_and_list_searches(self):
        save_result = save_search_impl(
            search_name="Affordable SUVs",
            customer_id="cust-1",
            body_type="suv",
            price_max=35000,
        )
        assert "saved search" in save_result.lower()

        list_result = list_saved_searches_impl(customer_id="cust-1")
        assert "affordable suvs" in list_result.lower()

    def test_save_favorite_and_list(self):
        save_result = save_favorite_impl(vehicle_id="VH-001", customer_id="cust-1")
        assert "saved" in save_result.lower()

        list_result = list_favorites_impl(customer_id="cust-1")
        assert "vh-001" in list_result.lower()

    def test_save_favorite_rejects_missing_vehicle(self):
        result = save_favorite_impl(vehicle_id="VH-999", customer_id="cust-1")
        assert "not found" in result.lower()

    def test_reserve_vehicle_duplicate_hold(self):
        first = reserve_vehicle_impl(
            vehicle_id="VH-001",
            customer_name="Pat Lee",
            customer_contact="pat@example.com",
            hold_hours=24,
        )
        assert "reservation hold created" in first.lower()

        second = reserve_vehicle_impl(
            vehicle_id="VH-001",
            customer_name="Alex Doe",
            customer_contact="alex@example.com",
            hold_hours=24,
        )
        assert "already has an active hold" in second.lower()

    def test_contact_dealer_requires_question(self):
        result = contact_dealer_impl(
            vehicle_id="VH-001",
            customer_name="Pat Lee",
            customer_contact="pat@example.com",
            question=" ",
        )
        assert "provide a question" in result.lower()

    def test_submit_deposit_requires_positive_amount(self):
        result = submit_purchase_deposit_impl(
            vehicle_id="VH-001",
            customer_name="Pat Lee",
            customer_contact="pat@example.com",
            deposit_amount=0,
        )
        assert "greater than 0" in result.lower()

    def test_schedule_service_rejects_bad_date(self):
        result = schedule_service_impl(
            vehicle_id="VH-001",
            customer_name="Pat Lee",
            customer_contact="pat@example.com",
            preferred_date="03/15/2026",
            service_type="oil_change",
        )
        assert "iso format" in result.lower()

    def test_request_follow_up_rejects_bad_channel(self):
        result = request_follow_up_impl(
            vehicle_id="VH-001",
            customer_name="Pat Lee",
            customer_contact="pat@example.com",
            preferred_channel="carrier_pigeon",
        )
        assert "preferred channel" in result.lower()
