"""Signature coverage for orchestration controls on server tool wrappers."""

from __future__ import annotations

import inspect

import pytest

import auto_mcp.server as server

ORCHESTRATION_PARAMS = {"provider", "scaffold_id", "policy", "context_notes", "raw"}
ORCHESTRATION_EXCEPT_PROVIDER = {"scaffold_id", "policy", "context_notes", "raw"}

CIP_ROUTED_TOOLS = [
    "search_vehicles",
    "search_by_location",
    "search_by_vin",
    "get_similar_vehicles",
    "get_vehicle_details",
    "compare_vehicles",
    "get_vehicle_history",
    "get_market_price_context",
    "get_warranty_info",
    "estimate_financing",
    "estimate_trade_in",
    "compare_financing_scenarios",
    "estimate_out_the_door_price",
    "estimate_insurance",
    "estimate_cost_of_ownership",
    "check_availability",
    "schedule_test_drive",
    "assess_purchase_readiness",
    "get_inventory_stats",
    "get_lead_analytics",
    "get_hot_leads",
    "get_lead_detail",
    "get_inventory_aging_report",
    "get_pricing_opportunities",
    "get_funnel_metrics",
]

NON_CIP_TOOLS = [
    "upsert_vehicle",
    "bulk_upsert_vehicles",
    "remove_vehicle",
    "expire_stale_listings",
    "record_lead",
    "record_sale",
    "bulk_import_from_api",
    "save_search",
    "list_saved_searches",
    "save_favorite",
    "list_favorites",
    "reserve_vehicle",
    "contact_dealer",
    "submit_purchase_deposit",
    "schedule_service",
    "request_follow_up",
    "set_llm_provider",
    "get_llm_provider",
]


@pytest.mark.parametrize("tool_name", CIP_ROUTED_TOOLS)
def test_cip_routed_tools_accept_orchestration_params(tool_name: str):
    fn = getattr(server, tool_name)
    params = set(inspect.signature(fn).parameters)
    assert ORCHESTRATION_PARAMS.issubset(params), (
        f"{tool_name} missing orchestration params: "
        f"{sorted(ORCHESTRATION_PARAMS - params)}"
    )


@pytest.mark.parametrize("tool_name", NON_CIP_TOOLS)
def test_non_cip_tools_do_not_accept_orchestration_params(tool_name: str):
    fn = getattr(server, tool_name)
    params = set(inspect.signature(fn).parameters)
    assert ORCHESTRATION_EXCEPT_PROVIDER.isdisjoint(params), (
        f"{tool_name} unexpectedly accepts orchestration params: "
        f"{sorted(ORCHESTRATION_EXCEPT_PROVIDER & params)}"
    )
    if tool_name != "set_llm_provider":
        assert "provider" not in params, f"{tool_name} should not expose provider override."
