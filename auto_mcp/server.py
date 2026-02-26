"""AutoCIP MCP server — FastMCP entry point with expanded funnel tooling."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from cip_protocol import CIP
from cip_protocol.orchestration.errors import (
    log_and_return_tool_error as _log_and_return_tool_error,
)
from cip_protocol.orchestration.pool import ProviderPool
from cip_protocol.scaffold.loader import load_scaffold_directory
from cip_protocol.scaffold.registry import ScaffoldRegistry
from mcp.server.fastmcp import FastMCP

from auto_mcp.config import AUTO_DOMAIN_CONFIG
from auto_mcp.tools.autodev import (
    get_autodev_listings_impl,
    get_autodev_overview_impl,
    get_autodev_vehicle_photos_impl,
    get_autodev_vin_decode_impl,
)
from auto_mcp.tools.availability import check_availability_impl
from auto_mcp.tools.compare import compare_vehicles_impl
from auto_mcp.tools.dealer_intelligence import (
    get_funnel_metrics_impl,
    get_hot_leads_impl,
    get_inventory_aging_report_impl,
    get_lead_detail_impl,
    get_pricing_opportunities_impl,
)
from auto_mcp.tools.details import get_vehicle_details_impl
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
from auto_mcp.tools.escalation import (
    acknowledge_escalation_impl,
    get_escalations_impl,
)
from auto_mcp.tools.financing import estimate_financing_impl, estimate_trade_in_impl
from auto_mcp.tools.financing_scenarios import compare_financing_scenarios_impl
from auto_mcp.tools.history import get_vehicle_history_impl
from auto_mcp.tools.ingestion import (
    bulk_import_impl,
    bulk_upsert_vehicles_impl,
    expire_stale_impl,
    record_lead_impl,
    remove_vehicle_impl,
    upsert_vehicle_impl,
)
from auto_mcp.tools.location_search import search_by_location_impl
from auto_mcp.tools.market import get_market_price_context_impl
from auto_mcp.tools.nhtsa import (
    get_nhtsa_complaints_impl,
    get_nhtsa_recalls_impl,
    get_nhtsa_safety_ratings_impl,
)
from auto_mcp.tools.ownership import (
    estimate_cost_of_ownership_impl,
    estimate_insurance_impl,
    estimate_out_the_door_price_impl,
)
from auto_mcp.tools.recommendations import get_similar_vehicles_impl
from auto_mcp.tools.sales import record_sale_impl
from auto_mcp.tools.scheduling import (
    assess_purchase_readiness_impl,
    schedule_test_drive_impl,
)
from auto_mcp.tools.search import search_vehicles_impl
from auto_mcp.tools.stats import get_inventory_stats_impl, get_lead_analytics_impl
from auto_mcp.tools.vin_search import search_by_vin_impl
from auto_mcp.tools.warranty import get_warranty_info_impl

# Load .env from project root (no extra dependency)
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if _ENV_FILE.is_file():
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

mcp = FastMCP("AutoCIP")
logger = logging.getLogger(__name__)

_SCAFFOLD_DIR = str(Path(__file__).parent / "scaffolds")

_pool = ProviderPool(AUTO_DOMAIN_CONFIG, _SCAFFOLD_DIR)

_escalation_store_ref: object | None = None
_scaffold_registry_ref: ScaffoldRegistry | None = None


def _get_escalation_store():
    """Lazy accessor — enables escalations on the SQLite store on first call."""
    global _escalation_store_ref  # noqa: PLW0603
    if _escalation_store_ref is None:
        from auto_mcp.data.inventory import get_store
        from auto_mcp.data.store import SqliteVehicleStore

        store = get_store()
        if isinstance(store, SqliteVehicleStore):
            _escalation_store_ref = store.enable_escalations()
    return _escalation_store_ref


def _get_scaffold_registry() -> ScaffoldRegistry:
    """Lazy scaffold registry accessor for resources/prompts."""
    global _scaffold_registry_ref  # noqa: PLW0603
    if _scaffold_registry_ref is None:
        reg = ScaffoldRegistry()
        load_scaffold_directory(_SCAFFOLD_DIR, reg)
        _scaffold_registry_ref = reg
    return _scaffold_registry_ref


def _compact_scaffold_entry(scaffold: Any) -> dict[str, Any]:
    """Build a concise, stable scaffold catalog entry."""
    applicability = scaffold.applicability
    return {
        "id": scaffold.id,
        "display_name": scaffold.display_name,
        "description": scaffold.description,
        "tools": list(applicability.tools or []),
        "intent_signals": list(applicability.intent_signals or []),
        "keywords": list(applicability.keywords or []),
        "tags": list(scaffold.tags or []),
    }


def _build_scaffold_catalog_payload() -> dict[str, Any]:
    reg = _get_scaffold_registry()
    scaffolds = sorted(reg.all(), key=lambda s: s.id)
    entries = [_compact_scaffold_entry(s) for s in scaffolds]
    return {
        "domain": AUTO_DOMAIN_CONFIG.name,
        "default_scaffold_id": AUTO_DOMAIN_CONFIG.default_scaffold_id,
        "count": len(entries),
        "scaffolds": entries,
    }


def _build_orchestration_entry_payload() -> dict[str, Any]:
    reg = _get_scaffold_registry()
    scaffold = reg.get("orchestration_entry")
    if scaffold is None:
        return {
            "error": True,
            "message": "orchestration_entry scaffold is not available.",
        }

    return {
        "orchestration_entry": {
            "id": scaffold.id,
            "display_name": scaffold.display_name,
            "description": scaffold.description,
            "reasoning_framework": scaffold.reasoning_framework,
            "domain_knowledge_activation": scaffold.domain_knowledge_activation,
            "guardrails": {
                "disclaimers": scaffold.guardrails.disclaimers,
                "escalation_triggers": scaffold.guardrails.escalation_triggers,
                "prohibited_actions": scaffold.guardrails.prohibited_actions,
            },
            "tags": list(scaffold.tags or []),
        },
        "scaffold_catalog": _build_scaffold_catalog_payload(),
    }


@mcp.resource("autocip://scaffolds/catalog")
def scaffold_catalog_resource() -> dict[str, Any]:
    """List available scaffold_id values with routing hints for orchestrators."""
    return _build_scaffold_catalog_payload()


@mcp.resource("autocip://orchestration/entry")
def orchestration_entry_resource() -> dict[str, Any]:
    """Expose orchestration entry guidance plus the scaffold catalog."""
    return _build_orchestration_entry_payload()


@mcp.prompt()
def orchestration_entry_prompt() -> str:
    """Prompt-friendly orchestration briefing with scaffold catalog."""
    payload = _build_orchestration_entry_payload()
    return (
        "Use this orchestration entry and scaffold catalog when selecting "
        "`scaffold_id` values for AutoCIP tool calls.\n\n"
        f"{json.dumps(payload, indent=2)}"
    )


def set_cip_override(cip: CIP | None) -> None:
    """Inject a CIP instance (e.g. with MockProvider) for testing."""
    _pool.set_override(cip)


def _prepare_cip_orchestration(
    *,
    tool_name: str,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
) -> tuple[CIP, str | None, str | None, str | None]:
    return _pool.prepare_orchestration(
        tool_name=tool_name,
        provider=provider,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
    )


# ── Tool registrations ──────────────────────────────────────────────


@mcp.tool()
def set_llm_provider(provider: str, model: str = "") -> str:
    """Set the default LLM provider used for CIP reasoning.

    provider: 'anthropic' or 'openai'
    model: optional model override (defaults to claude-sonnet-4-6 / gpt-4o)
    """
    try:
        return _pool.set_provider(provider, model)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="set_llm_provider",
            exc=exc,
            user_message=f"Failed to switch to {provider}: check API key is set.",
        )


@mcp.tool()
def get_llm_provider() -> str:
    """Return current default provider/model and initialized provider pool details."""
    return _pool.get_info()


@mcp.tool()
async def search_vehicles(
    make: str = "",
    model: str = "",
    year_min: int | None = None,
    year_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    body_type: str = "",
    fuel_type: str = "",
    limit: int = 10,
    offset: int = 0,
    include_sold: bool = False,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Search vehicles with pagination.

    Sold units are excluded unless include_sold=true.
    """
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="search_vehicles",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await search_vehicles_impl(
            cip,
            make=make or None,
            model=model or None,
            year_min=year_min,
            year_max=year_max,
            price_min=price_min,
            price_max=price_max,
            body_type=body_type or None,
            fuel_type=fuel_type or None,
            limit=limit,
            offset=offset,
            include_sold=include_sold,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="search_vehicles",
            exc=exc,
            user_message=(
                "I am having trouble searching vehicles right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_vehicle_details(
    vehicle_id: str,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Get detailed specifications and information about a specific vehicle by ID."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_vehicle_details",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_vehicle_details_impl(
            cip,
            vehicle_id=vehicle_id,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_vehicle_details",
            exc=exc,
            user_message=(
                "I am having trouble retrieving vehicle details right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def compare_vehicles(
    vehicle_ids: list[str],
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Compare 2-3 vehicles side by side. Provide a list of vehicle IDs."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="compare_vehicles",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await compare_vehicles_impl(
            cip,
            vehicle_ids=vehicle_ids,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="compare_vehicles",
            exc=exc,
            user_message=(
                "I am having trouble comparing vehicles right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def estimate_financing(
    vehicle_price: float,
    down_payment: float = 0.0,
    loan_term_months: int = 60,
    estimated_apr: float = 6.5,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Estimate monthly payments for a vehicle purchase. All figures are estimates only."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="estimate_financing",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await estimate_financing_impl(
            cip,
            vehicle_price=vehicle_price,
            down_payment=down_payment,
            loan_term_months=loan_term_months,
            estimated_apr=estimated_apr,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="estimate_financing",
            exc=exc,
            user_message=(
                "I am having trouble estimating financing right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def estimate_trade_in(
    year: int,
    make: str,
    model: str,
    mileage: int,
    condition: str = "good",
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Estimate trade-in value based on year, make, model, mileage, and condition."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="estimate_trade_in",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await estimate_trade_in_impl(
            cip,
            year=year,
            make=make,
            model=model,
            mileage=mileage,
            condition=condition,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="estimate_trade_in",
            exc=exc,
            user_message=(
                "I am having trouble estimating trade-in value right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def check_availability(
    vehicle_id: str,
    zip_code: str = "",
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Check if a specific vehicle is currently available and get dealer information."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="check_availability",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await check_availability_impl(
            cip,
            vehicle_id=vehicle_id,
            zip_code=zip_code,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="check_availability",
            exc=exc,
            user_message=(
                "I am having trouble checking availability right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def schedule_test_drive(
    vehicle_id: str,
    preferred_date: str,
    preferred_time: str,
    customer_name: str,
    customer_phone: str,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Request a test drive appointment for a specific vehicle."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="schedule_test_drive",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await schedule_test_drive_impl(
            cip,
            vehicle_id=vehicle_id,
            preferred_date=preferred_date,
            preferred_time=preferred_time,
            customer_name=customer_name,
            customer_phone=customer_phone,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="schedule_test_drive",
            exc=exc,
            user_message=(
                "I am having trouble scheduling a test drive right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def assess_purchase_readiness(
    vehicle_id: str,
    budget: float,
    has_financing: bool = False,
    has_insurance: bool = False,
    has_trade_in: bool = False,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Assess how ready you are to purchase a specific vehicle based on your situation."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="assess_purchase_readiness",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await assess_purchase_readiness_impl(
            cip,
            vehicle_id=vehicle_id,
            budget=budget,
            has_financing=has_financing,
            has_insurance=has_insurance,
            has_trade_in=has_trade_in,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="assess_purchase_readiness",
            exc=exc,
            user_message=(
                "I am having trouble assessing purchase readiness right now. "
                "Please try again in a moment."
            ),
        )


# ── New CIP-integrated tools ───────────────────────────────────────


@mcp.tool()
async def search_by_location(
    zip_code: str,
    radius_miles: float = 50.0,
    make: str = "",
    model: str = "",
    year_min: int | None = None,
    year_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    body_type: str = "",
    fuel_type: str = "",
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Search for vehicles near a ZIP code within a given radius."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="search_by_location",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await search_by_location_impl(
            cip,
            zip_code=zip_code,
            radius_miles=radius_miles,
            make=make or None,
            model=model or None,
            year_min=year_min,
            year_max=year_max,
            price_min=price_min,
            price_max=price_max,
            body_type=body_type or None,
            fuel_type=fuel_type or None,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="search_by_location",
            exc=exc,
            user_message=(
                "I am having trouble searching by location right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def search_by_vin(
    vin: str,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Look up a specific vehicle by its 17-character VIN."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="search_by_vin",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await search_by_vin_impl(
            cip,
            vin=vin,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="search_by_vin",
            exc=exc,
            user_message=(
                "I am having trouble looking up that VIN right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_inventory_stats(
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Get comprehensive inventory statistics including coverage, pricing, and freshness."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_inventory_stats",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_inventory_stats_impl(
            cip,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_inventory_stats",
            exc=exc,
            user_message=(
                "I am having trouble retrieving inventory stats right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_lead_analytics(
    days: int = 30,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Get lead engagement analytics for dealer reporting over a specified period."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_lead_analytics",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_lead_analytics_impl(
            cip,
            days=days,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_lead_analytics",
            exc=exc,
            user_message=(
                "I am having trouble retrieving lead analytics right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_hot_leads(
    limit: int = 10,
    min_score: float = 10.0,
    dealer_zip: str = "",
    days: int = 30,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Get highest-intent leads ranked by engagement score."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_hot_leads",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_hot_leads_impl(
            cip,
            limit=limit,
            min_score=min_score,
            dealer_zip=dealer_zip,
            days=days,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_hot_leads",
            exc=exc,
            user_message=(
                "I am having trouble retrieving hot leads right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_lead_detail(
    lead_id: str,
    days: int = 90,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Get timeline and score details for a specific lead profile."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_lead_detail",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_lead_detail_impl(
            cip,
            lead_id=lead_id,
            days=days,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_lead_detail",
            exc=exc,
            user_message=(
                "I am having trouble retrieving that lead detail right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_inventory_aging_report(
    min_days_on_lot: int = 30,
    limit: int = 100,
    dealer_zip: str = "",
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Get inventory aging and velocity report to identify stale units."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_inventory_aging_report",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_inventory_aging_report_impl(
            cip,
            min_days_on_lot=min_days_on_lot,
            limit=limit,
            dealer_zip=dealer_zip,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_inventory_aging_report",
            exc=exc,
            user_message=(
                "I am having trouble retrieving inventory aging right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_pricing_opportunities(
    limit: int = 25,
    stale_days_threshold: int = 45,
    overpriced_threshold_pct: float = 5.0,
    underpriced_threshold_pct: float = -5.0,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Get prioritized pricing opportunities based on market and aging signals."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_pricing_opportunities",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_pricing_opportunities_impl(
            cip,
            limit=limit,
            stale_days_threshold=stale_days_threshold,
            overpriced_threshold_pct=overpriced_threshold_pct,
            underpriced_threshold_pct=underpriced_threshold_pct,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_pricing_opportunities",
            exc=exc,
            user_message=(
                "I am having trouble retrieving pricing opportunities right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_funnel_metrics(
    days: int = 30,
    dealer_zip: str = "",
    breakdown_by: str = "none",
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Get closed-loop funnel conversion metrics through sale outcomes."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_funnel_metrics",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_funnel_metrics_impl(
            cip,
            days=days,
            dealer_zip=dealer_zip,
            breakdown_by=breakdown_by,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_funnel_metrics",
            exc=exc,
            user_message=(
                "I am having trouble retrieving funnel metrics right now. "
                "Please try again in a moment."
            ),
        )


# ── Funnel-expansion tools ────────────────────────────────────────


@mcp.tool()
async def get_similar_vehicles(
    vehicle_id: str,
    limit: int = 5,
    prefer_lower_price: bool = True,
    max_price: float | None = None,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Recommend similar vehicles, optionally with a cheaper-price bias."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_similar_vehicles",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_similar_vehicles_impl(
            cip,
            vehicle_id=vehicle_id,
            limit=limit,
            prefer_lower_price=prefer_lower_price,
            max_price=max_price,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_similar_vehicles",
            exc=exc,
            user_message=(
                "I am having trouble finding similar vehicles right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_vehicle_history(
    vehicle_id: str,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Get a history summary for a vehicle (title, accidents, ownership, recalls)."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_vehicle_history",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_vehicle_history_impl(
            cip,
            vehicle_id=vehicle_id,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_vehicle_history",
            exc=exc,
            user_message=(
                "I am having trouble retrieving vehicle history right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def estimate_cost_of_ownership(
    vehicle_id: str,
    annual_miles: int = 12_000,
    ownership_years: int = 5,
    driver_age: int = 35,
    gas_price_per_gallon: float = 3.80,
    electricity_price_per_kwh: float = 0.16,
    insurance_zip_code: str = "",
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Estimate ownership cost including fuel/energy, maintenance, and insurance."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="estimate_cost_of_ownership",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await estimate_cost_of_ownership_impl(
            cip,
            vehicle_id=vehicle_id,
            annual_miles=annual_miles,
            ownership_years=ownership_years,
            driver_age=driver_age,
            gas_price_per_gallon=gas_price_per_gallon,
            electricity_price_per_kwh=electricity_price_per_kwh,
            insurance_zip_code=insurance_zip_code,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="estimate_cost_of_ownership",
            exc=exc,
            user_message=(
                "I am having trouble estimating ownership costs right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_market_price_context(
    vehicle_id: str,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Assess market pricing context and deal quality for a vehicle listing."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_market_price_context",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_market_price_context_impl(
            cip,
            vehicle_id=vehicle_id,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_market_price_context",
            exc=exc,
            user_message=(
                "I am having trouble evaluating market pricing right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def compare_financing_scenarios(
    vehicle_price: float,
    down_payment_options: list[float] | None = None,
    loan_term_options: list[int] | None = None,
    estimated_apr: float = 6.5,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Compare multiple financing scenarios across down payments and loan terms."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="compare_financing_scenarios",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await compare_financing_scenarios_impl(
            cip,
            vehicle_price=vehicle_price,
            down_payment_options=down_payment_options,
            loan_term_options=loan_term_options,
            estimated_apr=estimated_apr,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="compare_financing_scenarios",
            exc=exc,
            user_message=(
                "I am having trouble comparing financing scenarios right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def estimate_out_the_door_price(
    vehicle_id: str,
    state: str = "TX",
    trade_in_value: float = 0.0,
    tax_rate: float | None = None,
    title_fee: float = 85.0,
    registration_fee: float = 150.0,
    doc_fee: float = 225.0,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Estimate out-the-door price with taxes and common fees."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="estimate_out_the_door_price",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await estimate_out_the_door_price_impl(
            cip,
            vehicle_id=vehicle_id,
            state=state,
            trade_in_value=trade_in_value,
            tax_rate=tax_rate,
            title_fee=title_fee,
            registration_fee=registration_fee,
            doc_fee=doc_fee,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="estimate_out_the_door_price",
            exc=exc,
            user_message=(
                "I am having trouble estimating out-the-door pricing right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def estimate_insurance(
    vehicle_id: str,
    driver_age: int = 35,
    annual_miles: int = 12_000,
    zip_code: str = "",
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Estimate insurance cost range for a vehicle and basic driver profile."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="estimate_insurance",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await estimate_insurance_impl(
            cip,
            vehicle_id=vehicle_id,
            driver_age=driver_age,
            annual_miles=annual_miles,
            zip_code=zip_code,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="estimate_insurance",
            exc=exc,
            user_message=(
                "I am having trouble estimating insurance right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_warranty_info(
    vehicle_id: str,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Summarize likely warranty coverage windows for a vehicle."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_warranty_info",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_warranty_info_impl(
            cip,
            vehicle_id=vehicle_id,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_warranty_info",
            exc=exc,
            user_message=(
                "I am having trouble retrieving warranty information right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_autodev_overview(
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Get Auto.dev account overview and usage context."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_autodev_overview",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_autodev_overview_impl(
            cip,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_autodev_overview",
            exc=exc,
            user_message=(
                "I am having trouble retrieving Auto.dev overview data right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_autodev_vin_decode(
    vin: str,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Decode a VIN using Auto.dev."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_autodev_vin_decode",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_autodev_vin_decode_impl(
            cip,
            vin=vin,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_autodev_vin_decode",
            exc=exc,
            user_message=(
                "I am having trouble decoding that VIN with Auto.dev right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_autodev_listings(
    vin: str = "",
    zip_code: str = "",
    distance_miles: int = 50,
    make: str = "",
    model: str = "",
    price_min: float | None = None,
    price_max: float | None = None,
    page: int = 1,
    limit: int = 25,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Fetch Auto.dev listings by VIN or search filters."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_autodev_listings",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_autodev_listings_impl(
            cip,
            vin=vin or None,
            zip_code=zip_code,
            distance_miles=distance_miles,
            make=make or None,
            model=model or None,
            price_min=price_min,
            price_max=price_max,
            page=page,
            limit=limit,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_autodev_listings",
            exc=exc,
            user_message=(
                "I am having trouble retrieving Auto.dev listings right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_autodev_vehicle_photos(
    vin: str = "",
    vehicle_id: str = "",
    max_photos: int = 12,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Fetch Auto.dev vehicle photos by VIN or inventory vehicle ID."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_autodev_vehicle_photos",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_autodev_vehicle_photos_impl(
            cip,
            vin=vin or None,
            vehicle_id=vehicle_id or None,
            max_photos=max_photos,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_autodev_vehicle_photos",
            exc=exc,
            user_message=(
                "I am having trouble retrieving Auto.dev vehicle photos right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_nhtsa_recalls(
    vin: str = "",
    make: str = "",
    model: str = "",
    model_year: int | None = None,
    vehicle_id: str = "",
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Look up NHTSA recall data by VIN, make/model/year, or inventory vehicle ID."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_nhtsa_recalls",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_nhtsa_recalls_impl(
            cip,
            vin=vin or None,
            make=make or None,
            model=model or None,
            model_year=model_year,
            vehicle_id=vehicle_id or None,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_nhtsa_recalls",
            exc=exc,
            user_message=(
                "I am having trouble retrieving NHTSA recall data right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_nhtsa_complaints(
    vin: str = "",
    make: str = "",
    model: str = "",
    model_year: int | None = None,
    vehicle_id: str = "",
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Look up NHTSA complaint data by VIN, make/model/year, or inventory vehicle ID."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_nhtsa_complaints",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_nhtsa_complaints_impl(
            cip,
            vin=vin or None,
            make=make or None,
            model=model or None,
            model_year=model_year,
            vehicle_id=vehicle_id or None,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_nhtsa_complaints",
            exc=exc,
            user_message=(
                "I am having trouble retrieving NHTSA complaint data right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def get_nhtsa_safety_ratings(
    vin: str = "",
    make: str = "",
    model: str = "",
    model_year: int | None = None,
    vehicle_id: str = "",
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Look up NHTSA safety ratings by VIN, make/model/year, or inventory vehicle ID."""
    try:
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_nhtsa_safety_ratings",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_nhtsa_safety_ratings_impl(
            cip,
            vin=vin or None,
            make=make or None,
            model=model or None,
            model_year=model_year,
            vehicle_id=vehicle_id or None,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_nhtsa_safety_ratings",
            exc=exc,
            user_message=(
                "I am having trouble retrieving NHTSA safety rating data right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def save_search(
    search_name: str,
    customer_id: str = "guest",
    make: str = "",
    model: str = "",
    year_min: int | None = None,
    year_max: int | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    body_type: str = "",
    fuel_type: str = "",
) -> str:
    """Save a named vehicle search so the customer can return later."""
    try:
        return save_search_impl(
            search_name=search_name,
            customer_id=customer_id,
            make=make or None,
            model=model or None,
            year_min=year_min,
            year_max=year_max,
            price_min=price_min,
            price_max=price_max,
            body_type=body_type or None,
            fuel_type=fuel_type or None,
        )
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="save_search",
            exc=exc,
            user_message=(
                "I am having trouble saving that search right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def list_saved_searches(customer_id: str = "guest") -> str:
    """List saved searches for a customer profile."""
    try:
        return list_saved_searches_impl(customer_id=customer_id)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="list_saved_searches",
            exc=exc,
            user_message=(
                "I am having trouble listing saved searches right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def save_favorite(vehicle_id: str, customer_id: str = "guest", note: str = "") -> str:
    """Save a vehicle to a customer's favorites list."""
    try:
        return save_favorite_impl(vehicle_id=vehicle_id, customer_id=customer_id, note=note)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="save_favorite",
            exc=exc,
            user_message=(
                "I am having trouble saving that favorite right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def list_favorites(customer_id: str = "guest") -> str:
    """List saved favorite vehicles for a customer profile."""
    try:
        return list_favorites_impl(customer_id=customer_id)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="list_favorites",
            exc=exc,
            user_message=(
                "I am having trouble listing favorites right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def reserve_vehicle(
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    hold_hours: int = 48,
    notes: str = "",
) -> str:
    """Create a short-term soft hold reservation on a vehicle."""
    try:
        return reserve_vehicle_impl(
            vehicle_id=vehicle_id,
            customer_name=customer_name,
            customer_contact=customer_contact,
            hold_hours=hold_hours,
            notes=notes,
        )
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="reserve_vehicle",
            exc=exc,
            user_message=(
                "I am having trouble creating a reservation hold right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def contact_dealer(
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    question: str,
    preferred_channel: str = "sms",
) -> str:
    """Send a customer question to the vehicle's dealer."""
    try:
        return contact_dealer_impl(
            vehicle_id=vehicle_id,
            customer_name=customer_name,
            customer_contact=customer_contact,
            question=question,
            preferred_channel=preferred_channel,
        )
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="contact_dealer",
            exc=exc,
            user_message=(
                "I am having trouble contacting the dealer right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def submit_purchase_deposit(
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    deposit_amount: float,
    financing_intent: str = "undecided",
    paperwork_started: bool = False,
) -> str:
    """Submit a deposit and begin digital paperwork intake for a purchase."""
    try:
        return submit_purchase_deposit_impl(
            vehicle_id=vehicle_id,
            customer_name=customer_name,
            customer_contact=customer_contact,
            deposit_amount=deposit_amount,
            financing_intent=financing_intent,
            paperwork_started=paperwork_started,
        )
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="submit_purchase_deposit",
            exc=exc,
            user_message=(
                "I am having trouble submitting the deposit right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def schedule_service(
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    preferred_date: str,
    service_type: str = "maintenance",
    notes: str = "",
) -> str:
    """Request a post-purchase service appointment."""
    try:
        return schedule_service_impl(
            vehicle_id=vehicle_id,
            customer_name=customer_name,
            customer_contact=customer_contact,
            preferred_date=preferred_date,
            service_type=service_type,
            notes=notes,
        )
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="schedule_service",
            exc=exc,
            user_message=(
                "I am having trouble scheduling service right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def request_follow_up(
    vehicle_id: str,
    customer_name: str,
    customer_contact: str,
    topic: str = "ownership check-in",
    preferred_channel: str = "email",
) -> str:
    """Request a dealer follow-up after purchase."""
    try:
        return request_follow_up_impl(
            vehicle_id=vehicle_id,
            customer_name=customer_name,
            customer_contact=customer_contact,
            topic=topic,
            preferred_channel=preferred_channel,
        )
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="request_follow_up",
            exc=exc,
            user_message=(
                "I am having trouble requesting follow-up right now. "
                "Please try again in a moment."
            ),
        )


# ── Inventory ingestion tools (pure CRUD, no CIP) ─────────────────


@mcp.tool()
def upsert_vehicle(vehicle: dict) -> str:
    """Add or update a single vehicle in the inventory. Must include an 'id' field."""
    try:
        return upsert_vehicle_impl(vehicle)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="upsert_vehicle",
            exc=exc,
            user_message=(
                "I am having trouble saving that vehicle right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def bulk_upsert_vehicles(vehicles: list[dict]) -> str:
    """Add or update multiple vehicles at once. Each dict must include an 'id' field."""
    try:
        return bulk_upsert_vehicles_impl(vehicles)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="bulk_upsert_vehicles",
            exc=exc,
            user_message=(
                "I am having trouble saving those vehicles right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def remove_vehicle(vehicle_id: str) -> str:
    """Remove a vehicle from the inventory by its ID."""
    try:
        return remove_vehicle_impl(vehicle_id)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="remove_vehicle",
            exc=exc,
            user_message=(
                "I am having trouble removing that vehicle right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def expire_stale_listings() -> str:
    """Archive vehicles that have passed their TTL expiration date."""
    try:
        return expire_stale_impl()
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="expire_stale_listings",
            exc=exc,
            user_message=(
                "I am having trouble expiring stale listings right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def record_lead(
    vehicle_id: str,
    action: str,
    user_query: str = "",
    lead_id: str = "",
    customer_id: str = "",
    session_id: str = "",
    customer_name: str = "",
    customer_contact: str = "",
    source_channel: str = "direct",
) -> str:
    """Record a user engagement lead for a vehicle.

    Supports optional identity stitching via lead/session/customer fields.
    """
    try:
        return record_lead_impl(
            vehicle_id,
            action,
            user_query,
            lead_id=lead_id,
            customer_id=customer_id,
            session_id=session_id,
            customer_name=customer_name,
            customer_contact=customer_contact,
            source_channel=source_channel,
        )
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="record_lead",
            exc=exc,
            user_message=(
                "I am having trouble recording that lead right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def record_sale(
    vehicle_id: str,
    sold_price: float,
    sold_at: str,
    lead_id: str = "",
    source_channel: str = "direct",
    salesperson_id: str = "",
    keep_vehicle_record: bool = True,
) -> str:
    """Record a completed sale outcome and link it to an optional lead."""
    try:
        return record_sale_impl(
            vehicle_id=vehicle_id,
            sold_price=sold_price,
            sold_at=sold_at,
            lead_id=lead_id,
            source_channel=source_channel,
            salesperson_id=salesperson_id,
            keep_vehicle_record=keep_vehicle_record,
        )
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="record_sale",
            exc=exc,
            user_message=(
                "I am having trouble recording that sale right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
async def bulk_import_from_api(
    source: str = "auto_dev",
    zip_code: str = "78701",
    radius_miles: int = 50,
    make: str = "",
    model: str = "",
    dry_run: bool = False,
) -> str:
    """Import vehicles from an external API (Auto.dev). Requires AUTO_DEV_API_KEY env var."""
    try:
        return await bulk_import_impl(
            source=source,
            zip_code=zip_code,
            radius_miles=radius_miles,
            make=make or None,
            model=model or None,
            dry_run=dry_run,
        )
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="bulk_import_from_api",
            exc=exc,
            user_message=(
                "I am having trouble importing vehicles right now. "
                "Please try again in a moment."
            ),
        )


# ── Escalation tools ──────────────────────────────────────────────


@mcp.tool()
async def get_escalations(
    limit: int = 20,
    include_delivered: bool = False,
    escalation_type: str = "",
    days: int = 30,
    provider: str = "",
    scaffold_id: str = "",
    policy: str = "",
    context_notes: str = "",
    raw: bool = False,
) -> str:
    """Get recent lead escalation alerts triggered by scoring threshold crossings."""
    try:
        esc_store = _get_escalation_store()
        if esc_store is None:
            return "Escalation tracking is not available."
        cip, resolved_scaffold_id, resolved_policy, resolved_context_notes = (
            _prepare_cip_orchestration(
                tool_name="get_escalations",
                provider=provider,
                scaffold_id=scaffold_id,
                policy=policy,
                context_notes=context_notes,
            )
        )
        return await get_escalations_impl(
            cip,
            esc_store,
            limit=limit,
            include_delivered=include_delivered,
            escalation_type=escalation_type,
            days=days,
            scaffold_id=resolved_scaffold_id,
            policy=resolved_policy,
            context_notes=resolved_context_notes,
            raw=raw,
        )
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_escalations",
            exc=exc,
            user_message=(
                "I am having trouble retrieving escalations right now. "
                "Please try again in a moment."
            ),
        )


@mcp.tool()
def acknowledge_escalation(escalation_id: str) -> str:
    """Mark a lead escalation alert as delivered/acknowledged."""
    try:
        esc_store = _get_escalation_store()
        if esc_store is None:
            return "Escalation tracking is not available."
        return acknowledge_escalation_impl(esc_store, escalation_id=escalation_id)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="acknowledge_escalation",
            exc=exc,
            user_message=(
                "I am having trouble acknowledging that escalation right now. "
                "Please try again in a moment."
            ),
        )


if __name__ == "__main__":
    mcp.run()
