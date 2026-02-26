"""Server integration tests — MCP tool wrappers, guardrails, and data integrity."""

from __future__ import annotations

from cip_protocol import CIP
from cip_protocol.llm.providers.mock import MockProvider

import auto_mcp.server as server_mod
from auto_mcp.data.inventory import get_vehicle, search_vehicles
from auto_mcp.data.seed import DEMO_VEHICLES as VEHICLES
from auto_mcp.server import (
    assess_purchase_readiness,
    bulk_import_from_api,
    bulk_upsert_vehicles,
    check_availability,
    compare_vehicles,
    estimate_financing,
    estimate_trade_in,
    get_llm_provider,
    get_vehicle_details,
    remove_vehicle,
    schedule_test_drive,
    set_cip_override,
    set_llm_provider,
    upsert_vehicle,
)
from auto_mcp.server import (
    search_vehicles as mcp_search_vehicles,
)

# ── MCP tool wrapper tests ──────────────────────────────────────


class TestMCPToolWrappers:
    """Verify that MCP-registered functions return strings and work end-to-end."""

    async def test_search_vehicles_returns_string(self):
        result = await mcp_search_vehicles(make="Toyota")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_get_vehicle_details_returns_string(self):
        result = await get_vehicle_details(vehicle_id="VH-001")
        assert isinstance(result, str)

    async def test_compare_vehicles_returns_string(self):
        result = await compare_vehicles(vehicle_ids=["VH-001", "VH-002"])
        assert isinstance(result, str)

    async def test_estimate_financing_returns_string(self):
        result = await estimate_financing(vehicle_price=30000)
        assert isinstance(result, str)

    async def test_estimate_trade_in_returns_string(self):
        result = await estimate_trade_in(year=2021, make="Toyota", model="Camry", mileage=50000)
        assert isinstance(result, str)

    async def test_check_availability_returns_string(self):
        result = await check_availability(vehicle_id="VH-001")
        assert isinstance(result, str)

    async def test_schedule_test_drive_returns_string(self):
        result = await schedule_test_drive(
            vehicle_id="VH-001",
            preferred_date="2026-03-15",
            preferred_time="10:00 AM",
            customer_name="Test User",
            customer_phone="555-0100",
        )
        assert isinstance(result, str)

    async def test_assess_purchase_readiness_returns_string(self):
        result = await assess_purchase_readiness(
            vehicle_id="VH-001", budget=35000
        )
        assert isinstance(result, str)

    async def test_search_wrapper_sanitizes_internal_errors(self, monkeypatch):
        async def _raise(*_args, **_kwargs):
            raise RuntimeError("simulated-failure")

        monkeypatch.setattr("auto_mcp.server.search_vehicles_impl", _raise)
        result = await mcp_search_vehicles(make="Toyota")
        assert "having trouble searching vehicles" in result.lower()
        assert "simulated-failure" not in result.lower()

    async def test_search_wrapper_accepts_orchestration_params(self):
        result = await mcp_search_vehicles(
            make="Toyota",
            provider="anthropic",
            scaffold_id="vehicle_search",
            policy="compact mode",
            context_notes="Dealer asks for concise response.",
            raw=False,
        )
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_invalid_scaffold_id_fails_fast(self):
        result = await mcp_search_vehicles(make="Toyota", scaffold_id="missing_scaffold")
        assert "unknown scaffold_id" in result.lower()
        assert "missing_scaffold" in result

    async def test_provider_override_is_forwarded(self, monkeypatch, mock_cip: CIP):
        captured: dict[str, str] = {}

        def _fake_prepare_cip_orchestration(**kwargs):
            captured["provider"] = kwargs["provider"]
            return mock_cip, None, None, None

        monkeypatch.setattr(
            server_mod,
            "_prepare_cip_orchestration",
            _fake_prepare_cip_orchestration,
        )
        await mcp_search_vehicles(make="Toyota", provider="openai")
        assert captured["provider"] == "openai"


def _reset_provider_state() -> None:
    pool = server_mod._pool
    pool._pool.clear()
    pool._provider_models.clear()
    pool._default_provider = ""
    pool.set_override(None)


class TestProviderPool:
    def test_provider_pool_builds_lazily_and_caches(self, monkeypatch):
        _reset_provider_state()
        monkeypatch.delenv("CIP_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("CIP_LLM_MODEL", raising=False)

        builds: list[tuple[str, str]] = []
        pool = server_mod._pool

        def _fake_build(provider: str, model: str = "") -> object:
            builds.append((provider, model))
            return {"provider": provider, "model": model}

        monkeypatch.setattr(pool, "_build", _fake_build)

        anth_1 = pool.get("anthropic")
        anth_2 = pool.get("anthropic")
        openai_1 = pool.get("openai")

        assert anth_1 is anth_2
        assert anth_1 is not openai_1
        assert builds == [("anthropic", ""), ("openai", "")]

    def test_default_provider_is_used_when_not_specified(self, monkeypatch):
        _reset_provider_state()
        monkeypatch.setenv("CIP_LLM_PROVIDER", "openai")
        monkeypatch.delenv("CIP_LLM_MODEL", raising=False)

        builds: list[tuple[str, str]] = []
        pool = server_mod._pool

        def _fake_build(provider: str, model: str = "") -> object:
            builds.append((provider, model))
            return {"provider": provider, "model": model}

        monkeypatch.setattr(pool, "_build", _fake_build)

        resolved = pool.get()
        assert resolved == {"provider": "openai", "model": ""}
        assert builds == [("openai", "")]

    def test_set_cip_override_still_wins(self, mock_cip: CIP):
        _reset_provider_state()
        set_cip_override(mock_cip)
        assert server_mod._pool.get("anthropic") is mock_cip

    def test_set_llm_provider_persists_model_per_provider(self, monkeypatch):
        _reset_provider_state()
        monkeypatch.delenv("CIP_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("CIP_LLM_MODEL", raising=False)

        builds: list[tuple[str, str]] = []
        pool = server_mod._pool

        def _fake_build(provider: str, model: str = "") -> object:
            builds.append((provider, model))
            return {"provider": provider, "model": model}

        monkeypatch.setattr(pool, "_build", _fake_build)

        msg_a = set_llm_provider("anthropic", "claude-custom")
        msg_b = set_llm_provider("openai", "gpt-custom")

        assert "anthropic/claude-custom" in msg_a
        assert "openai/gpt-custom" in msg_b
        assert pool._provider_models["anthropic"] == "claude-custom"
        assert pool._provider_models["openai"] == "gpt-custom"
        assert builds == [("anthropic", "claude-custom"), ("openai", "gpt-custom")]

    def test_get_llm_provider_keeps_legacy_prefix_and_pool_details(self, monkeypatch):
        _reset_provider_state()
        monkeypatch.delenv("CIP_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("CIP_LLM_MODEL", raising=False)

        pool = server_mod._pool

        def _fake_build(provider: str, model: str = "") -> object:
            return {"provider": provider, "model": model}

        monkeypatch.setattr(pool, "_build", _fake_build)

        set_llm_provider("anthropic", "claude-test")
        status = get_llm_provider()

        assert status.startswith("anthropic/claude-test")
        assert "default=anthropic" in status
        assert "pool=[" in status


# ── Adversarial guardrail tests ─────────────────────────────────


class TestGuardrails:
    """Test that CIP guardrails flag prohibited content from the mock provider."""

    async def test_prohibited_purchase_decision(self, mock_cip: CIP, mock_provider: MockProvider):
        mock_provider.response_content = "You should definitely buy this car right now!"
        result = await mock_cip.run(
            "Should I buy this car?",
            tool_name="get_vehicle_details",
            data_context={"vehicle": {"make": "Toyota", "model": "Camry"}},
        )
        # The response should be flagged by guardrails
        assert len(result.response.guardrail_flags) > 0

    async def test_prohibited_financial_guarantee(
        self, mock_cip: CIP, mock_provider: MockProvider
    ):
        mock_provider.response_content = (
            "I guarantee your rate will be 3.9% and you will definitely get approved."
        )
        result = await mock_cip.run(
            "What rate can I get?",
            tool_name="estimate_financing",
            data_context={"vehicle_price": 30000},
        )
        assert len(result.response.guardrail_flags) > 0

    async def test_regex_apr_promise(self, mock_cip: CIP, mock_provider: MockProvider):
        mock_provider.response_content = "Your APR will be 4.5% based on your profile."
        result = await mock_cip.run(
            "What APR can I expect?",
            tool_name="estimate_financing",
            data_context={"vehicle_price": 30000},
        )
        assert len(result.response.guardrail_flags) > 0


# ── Mock data integrity ────────────────────────────────────────


class TestDataIntegrity:
    """Verify mock inventory meets requirements."""

    def test_minimum_vehicle_count(self):
        assert len(VEHICLES) >= 30

    def test_unique_ids(self):
        ids = [v["id"] for v in VEHICLES]
        assert len(ids) == len(set(ids))

    def test_unique_vins(self):
        vins = [v["vin"] for v in VEHICLES]
        assert len(vins) == len(set(vins))

    def test_required_fields_present(self):
        required = {
            "id", "year", "make", "model", "trim", "body_type", "price",
            "mileage", "exterior_color", "interior_color", "fuel_type",
            "mpg_city", "mpg_highway", "engine", "transmission", "drivetrain",
            "features", "safety_rating", "dealer_name", "dealer_location",
            "availability_status", "vin",
        }
        for v in VEHICLES:
            missing = required - set(v.keys())
            assert not missing, f"Vehicle {v.get('id', '?')} missing fields: {missing}"

    def test_all_body_types_represented(self):
        body_types = {v["body_type"] for v in VEHICLES}
        assert "sedan" in body_types
        assert "suv" in body_types
        assert "truck" in body_types

    def test_all_fuel_types_represented(self):
        fuel_types = {v["fuel_type"] for v in VEHICLES}
        assert "gasoline" in fuel_types
        assert "electric" in fuel_types
        assert "hybrid" in fuel_types

    def test_get_vehicle_returns_correct(self):
        v = get_vehicle("VH-001")
        assert v is not None
        assert v["make"] == "Toyota"

    def test_get_vehicle_none_for_missing(self):
        assert get_vehicle("VH-999") is None

    def test_search_filters_by_make(self):
        results = search_vehicles(make="Toyota")
        assert all(v["make"] == "Toyota" for v in results)
        assert len(results) >= 1

    def test_search_filters_by_price_range(self):
        results = search_vehicles(price_min=40000, price_max=50000)
        assert all(40000 <= v["price"] <= 50000 for v in results)


# ── Ingestion tool integration tests ──────────────────────────


class TestIngestionTools:
    """Verify MCP ingestion tools work end-to-end."""

    def test_upsert_vehicle_new(self):
        result = upsert_vehicle(vehicle={
            "id": "VH-100", "year": 2025, "make": "Rivian", "model": "R1S",
            "trim": "Adventure", "body_type": "suv", "price": 78_000,
            "fuel_type": "electric",
        })
        assert "upserted" in result
        assert get_vehicle("VH-100") is not None

    def test_upsert_vehicle_accepts_null_optional_numeric_fields(self):
        result = upsert_vehicle(vehicle={
            "id": "VH-104",
            "year": 2025,
            "make": "Rivian",
            "model": "R1S",
            "body_type": "suv",
            "price": 78_000,
            "fuel_type": "electric",
            "mileage": None,
            "mpg_city": None,
            "mpg_highway": None,
        })
        assert "upserted" in result.lower()
        vehicle = get_vehicle("VH-104")
        assert vehicle is not None
        assert vehicle["mileage"] == 0
        assert vehicle["mpg_city"] == 0
        assert vehicle["mpg_highway"] == 0

    def test_bulk_upsert_vehicles(self):
        result = bulk_upsert_vehicles(vehicles=[
            {"id": "VH-200", "year": 2025, "make": "Lucid", "model": "Air",
             "trim": "Pure", "body_type": "sedan", "price": 70_000, "fuel_type": "electric"},
            {"id": "VH-201", "year": 2025, "make": "Polestar", "model": "2",
             "trim": "Long Range", "body_type": "sedan", "price": 49_800, "fuel_type": "electric"},
        ])
        assert "2 vehicle(s) upserted" in result
        assert get_vehicle("VH-200") is not None
        assert get_vehicle("VH-201") is not None

    def test_upsert_vehicle_maps_common_alias_fields(self):
        result = upsert_vehicle(vehicle={
            "id": "VH-ALIAS-001",
            "year": 2024,
            "make": "Toyota",
            "model": "Camry",
            "bodyStyle": "Sedan",
            "msrp": "$31,250",
            "fuelType": "Gasoline",
            "dealerZip": "78701",
            "displayColor": "Midnight Black",
        })
        assert "upserted" in result.lower()

        vehicle = get_vehicle("VH-ALIAS-001")
        assert vehicle is not None
        assert vehicle["body_type"] == "sedan"
        assert vehicle["price"] == 31250.0
        assert vehicle["fuel_type"] == "gasoline"
        assert vehicle["dealer_zip"] == "78701"
        assert vehicle["exterior_color"] == "Midnight Black"

    def test_upsert_vehicle_accepts_missing_vin_with_soft_warning(self):
        result = upsert_vehicle(vehicle={
            "id": "VH-SOFTVIN-001",
            "year": 2025,
            "make": "Rivian",
            "model": "R1T",
            "body_type": "truck",
            "price": 69_995,
            "fuel_type": "electric",
        })
        assert "upserted" in result.lower()
        assert "warning" in result.lower()

        vehicle = get_vehicle("VH-SOFTVIN-001")
        assert vehicle is not None
        assert vehicle["source"] == "manual_low_confidence"

    def test_upsert_vehicle_backfills_missing_fields_from_vin_decode(self, monkeypatch):
        monkeypatch.setattr(
            "auto_mcp.tools.ingestion._decode_vin_nhtsa",
            lambda _vin: {
                "year": 2023,
                "make": "Honda",
                "model": "Accord",
                "trim": "Sport",
                "body_type": "sedan",
                "fuel_type": "gasoline",
            },
        )

        result = upsert_vehicle(vehicle={
            "id": "VH-VINDECODE-001",
            "vin": "1HGCM82633A004352",
            "price": 27_500,
        })

        assert "upserted successfully" in result.lower()
        vehicle = get_vehicle("VH-VINDECODE-001")
        assert vehicle is not None
        assert vehicle["year"] == 2023
        assert vehicle["make"] == "Honda"
        assert vehicle["model"] == "Accord"
        assert vehicle["trim"] == "Sport"
        assert vehicle["body_type"] == "sedan"
        assert vehicle["fuel_type"] == "gasoline"
        assert vehicle["source"] == "manual"

    def test_bulk_upsert_vehicles_returns_warning_summary_for_soft_vin(self):
        result = bulk_upsert_vehicles(vehicles=[
            {
                "id": "VH-BULK-SOFTVIN-001",
                "year": 2025,
                "make": "Nissan",
                "model": "Rogue",
                "body_type": "suv",
                "price": 30_500,
                "fuel_type": "gasoline",
            },
            {
                "id": "VH-BULK-SOFTVIN-002",
                "year": 2024,
                "make": "Hyundai",
                "model": "Ioniq 5",
                "body_type": "suv",
                "price": 42_990,
                "fuel_type": "electric",
            },
        ])

        assert "2 vehicle(s) upserted" in result.lower()
        assert "warning" in result.lower()
        first = get_vehicle("VH-BULK-SOFTVIN-001")
        second = get_vehicle("VH-BULK-SOFTVIN-002")
        assert first is not None and first["source"] == "manual_low_confidence"
        assert second is not None and second["source"] == "manual_low_confidence"

    def test_remove_vehicle(self):
        # Ensure it exists first
        assert get_vehicle("VH-001") is not None
        result = remove_vehicle(vehicle_id="VH-001")
        assert "removed" in result
        assert get_vehicle("VH-001") is None

    def test_upsert_vehicle_rejects_non_dict_payload(self):
        result = upsert_vehicle(vehicle="not-a-dict")  # type: ignore[arg-type]
        assert "must be a dict" in result.lower()

    def test_upsert_vehicle_rejects_missing_required_fields(self):
        result = upsert_vehicle(vehicle={
            "id": "VH-101",
            "year": 2025,
            "model": "R1S",
            "body_type": "suv",
            "price": 78_000,
            "fuel_type": "electric",
        })
        assert "missing required field" in result.lower()
        assert "make" in result.lower()
        assert get_vehicle("VH-101") is None

    def test_upsert_vehicle_rejects_invalid_year_type(self):
        result = upsert_vehicle(vehicle={
            "id": "VH-102",
            "year": "2025",
            "make": "Rivian",
            "model": "R1S",
            "body_type": "suv",
            "price": 78_000,
            "fuel_type": "electric",
        })
        assert "field 'year' must be an integer" in result.lower()
        assert get_vehicle("VH-102") is None

    def test_upsert_vehicle_rejects_negative_price(self):
        result = upsert_vehicle(vehicle={
            "id": "VH-103",
            "year": 2025,
            "make": "Rivian",
            "model": "R1S",
            "body_type": "suv",
            "price": -1,
            "fuel_type": "electric",
        })
        assert "field 'price' must be greater than or equal to 0" in result.lower()
        assert get_vehicle("VH-103") is None

    def test_bulk_upsert_vehicles_rejects_non_list_payload(self):
        result = bulk_upsert_vehicles(vehicles="not-a-list")  # type: ignore[arg-type]
        assert "must be a list of dicts" in result.lower()

    def test_bulk_upsert_vehicles_rejects_non_dict_entry(self):
        result = bulk_upsert_vehicles(
            vehicles=[
                {
                    "id": "VH-300",
                    "year": 2025,
                    "make": "Test",
                    "model": "Valid",
                    "body_type": "sedan",
                    "price": 10_000,
                    "fuel_type": "gasoline",
                },
                "bad-entry",
            ]  # type: ignore[list-item]
        )
        assert "index 1" in result.lower()
        assert "must be a dict" in result.lower()
        assert get_vehicle("VH-300") is None

    def test_bulk_upsert_validation_is_all_or_nothing(self):
        result = bulk_upsert_vehicles(vehicles=[
            {
                "id": "VH-310",
                "year": 2025,
                "make": "Lucid",
                "model": "Air",
                "body_type": "sedan",
                "price": 70_000,
                "fuel_type": "electric",
            },
            {
                "id": "VH-311",
                "year": 2025,
                "make": "Polestar",
                "model": "2",
                "body_type": "sedan",
                "price": 49_800,
            },
        ])
        assert "missing required field" in result.lower()
        assert "fuel_type" in result.lower()
        assert get_vehicle("VH-310") is None
        assert get_vehicle("VH-311") is None

    def test_upsert_vehicle_wrapper_handles_internal_error(self, monkeypatch):
        def _raise(_vehicle):
            raise RuntimeError("simulated-failure")

        monkeypatch.setattr("auto_mcp.server.upsert_vehicle_impl", _raise)
        result = upsert_vehicle(vehicle={"id": "VH-ERR"})
        assert "having trouble saving that vehicle" in result.lower()
        assert "simulated-failure" not in result.lower()

    def test_bulk_upsert_wrapper_handles_internal_error(self, monkeypatch):
        def _raise(_vehicles):
            raise RuntimeError("simulated-failure")

        monkeypatch.setattr("auto_mcp.server.bulk_upsert_vehicles_impl", _raise)
        result = bulk_upsert_vehicles(vehicles=[])
        assert "having trouble saving those vehicles" in result.lower()
        assert "simulated-failure" not in result.lower()

    async def test_bulk_import_rejects_unsupported_source(self):
        result = await bulk_import_from_api(source="nhtsa", dry_run=True)
        assert "unsupported source" in result.lower()
        assert "auto_dev" in result.lower()

    async def test_bulk_import_uses_pipeline_and_zip_scope(self, monkeypatch):
        calls: dict[str, object] = {}

        async def _fake_run(self, metros=None, **kwargs):  # noqa: ANN001
            calls["metros"] = metros
            calls.update(kwargs)
            return {
                "total_fetched": 12,
                "normalized": 8,
                "deduped": 7,
                "nhtsa_enriched": 2,
                "upserted": 0,
                "errors": [],
            }

        monkeypatch.setenv("AUTO_DEV_API_KEY", "test-key")
        monkeypatch.setattr(
            "auto_mcp.ingestion.pipeline.IngestionPipeline.run_auto_dev", _fake_run,
        )

        result = await bulk_import_from_api(
            source="auto_dev",
            zip_code="90210",
            make="Tesla",
            model="Model 3",
            dry_run=True,
        )

        assert "dry run" in result.lower()
        assert "would import 7 vehicles" in result.lower()
        assert calls["zip_codes"] == ["90210"]
        assert calls["make"] == "Tesla"
        assert calls["model"] == "Model 3"
        assert calls["enrich_nhtsa_data"] is True

    def test_remove_vehicle_wrapper_handles_internal_error(self, monkeypatch):
        def _raise(_vehicle_id):
            raise RuntimeError("simulated-failure")

        monkeypatch.setattr("auto_mcp.server.remove_vehicle_impl", _raise)
        result = remove_vehicle(vehicle_id="VH-001")
        assert "having trouble removing that vehicle" in result.lower()
        assert "simulated-failure" not in result.lower()
