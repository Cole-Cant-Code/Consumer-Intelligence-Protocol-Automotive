"""Server wrapper tests for funnel-expansion MCP tools."""

from __future__ import annotations

from auto_mcp.server import (
    compare_financing_scenarios,
    contact_dealer,
    estimate_cost_of_ownership,
    estimate_insurance,
    estimate_out_the_door_price,
    get_market_price_context,
    get_similar_vehicles,
    get_vehicle_history,
    get_warranty_info,
    list_favorites,
    list_saved_searches,
    request_follow_up,
    reserve_vehicle,
    save_favorite,
    save_search,
    schedule_service,
    submit_purchase_deposit,
)


class TestFunnelWrappers:
    async def test_get_similar_vehicles_returns_string(self):
        result = await get_similar_vehicles(vehicle_id="VH-001", limit=3)
        assert isinstance(result, str)

    async def test_get_vehicle_history_returns_string(self):
        result = await get_vehicle_history(vehicle_id="VH-001")
        assert isinstance(result, str)

    async def test_estimate_cost_of_ownership_returns_string(self):
        result = await estimate_cost_of_ownership(vehicle_id="VH-001")
        assert isinstance(result, str)

    async def test_get_market_price_context_returns_string(self):
        result = await get_market_price_context(vehicle_id="VH-001")
        assert isinstance(result, str)

    async def test_compare_financing_scenarios_returns_string(self):
        result = await compare_financing_scenarios(vehicle_price=30000)
        assert isinstance(result, str)

    async def test_estimate_out_the_door_price_returns_string(self):
        result = await estimate_out_the_door_price(vehicle_id="VH-001")
        assert isinstance(result, str)

    async def test_estimate_insurance_returns_string(self):
        result = await estimate_insurance(vehicle_id="VH-001")
        assert isinstance(result, str)

    async def test_get_warranty_info_returns_string(self):
        result = await get_warranty_info(vehicle_id="VH-001")
        assert isinstance(result, str)

    def test_search_save_and_list_flow_returns_strings(self):
        save_result = save_search(
            search_name="My SUV Search",
            customer_id="cust-2",
            body_type="suv",
            price_max=40000,
        )
        assert isinstance(save_result, str)

        list_result = list_saved_searches(customer_id="cust-2")
        assert isinstance(list_result, str)

    def test_favorite_flow_returns_strings(self):
        save_result = save_favorite(vehicle_id="VH-001", customer_id="cust-2")
        assert isinstance(save_result, str)

        list_result = list_favorites(customer_id="cust-2")
        assert isinstance(list_result, str)

    def test_conversion_and_post_purchase_flows_return_strings(self):
        reserve_result = reserve_vehicle(
            vehicle_id="VH-001",
            customer_name="Sam User",
            customer_contact="sam@example.com",
        )
        assert isinstance(reserve_result, str)

        message_result = contact_dealer(
            vehicle_id="VH-001",
            customer_name="Sam User",
            customer_contact="sam@example.com",
            question="Does this include the tech package?",
        )
        assert isinstance(message_result, str)

        deposit_result = submit_purchase_deposit(
            vehicle_id="VH-001",
            customer_name="Sam User",
            customer_contact="sam@example.com",
            deposit_amount=1000,
        )
        assert isinstance(deposit_result, str)

        service_result = schedule_service(
            vehicle_id="VH-001",
            customer_name="Sam User",
            customer_contact="sam@example.com",
            preferred_date="2026-03-20",
            service_type="first_service",
        )
        assert isinstance(service_result, str)

        follow_result = request_follow_up(
            vehicle_id="VH-001",
            customer_name="Sam User",
            customer_contact="sam@example.com",
            topic="warranty onboarding",
        )
        assert isinstance(follow_result, str)
