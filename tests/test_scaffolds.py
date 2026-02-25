"""Scaffold validation, routing, and content tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from cip_protocol.scaffold.loader import load_scaffold_directory
from cip_protocol.scaffold.registry import ScaffoldRegistry
from cip_protocol.scaffold.validator import validate_scaffold_directory

SCAFFOLD_DIR = str(Path(__file__).resolve().parent.parent / "auto_mcp" / "scaffolds")


@pytest.fixture()
def registry() -> ScaffoldRegistry:
    reg = ScaffoldRegistry()
    load_scaffold_directory(SCAFFOLD_DIR, reg)
    return reg


class TestScaffoldValidation:
    def test_all_scaffolds_valid(self):
        count, errors = validate_scaffold_directory(SCAFFOLD_DIR)
        assert count == 13
        assert len(errors) == 0

    def test_all_ids_unique(self, registry: ScaffoldRegistry):
        ids = [s.id for s in registry.all()]
        assert len(ids) == len(set(ids))

    def test_all_domain_auto_shopping(self, registry: ScaffoldRegistry):
        for scaffold in registry.all():
            assert scaffold.domain == "auto_shopping"


class TestScaffoldRouting:
    """Verify that each tool name routes to its expected scaffold."""

    @pytest.mark.parametrize(
        "tool_name,expected_scaffold_id",
        [
            ("search_vehicles", "vehicle_search"),
            ("compare_vehicles", "vehicle_comparison"),
            ("get_vehicle_details", "vehicle_details"),
            ("estimate_financing", "financing_overview"),
            ("estimate_trade_in", "trade_in_estimate"),
            ("check_availability", "availability_check"),
            ("schedule_test_drive", "test_drive_schedule"),
            ("assess_purchase_readiness", "purchase_readiness"),
        ],
    )
    def test_tool_routes_to_scaffold(
        self, registry: ScaffoldRegistry, tool_name: str, expected_scaffold_id: str
    ):
        matches = registry.find_by_tool(tool_name)
        assert len(matches) >= 1, f"No scaffold found for tool '{tool_name}'"
        assert matches[0].id == expected_scaffold_id

    def test_unknown_tool_not_found(self, registry: ScaffoldRegistry):
        matches = registry.find_by_tool("nonexistent_tool")
        assert len(matches) == 0


class TestScaffoldContent:
    """Verify scaffold content quality."""

    def test_all_have_disclaimers(self, registry: ScaffoldRegistry):
        for scaffold in registry.all():
            assert len(scaffold.guardrails.disclaimers) >= 1, (
                f"Scaffold '{scaffold.id}' missing disclaimers"
            )

    def test_all_have_reasoning_steps(self, registry: ScaffoldRegistry):
        for scaffold in registry.all():
            steps = scaffold.reasoning_framework.get("steps", [])
            assert len(steps) >= 1, (
                f"Scaffold '{scaffold.id}' missing reasoning steps"
            )

    def test_financing_has_heavy_guardrails(self, registry: ScaffoldRegistry):
        matches = registry.find_by_tool("estimate_financing")
        assert len(matches) >= 1
        scaffold = matches[0]
        assert len(scaffold.guardrails.disclaimers) >= 3
        assert len(scaffold.guardrails.prohibited_actions) >= 2
