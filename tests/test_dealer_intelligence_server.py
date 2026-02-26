"""Server wrapper tests for dealer-intelligence MCP tools."""

from __future__ import annotations

from auto_mcp.data.inventory import get_vehicle, record_vehicle_lead
from auto_mcp.server import (
    get_funnel_metrics,
    get_hot_leads,
    get_inventory_aging_report,
    get_lead_detail,
    get_pricing_opportunities,
    record_lead,
    record_sale,
)


class TestDealerIntelligenceWrappers:
    async def test_get_hot_leads_returns_string(self):
        record_vehicle_lead("VH-001", "viewed", customer_id="srv-cust-a")
        result = await get_hot_leads(min_score=0)
        assert isinstance(result, str)

    async def test_get_lead_detail_returns_string(self):
        lead_id = record_vehicle_lead("VH-002", "viewed", customer_id="srv-cust-b")
        result = await get_lead_detail(lead_id=lead_id)
        assert isinstance(result, str)

    async def test_inventory_aging_and_pricing_tools_return_string(self):
        aging = await get_inventory_aging_report(min_days_on_lot=0, limit=10)
        pricing = await get_pricing_opportunities(limit=10)
        assert isinstance(aging, str)
        assert isinstance(pricing, str)

    async def test_get_funnel_metrics_returns_string(self):
        lead_id = record_vehicle_lead("VH-003", "viewed", customer_id="srv-cust-c")
        record_vehicle_lead(
            "VH-003",
            "availability_check",
            lead_id=lead_id,
            customer_id="srv-cust-c",
        )
        sale = record_sale(
            vehicle_id="VH-003",
            sold_price=25000,
            sold_at="2026-02-20T12:00:00+00:00",
            lead_id=lead_id,
        )
        assert isinstance(sale, str)

        result = await get_funnel_metrics(days=30)
        assert isinstance(result, str)

    def test_record_lead_backwards_compatible_signature(self):
        result = record_lead(vehicle_id="VH-004", action="viewed", user_query="legacy")
        assert "lead event recorded" in result.lower()

    def test_record_lead_accepts_vehicle_view_alias(self):
        result = record_lead(vehicle_id="VH-004", action="vehicle_view")
        assert "lead event recorded" in result.lower()
        assert "action: viewed" in result.lower()

    def test_record_lead_with_identity_fields(self):
        result = record_lead(
            vehicle_id="VH-005",
            action="viewed",
            customer_id="srv-cust-d",
            session_id="sess-123",
            customer_name="Alex Smith",
            customer_contact="alex@example.com",
            source_channel="organic",
        )
        assert "lead_id" in result.lower()

    def test_record_sale_keep_vehicle_record_false(self):
        result = record_sale(
            vehicle_id="VH-006",
            sold_price=21000,
            sold_at="2026-02-20T12:00:00+00:00",
            keep_vehicle_record=False,
        )
        assert "sale" in result.lower()
        assert get_vehicle("VH-006") is None
