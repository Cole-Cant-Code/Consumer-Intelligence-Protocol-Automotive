"""Tests for lead escalation detection, storage, and tool implementations."""

from __future__ import annotations

import json

from cip_protocol import CIP
from cip_protocol.llm.providers.mock import MockProvider

from auto_mcp.data.inventory import get_store, record_vehicle_lead
from auto_mcp.data.store import SqliteVehicleStore
from auto_mcp.escalation.detector import (
    ESCALATION_TRANSITIONS,
    check_escalation,
    clear_callbacks,
    register_callback,
)
from auto_mcp.escalation.store import EscalationStore
from auto_mcp.tools.escalation import (
    acknowledge_escalation_impl,
    get_escalations_impl,
)

# ── Helpers ───────────────────────────────────────────────────────


def _esc_store() -> EscalationStore:
    """Return the EscalationStore from the active test store."""
    store = get_store()
    assert isinstance(store, SqliteVehicleStore)
    assert store._escalation_store is not None
    return store._escalation_store


# ── Detector unit tests ──────────────────────────────────────────


class TestDetector:
    def test_same_status_returns_none(self):
        result = check_escalation(
            lead_id="L-1",
            old_status="new",
            new_status="new",
            score=5.0,
            vehicle_id="VH-001",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="viewed",
        )
        assert result is None

    def test_cold_to_warm(self):
        result = check_escalation(
            lead_id="L-2",
            old_status="new",
            new_status="engaged",
            score=12.0,
            vehicle_id="VH-001",
            customer_name="Alice",
            customer_contact="alice@test.com",
            source_channel="web",
            action="compared",
        )
        assert result is not None
        assert result["escalation_type"] == "cold_to_warm"
        assert result["lead_id"] == "L-2"
        assert result["id"].startswith("esc-")

    def test_warm_to_hot(self):
        result = check_escalation(
            lead_id="L-3",
            old_status="engaged",
            new_status="qualified",
            score=25.0,
            vehicle_id="VH-002",
            customer_name="Bob",
            customer_contact="",
            source_channel="direct",
            action="test_drive",
        )
        assert result is not None
        assert result["escalation_type"] == "warm_to_hot"

    def test_cold_to_hot(self):
        result = check_escalation(
            lead_id="L-4",
            old_status="new",
            new_status="qualified",
            score=30.0,
            vehicle_id="VH-003",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="purchase_deposit",
        )
        assert result is not None
        assert result["escalation_type"] == "cold_to_hot"

    def test_terminal_transition_returns_none(self):
        """Transitions to terminal states (won/lost) are not in the map."""
        result = check_escalation(
            lead_id="L-5",
            old_status="qualified",
            new_status="won",
            score=30.0,
            vehicle_id="VH-001",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="sale_closed",
        )
        assert result is None

    def test_all_transitions_covered(self):
        """Sanity check — the transition map has exactly 3 entries."""
        assert len(ESCALATION_TRANSITIONS) == 3

    def test_callback_fires(self):
        captured: list[dict] = []
        register_callback(lambda esc: captured.append(esc))
        try:
            check_escalation(
                lead_id="cb-1",
                old_status="new",
                new_status="engaged",
                score=15.0,
                vehicle_id="VH-001",
                customer_name="",
                customer_contact="",
                source_channel="direct",
                action="financed",
            )
            assert len(captured) == 1
            assert captured[0]["lead_id"] == "cb-1"
        finally:
            clear_callbacks()

    def test_callback_error_does_not_propagate(self):
        def bad_callback(esc: dict) -> None:
            raise RuntimeError("boom")

        register_callback(bad_callback)
        try:
            result = check_escalation(
                lead_id="cb-err",
                old_status="new",
                new_status="engaged",
                score=12.0,
                vehicle_id="VH-001",
                customer_name="",
                customer_contact="",
                source_channel="direct",
                action="compared",
            )
            assert result is not None  # should still return despite callback error
        finally:
            clear_callbacks()


# ── EscalationStore unit tests ───────────────────────────────────


class TestEscalationStore:
    def test_save_and_get_pending(self):
        esc_store = _esc_store()
        esc = check_escalation(
            lead_id="S-1",
            old_status="new",
            new_status="engaged",
            score=14.0,
            vehicle_id="VH-001",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="compared",
        )
        esc_store.save(esc)
        pending = esc_store.get_pending()
        assert any(e["id"] == esc["id"] for e in pending)

    def test_mark_delivered_removes_from_pending(self):
        esc_store = _esc_store()
        esc = check_escalation(
            lead_id="S-2",
            old_status="engaged",
            new_status="qualified",
            score=25.0,
            vehicle_id="VH-002",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="test_drive",
        )
        esc_store.save(esc)
        assert esc_store.mark_delivered(esc["id"])
        pending = esc_store.get_pending()
        assert not any(e["id"] == esc["id"] for e in pending)

    def test_mark_delivered_returns_false_for_unknown_id(self):
        assert not _esc_store().mark_delivered("esc-nonexistent")

    def test_has_active_escalation(self):
        esc_store = _esc_store()
        esc = check_escalation(
            lead_id="S-3",
            old_status="new",
            new_status="engaged",
            score=12.0,
            vehicle_id="VH-001",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="viewed",
        )
        esc_store.save(esc)
        assert esc_store.has_active_escalation("S-3", "cold_to_warm")
        assert not esc_store.has_active_escalation("S-3", "warm_to_hot")

    def test_has_active_escalation_false_after_delivery(self):
        esc_store = _esc_store()
        esc = check_escalation(
            lead_id="S-4",
            old_status="new",
            new_status="engaged",
            score=12.0,
            vehicle_id="VH-001",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="compared",
        )
        esc_store.save(esc)
        esc_store.mark_delivered(esc["id"])
        assert not esc_store.has_active_escalation("S-4", "cold_to_warm")

    def test_get_pending_filter_by_type(self):
        esc_store = _esc_store()
        e1 = check_escalation(
            lead_id="F-1",
            old_status="new",
            new_status="engaged",
            score=12.0,
            vehicle_id="VH-001",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="compared",
        )
        e2 = check_escalation(
            lead_id="F-2",
            old_status="engaged",
            new_status="qualified",
            score=25.0,
            vehicle_id="VH-002",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="test_drive",
        )
        esc_store.save(e1)
        esc_store.save(e2)

        warm = esc_store.get_pending(escalation_type="cold_to_warm")
        hot = esc_store.get_pending(escalation_type="warm_to_hot")
        assert any(e["id"] == e1["id"] for e in warm)
        assert not any(e["id"] == e2["id"] for e in warm)
        assert any(e["id"] == e2["id"] for e in hot)

    def test_get_all_includes_delivered(self):
        esc_store = _esc_store()
        esc = check_escalation(
            lead_id="A-1",
            old_status="new",
            new_status="engaged",
            score=12.0,
            vehicle_id="VH-001",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="compared",
        )
        esc_store.save(esc)
        esc_store.mark_delivered(esc["id"])
        all_escs = esc_store.get_all()
        assert any(e["id"] == esc["id"] for e in all_escs)

    def test_get_all_filter_by_type(self):
        esc_store = _esc_store()
        cold_to_warm = check_escalation(
            lead_id="ALL-1",
            old_status="new",
            new_status="engaged",
            score=12.0,
            vehicle_id="VH-001",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="compared",
        )
        warm_to_hot = check_escalation(
            lead_id="ALL-2",
            old_status="engaged",
            new_status="qualified",
            score=24.0,
            vehicle_id="VH-002",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="test_drive",
        )
        esc_store.save(cold_to_warm)
        esc_store.save(warm_to_hot)

        filtered = esc_store.get_all(limit=10, days=30, escalation_type="cold_to_warm")
        assert any(e["id"] == cold_to_warm["id"] for e in filtered)
        assert not any(e["id"] == warm_to_hot["id"] for e in filtered)

    def test_duplicate_save_ignored(self):
        esc_store = _esc_store()
        esc = check_escalation(
            lead_id="D-1",
            old_status="new",
            new_status="engaged",
            score=12.0,
            vehicle_id="VH-001",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="compared",
        )
        esc_store.save(esc)
        esc_store.save(esc)  # should not raise
        pending = esc_store.get_pending()
        count = sum(1 for e in pending if e["id"] == esc["id"])
        assert count == 1


# ── Tool implementation tests ────────────────────────────────────


class TestEscalationTools:
    async def test_get_escalations_returns_string(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        esc_store = _esc_store()
        esc = check_escalation(
            lead_id="T-1",
            old_status="new",
            new_status="engaged",
            score=14.0,
            vehicle_id="VH-001",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="compared",
        )
        esc_store.save(esc)
        result = await get_escalations_impl(mock_cip, esc_store, limit=10)
        assert isinstance(result, str)
        assert mock_provider.call_count == 1

    async def test_get_escalations_raw_mode(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        esc_store = _esc_store()
        result = await get_escalations_impl(mock_cip, esc_store, limit=10, raw=True)
        payload = json.loads(result)
        assert payload["_raw"] is True
        assert payload["_tool"] == "get_escalations"
        assert mock_provider.call_count == 0

    async def test_get_escalations_empty(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        esc_store = _esc_store()
        result = await get_escalations_impl(mock_cip, esc_store, limit=10)
        assert isinstance(result, str)

    async def test_get_escalations_invalid_limit(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        esc_store = _esc_store()
        result = await get_escalations_impl(mock_cip, esc_store, limit=0)
        assert "greater than 0" in result.lower()
        assert mock_provider.call_count == 0

    async def test_get_escalations_invalid_days_when_include_delivered(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        esc_store = _esc_store()
        result = await get_escalations_impl(
            mock_cip,
            esc_store,
            include_delivered=True,
            days=0,
        )
        assert "days must be greater than 0" in result.lower()
        assert mock_provider.call_count == 0

    async def test_get_escalations_include_delivered_applies_type_filter(
        self,
        mock_cip: CIP,
        mock_provider: MockProvider,
    ):
        esc_store = _esc_store()
        cold_to_warm = check_escalation(
            lead_id="TOOL-1",
            old_status="new",
            new_status="engaged",
            score=12.0,
            vehicle_id="VH-001",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="compared",
        )
        warm_to_hot = check_escalation(
            lead_id="TOOL-2",
            old_status="engaged",
            new_status="qualified",
            score=24.0,
            vehicle_id="VH-002",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="test_drive",
        )
        esc_store.save(cold_to_warm)
        esc_store.save(warm_to_hot)

        raw_result = await get_escalations_impl(
            mock_cip,
            esc_store,
            include_delivered=True,
            escalation_type="cold_to_warm",
            days=30,
            raw=True,
        )
        payload = json.loads(raw_result)
        types = {e["escalation_type"] for e in payload["data"]["escalations"]}
        assert types == {"cold_to_warm"}
        assert mock_provider.call_count == 0

    def test_acknowledge_escalation_happy_path(self):
        esc_store = _esc_store()
        esc = check_escalation(
            lead_id="A-ack",
            old_status="new",
            new_status="engaged",
            score=12.0,
            vehicle_id="VH-001",
            customer_name="",
            customer_contact="",
            source_channel="direct",
            action="compared",
        )
        esc_store.save(esc)
        result = acknowledge_escalation_impl(esc_store, escalation_id=esc["id"])
        assert "acknowledged" in result.lower()

    def test_acknowledge_escalation_missing_id(self):
        result = acknowledge_escalation_impl(_esc_store(), escalation_id="")
        assert "required" in result.lower()

    def test_acknowledge_escalation_unknown_id(self):
        result = acknowledge_escalation_impl(
            _esc_store(), escalation_id="esc-nonexistent"
        )
        assert "not found" in result.lower()


# ── Integration: record_lead triggers escalation ─────────────────


class TestRecordLeadEscalation:
    def test_cold_to_warm_escalation_fires(self):
        """Enough events to cross the engaged threshold (≥10) should create an escalation."""
        esc_store = _esc_store()

        # financed (6) + availability_check (5) = 11 → engaged
        lead_id = record_vehicle_lead("VH-001", "financed", customer_id="int-1")
        record_vehicle_lead("VH-001", "availability_check", lead_id=lead_id)

        pending = esc_store.get_pending(escalation_type="cold_to_warm")
        assert any(e["lead_id"] == lead_id for e in pending)

    def test_warm_to_hot_escalation_fires(self):
        """Cross engaged (≥10) and then qualified (≥22) thresholds."""
        esc_store = _esc_store()

        # First cross to engaged: financed (6) + availability_check (5) = 11
        lead_id = record_vehicle_lead("VH-002", "financed", customer_id="int-2")
        record_vehicle_lead("VH-002", "availability_check", lead_id=lead_id)

        # Now cross to qualified: + test_drive (8) + reserve_vehicle (9) = 28
        record_vehicle_lead("VH-002", "test_drive", lead_id=lead_id)
        record_vehicle_lead("VH-002", "reserve_vehicle", lead_id=lead_id)

        hot_pending = esc_store.get_pending(escalation_type="warm_to_hot")
        assert any(e["lead_id"] == lead_id for e in hot_pending)

    def test_no_duplicate_escalation_for_same_transition(self):
        """Multiple events that keep the same status should not create duplicates."""
        esc_store = _esc_store()

        # Cross to engaged: financed (6) + availability_check (5) = 11
        lead_id = record_vehicle_lead("VH-003", "financed", customer_id="int-3")
        record_vehicle_lead("VH-003", "availability_check", lead_id=lead_id)

        # More events that stay in engaged (score still < 22)
        record_vehicle_lead("VH-003", "compared", lead_id=lead_id)  # +3 = 14
        record_vehicle_lead("VH-003", "viewed", lead_id=lead_id)  # +1 = 15

        warm_pending = esc_store.get_pending(escalation_type="cold_to_warm")
        matches = [e for e in warm_pending if e["lead_id"] == lead_id]
        assert len(matches) == 1

    def test_no_escalation_below_threshold(self):
        """Low-weight events that don't cross a threshold produce no escalation."""
        esc_store = _esc_store()

        # viewed (1) + viewed (1) + compared (3) = 5 → still "new"
        lead_id = record_vehicle_lead("VH-004", "viewed", customer_id="int-4")
        record_vehicle_lead("VH-004", "viewed", lead_id=lead_id)
        record_vehicle_lead("VH-004", "compared", lead_id=lead_id)

        pending = esc_store.get_pending()
        assert not any(e["lead_id"] == lead_id for e in pending)
