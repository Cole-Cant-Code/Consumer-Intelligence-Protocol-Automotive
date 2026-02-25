"""Multi-scenario financing comparison tool implementation."""

from __future__ import annotations

from typing import Any

from cip_protocol import CIP

from auto_mcp.tools.orchestration import run_tool_with_orchestration


def _monthly_payment(principal: float, apr: float, term_months: int) -> float:
    monthly_rate = (apr / 100.0) / 12.0
    if monthly_rate == 0:
        return principal / term_months

    factor = (1 + monthly_rate) ** term_months
    return principal * (monthly_rate * factor) / (factor - 1)


async def compare_financing_scenarios_impl(
    cip: CIP,
    *,
    vehicle_price: float,
    down_payment_options: list[float] | None = None,
    loan_term_options: list[int] | None = None,
    estimated_apr: float = 6.5,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Compare financing outcomes across multiple down payment and term scenarios."""
    if vehicle_price <= 0:
        return "Vehicle price must be greater than 0."
    if estimated_apr < 0:
        return "Estimated APR must be greater than or equal to 0."

    resolved_down = down_payment_options or [0.0, 5_000.0, 10_000.0]
    resolved_terms = loan_term_options or [48, 60, 72]

    if any(value < 0 for value in resolved_down):
        return "Down payment options must all be greater than or equal to 0."
    if any(value <= 0 for value in resolved_terms):
        return "Loan term options must all be greater than 0 months."

    normalized_down = sorted(set(round(float(value), 2) for value in resolved_down))
    normalized_terms = sorted(set(int(value) for value in resolved_terms))

    scenarios: list[dict[str, Any]] = []
    for down_payment in normalized_down:
        loan_amount = vehicle_price - down_payment
        if loan_amount <= 0:
            continue

        for term in normalized_terms:
            monthly = _monthly_payment(loan_amount, estimated_apr, term)
            total_paid = monthly * term
            total_interest = total_paid - loan_amount
            scenarios.append(
                {
                    "down_payment": down_payment,
                    "loan_term_months": term,
                    "loan_amount": round(loan_amount, 2),
                    "estimated_monthly_payment": round(monthly, 2),
                    "total_paid": round(total_paid, 2),
                    "total_interest": round(total_interest, 2),
                }
            )

    if not scenarios:
        return (
            "No valid financing scenarios could be generated. "
            "Check that at least one down payment is less than the vehicle price."
        )

    lowest_monthly = min(scenarios, key=lambda item: item["estimated_monthly_payment"])
    lowest_interest = min(scenarios, key=lambda item: item["total_interest"])

    user_input = (
        f"Compare financing scenarios for a ${vehicle_price:,.0f} vehicle at "
        f"{estimated_apr}% estimated APR"
    )

    data_context: dict[str, Any] = {
        "vehicle_price": round(vehicle_price, 2),
        "estimated_apr": estimated_apr,
        "scenario_count": len(scenarios),
        "down_payment_options": normalized_down,
        "loan_term_options": normalized_terms,
        "scenarios": scenarios,
        "highlights": {
            "lowest_monthly_payment": lowest_monthly,
            "lowest_total_interest": lowest_interest,
        },
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="compare_financing_scenarios",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )
