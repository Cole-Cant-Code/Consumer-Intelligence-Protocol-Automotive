"""Tool implementation tests for dealer intelligence phases."""

from __future__ import annotations

import json

from cip_protocol import CIP
from cip_protocol.llm.providers.mock import MockProvider

from auto_mcp.data.inventory import get_vehicle, record_vehicle_lead
from auto_mcp.tools.dealer_intelligence import (
    get_funnel_metrics_impl,
    get_hot_leads_impl,
    get_inventory_aging_report_impl,
    get_lead_detail_impl,
    get_pricing_opportunities_impl,
)
from auto_mcp.tools.sales import record_sale_impl


class TestDealerLeadTools:
    async def test_get_hot_leads_returns_string(self, mock_cip: CIP, mock_provider: MockProvider):
        record_vehicle_lead("VH-001", "viewed", customer_id="cust-a")
        record_vehicle_lead("VH-001", "test_drive", customer_id="cust-a")

        result = await get_hot_leads_impl(mock_cip, min_score=0.0, limit=5)
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_get_lead_detail_missing_profile(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        result = await get_lead_detail_impl(mock_cip, lead_id="leadprof-missing")
        assert "not found" in result.lower()
        assert mock_provider.call_count == 0

    async def test_get_lead_detail_happy_path(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        lead_id = record_vehicle_lead("VH-002", "viewed", customer_id="cust-b")
        record_vehicle_lead("VH-002", "compared", lead_id=lead_id, customer_id="cust-b")

        result = await get_lead_detail_impl(mock_cip, lead_id=lead_id)
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_get_hot_leads_raw_mode_skips_provider(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        record_vehicle_lead("VH-004", "viewed", customer_id="cust-raw")
        result = await get_hot_leads_impl(mock_cip, min_score=0.0, raw=True)
        payload = json.loads(result)
        assert payload["_raw"] is True
        assert payload["_tool"] == "get_hot_leads"
        assert payload["_meta"]["schema_version"] == 1
        assert mock_provider.call_count == 0

    async def test_context_notes_pass_through_to_prompt(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        record_vehicle_lead("VH-005", "viewed", customer_id="cust-note")
        await get_hot_leads_impl(
            mock_cip,
            min_score=0.0,
            context_notes="Dealer principal wants compact actions only.",
        )
        assert "Context From Other Domains" in mock_provider.last_user_message
        assert "compact actions only" in mock_provider.last_user_message


class TestDealerInventoryTools:
    async def test_get_inventory_aging_report_returns_string(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        result = await get_inventory_aging_report_impl(mock_cip, min_days_on_lot=0, limit=20)
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_get_pricing_opportunities_returns_string(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        result = await get_pricing_opportunities_impl(mock_cip, limit=20)
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_policy_passthrough_affects_prompt(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        await get_pricing_opportunities_impl(mock_cip, limit=10, policy="skip disclaimers")
        assert "Required Disclaimers" not in mock_provider.last_system_message


class TestDealerFunnelAndSales:
    def test_record_sale_rejects_invalid_datetime(self):
        result = record_sale_impl(
            vehicle_id="VH-001",
            sold_price=28000,
            sold_at="02/20/2026",
        )
        assert "iso datetime" in result.lower()

    def test_record_sale_can_remove_vehicle(self):
        result = record_sale_impl(
            vehicle_id="VH-001",
            sold_price=28000,
            sold_at="2026-02-20T12:00:00+00:00",
            keep_vehicle_record=False,
        )
        assert "sale" in result.lower()
        assert get_vehicle("VH-001") is None

    async def test_get_funnel_metrics_returns_string(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        lead_id = record_vehicle_lead("VH-003", "viewed", customer_id="cust-c")
        record_vehicle_lead(
            "VH-003", "availability_check", lead_id=lead_id, customer_id="cust-c"
        )
        record_sale_impl(
            vehicle_id="VH-003",
            sold_price=24000,
            sold_at="2026-02-20T12:00:00+00:00",
            lead_id=lead_id,
        )

        result = await get_funnel_metrics_impl(mock_cip, days=30)
        assert isinstance(result, str)
        assert mock_provider.call_count == 1
