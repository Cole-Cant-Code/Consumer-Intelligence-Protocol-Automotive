"""Shared test fixtures — MockProvider injection, scaffold loading, cache clearing."""

from __future__ import annotations

from pathlib import Path

import pytest
from cip_protocol import CIP
from cip_protocol.llm.providers.mock import MockProvider
from cip_protocol.scaffold.matcher import clear_matcher_cache

from auto_mcp.config import AUTO_DOMAIN_CONFIG
from auto_mcp.data.inventory import set_store
from auto_mcp.data.seed import seed_demo_data
from auto_mcp.data.store import SqliteVehicleStore
from auto_mcp.server import set_cip_override

SCAFFOLD_DIR = str(Path(__file__).resolve().parent.parent / "auto_mcp" / "scaffolds")


@pytest.fixture()
def mock_provider() -> MockProvider:
    """A fresh MockProvider for each test."""
    return MockProvider("Mock LLM response for AutoCIP.")


@pytest.fixture()
def mock_cip(mock_provider: MockProvider) -> CIP:
    """CIP instance wired with real scaffolds + MockProvider."""
    return CIP.from_config(AUTO_DOMAIN_CONFIG, SCAFFOLD_DIR, mock_provider)


@pytest.fixture(autouse=True)
def _inject_mock_cip(mock_cip: CIP):
    """Auto-inject the mock CIP into the server singleton for every test."""
    set_cip_override(mock_cip)
    yield
    set_cip_override(None)


@pytest.fixture(autouse=True)
def _inject_test_store():
    """Give every test a fresh, isolated, seeded in-memory vehicle store."""
    store = SqliteVehicleStore(":memory:")
    seed_demo_data(store)
    set_store(store)
    yield
    set_store(None)


@pytest.fixture(autouse=True)
def _clear_matcher_cache():
    """Clear matcher cache before and after each test to prevent cross-test pollution."""
    clear_matcher_cache()
    yield
    clear_matcher_cache()
