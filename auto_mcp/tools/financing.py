"""Financing and trade-in tool implementations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cip_protocol import CIP

from auto_mcp.tools.orchestration import run_tool_with_orchestration


async def estimate_financing_impl(
    cip: CIP,
    *,
    vehicle_price: float,
    down_payment: float = 0.0,
    loan_term_months: int = 60,
    estimated_apr: float = 6.5,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Calculate estimated monthly payment using standard amortization."""
    if vehicle_price < 0:
        return "Vehicle price must be greater than or equal to 0."
    if down_payment < 0:
        return "Down payment must be greater than or equal to 0."
    if loan_term_months <= 0:
        return "Loan term must be greater than 0 months."
    if estimated_apr < 0:
        return "Estimated APR must be greater than or equal to 0."

    loan_amount = vehicle_price - down_payment
    if loan_amount <= 0:
        return "Down payment exceeds or equals the vehicle price. No financing needed."

    monthly_rate = (estimated_apr / 100) / 12
    if monthly_rate == 0:
        monthly_payment = loan_amount / loan_term_months
    else:
        # Standard amortization formula: M = P * [r(1+r)^n] / [(1+r)^n - 1]
        factor = (1 + monthly_rate) ** loan_term_months
        monthly_payment = loan_amount * (monthly_rate * factor) / (factor - 1)

    total_paid = monthly_payment * loan_term_months
    total_interest = total_paid - loan_amount

    user_input = (
        f"Estimate financing for a ${vehicle_price:,.0f} vehicle with "
        f"${down_payment:,.0f} down, {loan_term_months}-month term at "
        f"{estimated_apr}% estimated APR"
    )

    data_context: dict[str, Any] = {
        "vehicle_price": vehicle_price,
        "down_payment": down_payment,
        "loan_amount": round(loan_amount, 2),
        "loan_term_months": loan_term_months,
        "estimated_apr": estimated_apr,
        "estimated_monthly_payment": round(monthly_payment, 2),
        "total_paid": round(total_paid, 2),
        "total_interest": round(total_interest, 2),
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="estimate_financing",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )


# Base MSRP lookup for trade-in depreciation model
_BASE_MSRP: dict[str, int] = {
    "toyota camry": 28_000, "honda accord": 29_000, "hyundai sonata": 27_000,
    "mazda mazda3": 24_000, "nissan altima": 27_000, "kia k5": 25_000,
    "toyota rav4": 30_000, "honda cr-v": 31_000, "chevrolet equinox": 29_000,
    "ford escape": 29_000, "hyundai tucson": 29_000, "subaru forester": 33_000,
    "ford f-150": 38_000, "chevrolet silverado 1500": 40_000, "ram 1500": 39_000,
    "toyota tacoma": 32_000, "tesla model 3": 40_000, "hyundai ioniq 5": 42_000,
    "chevrolet equinox ev": 35_000, "ford mustang mach-e": 45_000,
    "bmw 3 series": 44_000, "mercedes-benz c-class": 47_000, "audi q5": 46_000,
    "lexus rx": 50_000, "genesis g70": 42_000, "volvo xc60": 45_000,
    "nissan sentra": 21_000, "hyundai elantra": 22_000, "chevrolet trax": 22_000,
    "kia forte": 20_000, "toyota rav4 prime": 43_000, "honda cr-v hybrid": 35_000,
}

_CONDITION_MULTIPLIER = {
    "excellent": 1.10,
    "good": 1.00,
    "fair": 0.85,
    "poor": 0.65,
}


async def estimate_trade_in_impl(
    cip: CIP,
    *,
    year: int,
    make: str,
    model: str,
    mileage: int,
    condition: str = "good",
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Estimate trade-in value using a depreciation model."""
    current_year = datetime.now(timezone.utc).year
    age = current_year - year
    if age < 0:
        return "Vehicle year cannot be in the future."

    key = f"{make} {model}".lower()
    base = _BASE_MSRP.get(key, 28_000)

    # Depreciation: 15% first year, 10% per year after
    if age == 0:
        depreciated = base
    elif age == 1:
        depreciated = base * 0.85
    else:
        depreciated = base * 0.85 * (0.90 ** (age - 1))

    # Mileage adjustment: assume 12k miles/year is average
    expected_mileage = age * 12_000 if age > 0 else 5_000
    mileage_ratio = mileage / max(expected_mileage, 1)
    if mileage_ratio > 1.0:
        mileage_adj = 1.0 - (mileage_ratio - 1.0) * 0.15
    else:
        mileage_adj = 1.0 + (1.0 - mileage_ratio) * 0.05
    mileage_adj = max(mileage_adj, 0.5)

    cond_mult = _CONDITION_MULTIPLIER.get(condition.lower(), 1.0)

    mid_value = depreciated * mileage_adj * cond_mult
    low_value = mid_value * 0.85
    high_value = mid_value * 1.15

    user_input = (
        f"Estimate trade-in value for a {year} {make} {model} "
        f"with {mileage:,} miles in {condition} condition"
    )

    data_context: dict[str, Any] = {
        "year": year,
        "make": make,
        "model": model,
        "mileage": mileage,
        "condition": condition,
        "estimated_low": round(low_value),
        "estimated_mid": round(mid_value),
        "estimated_high": round(high_value),
        "base_msrp_used": base,
        "vehicle_age_years": age,
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="estimate_trade_in",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )
