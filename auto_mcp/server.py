"""AutoCIP MCP server — FastMCP entry point with 20 tool registrations."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cip_protocol import CIP
from mcp.server.fastmcp import FastMCP

from auto_mcp.config import AUTO_DOMAIN_CONFIG
from auto_mcp.tools.availability import check_availability_impl
from auto_mcp.tools.compare import compare_vehicles_impl
from auto_mcp.tools.details import get_vehicle_details_impl
from auto_mcp.tools.financing import estimate_financing_impl, estimate_trade_in_impl
from auto_mcp.tools.ingestion import (
    bulk_import_impl,
    bulk_upsert_vehicles_impl,
    expire_stale_impl,
    record_lead_impl,
    remove_vehicle_impl,
    upsert_vehicle_impl,
)
from auto_mcp.tools.location_search import search_by_location_impl
from auto_mcp.tools.scheduling import (
    assess_purchase_readiness_impl,
    schedule_test_drive_impl,
)
from auto_mcp.tools.search import search_vehicles_impl
from auto_mcp.tools.stats import get_inventory_stats_impl, get_lead_analytics_impl
from auto_mcp.tools.vin_search import search_by_vin_impl

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

_cip_instance: CIP | None = None
_cip_provider: str = ""
_cip_model: str = ""

_KEY_MAP = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
}


def _build_cip(provider: str, model: str = "") -> CIP:
    """Build a CIP instance for the given provider/model."""
    api_key = os.environ.get(_KEY_MAP.get(provider, ""), "")
    resolved_model = model or _DEFAULT_MODELS.get(provider, "")
    return CIP.from_config(
        AUTO_DOMAIN_CONFIG,
        _SCAFFOLD_DIR,
        provider,
        api_key=api_key,
        model=resolved_model,
    )


def _get_cip() -> CIP:
    """Lazy singleton for the CIP instance. Uses override if set (for testing)."""
    global _cip_instance, _cip_provider, _cip_model  # noqa: PLW0603
    if _cip_instance is None:
        provider = _cip_provider or os.environ.get("CIP_LLM_PROVIDER", "anthropic")
        model = _cip_model or os.environ.get("CIP_LLM_MODEL", "")
        _cip_instance = _build_cip(provider, model)
        _cip_provider = provider
        _cip_model = model
    return _cip_instance


def set_cip_override(cip: CIP | None) -> None:
    """Inject a CIP instance (e.g. with MockProvider) for testing."""
    global _cip_instance  # noqa: PLW0603
    _cip_instance = cip


def _log_and_return_tool_error(
    *, tool_name: str, exc: Exception, user_message: str
) -> str:
    """Log full exception details while returning a safe user-facing error."""
    logger.exception("Tool '%s' failed", tool_name, exc_info=exc)
    return user_message


# ── Tool registrations ──────────────────────────────────────────────


@mcp.tool()
def set_llm_provider(provider: str, model: str = "") -> str:
    """Switch the LLM provider used for CIP reasoning.

    provider: 'anthropic' or 'openai'
    model: optional model override (defaults to claude-sonnet-4-6 / gpt-4o)
    """
    global _cip_instance, _cip_provider, _cip_model  # noqa: PLW0603
    provider = provider.strip().lower()
    if provider not in _KEY_MAP:
        return f"Unknown provider '{provider}'. Use 'anthropic' or 'openai'."
    resolved_model = model.strip() or _DEFAULT_MODELS.get(provider, "")
    try:
        _cip_instance = _build_cip(provider, resolved_model)
        _cip_provider = provider
        _cip_model = resolved_model
        return f"CIP reasoning now uses {provider}/{resolved_model}."
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="set_llm_provider",
            exc=exc,
            user_message=f"Failed to switch to {provider}: check API key is set.",
        )


@mcp.tool()
def get_llm_provider() -> str:
    """Return the current CIP LLM provider and model."""
    _get_cip()  # ensure initialized
    return f"{_cip_provider}/{_cip_model}"


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
    ) -> str:
    """Search for vehicles by filters with optional pagination via limit/offset."""
    try:
        return await search_vehicles_impl(
            _get_cip(),
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
        )
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
async def get_vehicle_details(vehicle_id: str) -> str:
    """Get detailed specifications and information about a specific vehicle by ID."""
    try:
        return await get_vehicle_details_impl(_get_cip(), vehicle_id=vehicle_id)
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
async def compare_vehicles(vehicle_ids: list[str]) -> str:
    """Compare 2-3 vehicles side by side. Provide a list of vehicle IDs."""
    try:
        return await compare_vehicles_impl(_get_cip(), vehicle_ids=vehicle_ids)
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
) -> str:
    """Estimate monthly payments for a vehicle purchase. All figures are estimates only."""
    try:
        return await estimate_financing_impl(
            _get_cip(),
            vehicle_price=vehicle_price,
            down_payment=down_payment,
            loan_term_months=loan_term_months,
            estimated_apr=estimated_apr,
        )
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
) -> str:
    """Estimate trade-in value based on year, make, model, mileage, and condition."""
    try:
        return await estimate_trade_in_impl(
            _get_cip(),
            year=year,
            make=make,
            model=model,
            mileage=mileage,
            condition=condition,
        )
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
async def check_availability(vehicle_id: str, zip_code: str = "") -> str:
    """Check if a specific vehicle is currently available and get dealer information."""
    try:
        return await check_availability_impl(
            _get_cip(), vehicle_id=vehicle_id, zip_code=zip_code
        )
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
) -> str:
    """Request a test drive appointment for a specific vehicle."""
    try:
        return await schedule_test_drive_impl(
            _get_cip(),
            vehicle_id=vehicle_id,
            preferred_date=preferred_date,
            preferred_time=preferred_time,
            customer_name=customer_name,
            customer_phone=customer_phone,
        )
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
) -> str:
    """Assess how ready you are to purchase a specific vehicle based on your situation."""
    try:
        return await assess_purchase_readiness_impl(
            _get_cip(),
            vehicle_id=vehicle_id,
            budget=budget,
            has_financing=has_financing,
            has_insurance=has_insurance,
            has_trade_in=has_trade_in,
        )
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
) -> str:
    """Search for vehicles near a ZIP code within a given radius."""
    try:
        return await search_by_location_impl(
            _get_cip(),
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
        )
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
async def search_by_vin(vin: str) -> str:
    """Look up a specific vehicle by its 17-character VIN."""
    try:
        return await search_by_vin_impl(_get_cip(), vin=vin)
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
async def get_inventory_stats() -> str:
    """Get comprehensive inventory statistics including coverage, pricing, and freshness."""
    try:
        return await get_inventory_stats_impl(_get_cip())
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
async def get_lead_analytics(days: int = 30) -> str:
    """Get lead engagement analytics for dealer reporting over a specified period."""
    try:
        return await get_lead_analytics_impl(_get_cip(), days=days)
    except Exception as exc:
        return _log_and_return_tool_error(
            tool_name="get_lead_analytics",
            exc=exc,
            user_message=(
                "I am having trouble retrieving lead analytics right now. "
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
    """Remove vehicles that have passed their TTL expiration date."""
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
def record_lead(vehicle_id: str, action: str, user_query: str = "") -> str:
    """Record a user engagement lead for a vehicle.

    Actions: viewed, compared, financed, test_drive, availability_check.
    """
    try:
        return record_lead_impl(vehicle_id, action, user_query)
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


if __name__ == "__main__":
    mcp.run()
