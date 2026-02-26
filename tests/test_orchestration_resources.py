"""Tests for orchestration MCP resources and prompt exposure."""

from __future__ import annotations

from auto_mcp.server import (
    orchestration_entry_prompt,
    orchestration_entry_resource,
    scaffold_catalog_resource,
)


class TestOrchestrationResources:
    def test_scaffold_catalog_resource_exposes_catalog(self):
        payload = scaffold_catalog_resource()
        assert payload["domain"] == "auto_shopping"
        assert payload["default_scaffold_id"] == "general_advice"
        assert payload["count"] >= 35

        ids = {entry["id"] for entry in payload["scaffolds"]}
        assert "orchestration_entry" in ids
        assert "vehicle_search" in ids
        assert "autodev_data" in ids

    def test_orchestration_entry_resource_includes_catalog(self):
        payload = orchestration_entry_resource()
        assert "orchestration_entry" in payload
        assert "scaffold_catalog" in payload
        assert payload["orchestration_entry"]["id"] == "orchestration_entry"
        assert payload["scaffold_catalog"]["count"] >= 35

    def test_orchestration_entry_prompt_non_empty(self):
        text = orchestration_entry_prompt()
        assert isinstance(text, str)
        assert "orchestration_entry" in text
        assert "scaffold_catalog" in text
