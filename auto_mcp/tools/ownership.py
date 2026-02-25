"""Ownership cost, taxes/fees, and insurance estimation tools."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cip_protocol import CIP

from auto_mcp.data.inventory import get_vehicle
from auto_mcp.tools.orchestration import run_tool_with_orchestration

_STATE_TAX_RATES = {
    "TX": 0.0625,
    "CA": 0.0725,
    "FL": 0.0600,
    "NY": 0.0400,
    "WA": 0.0650,
}

_BODY_INSURANCE_MULTIPLIER = {
    "sedan": 0.95,
    "suv": 1.04,
    "truck": 1.10,
}

_FUEL_MAINTENANCE_PER_MILE = {
    "gasoline": 0.095,
    "hybrid": 0.080,
    "electric": 0.065,
}

_LUXURY_MAKES = {
    "audi",
    "bmw",
    "genesis",
    "lexus",
    "mercedes-benz",
    "tesla",
    "volvo",
}


def _estimate_insurance_range(
    *,
    vehicle: dict[str, Any],
    driver_age: int,
    annual_miles: int,
    zip_code: str,
) -> dict[str, float]:
    base = 820.0 + (float(vehicle["price"]) * 0.018)

    body_multiplier = _BODY_INSURANCE_MULTIPLIER.get(vehicle["body_type"].lower(), 1.0)
    luxury_multiplier = 1.18 if vehicle["make"].lower() in _LUXURY_MAKES else 1.0

    safety_rating = int(vehicle.get("safety_rating", 3) or 3)
    safety_multiplier = max(0.78, 1.0 - (max(0, safety_rating - 3) * 0.05))

    if driver_age < 25:
        age_multiplier = 1.45
    elif driver_age < 30:
        age_multiplier = 1.20
    elif driver_age > 70:
        age_multiplier = 1.18
    else:
        age_multiplier = 1.0

    mileage_multiplier = 1.0
    if annual_miles > 12_000:
        mileage_multiplier += min(0.35, ((annual_miles - 12_000) / 12_000) * 0.18)

    zip_multiplier = 1.0
    zip_prefix = zip_code.strip()[:2]
    if zip_prefix in {"10", "90", "33"}:
        zip_multiplier = 1.15
    elif zip_prefix in {"78", "77", "75"}:
        zip_multiplier = 1.03

    annual_mid = (
        base
        * body_multiplier
        * luxury_multiplier
        * safety_multiplier
        * age_multiplier
        * mileage_multiplier
        * zip_multiplier
    )

    annual_low = annual_mid * 0.86
    annual_high = annual_mid * 1.14

    return {
        "annual_low": round(annual_low, 2),
        "annual_mid": round(annual_mid, 2),
        "annual_high": round(annual_high, 2),
        "monthly_low": round(annual_low / 12, 2),
        "monthly_mid": round(annual_mid / 12, 2),
        "monthly_high": round(annual_high / 12, 2),
    }


def _combined_efficiency(vehicle: dict[str, Any]) -> float:
    city = max(1.0, float(vehicle.get("mpg_city", 0) or 0))
    highway = max(1.0, float(vehicle.get("mpg_highway", 0) or 0))
    return max(1.0, (city + highway) / 2)


async def estimate_insurance_impl(
    cip: CIP,
    *,
    vehicle_id: str,
    driver_age: int = 35,
    annual_miles: int = 12_000,
    zip_code: str = "",
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Estimate annual and monthly insurance range for a vehicle."""
    if driver_age <= 0:
        return "Driver age must be greater than 0."
    if annual_miles <= 0:
        return "Annual miles must be greater than 0."

    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    insurance = _estimate_insurance_range(
        vehicle=vehicle,
        driver_age=driver_age,
        annual_miles=annual_miles,
        zip_code=zip_code,
    )

    user_input = (
        f"Estimate insurance for {vehicle['year']} {vehicle['make']} {vehicle['model']} "
        f"(ID: {vehicle_id})"
    )

    data_context: dict[str, Any] = {
        "vehicle": {
            "id": vehicle["id"],
            "year": vehicle["year"],
            "make": vehicle["make"],
            "model": vehicle["model"],
            "trim": vehicle["trim"],
            "price": vehicle["price"],
            "body_type": vehicle["body_type"],
            "safety_rating": vehicle["safety_rating"],
        },
        "driver_profile": {
            "driver_age": driver_age,
            "annual_miles": annual_miles,
            "zip_code": zip_code,
        },
        "insurance_estimate": insurance,
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="estimate_insurance",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )


async def estimate_out_the_door_price_impl(
    cip: CIP,
    *,
    vehicle_id: str,
    state: str = "TX",
    trade_in_value: float = 0.0,
    tax_rate: float | None = None,
    title_fee: float = 85.0,
    registration_fee: float = 150.0,
    doc_fee: float = 225.0,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Estimate out-the-door vehicle price including tax and common fees."""
    if trade_in_value < 0:
        return "Trade-in value must be greater than or equal to 0."
    if tax_rate is not None and tax_rate < 0:
        return "Tax rate must be greater than or equal to 0."
    for label, value in {
        "title fee": title_fee,
        "registration fee": registration_fee,
        "doc fee": doc_fee,
    }.items():
        if value < 0:
            return f"{label.capitalize()} must be greater than or equal to 0."

    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    normalized_state = state.strip().upper()[:2] or "TX"
    resolved_tax_rate = (
        tax_rate
        if tax_rate is not None
        else _STATE_TAX_RATES.get(normalized_state, 0.065)
    )

    taxable_amount = max(0.0, float(vehicle["price"]) - trade_in_value)
    sales_tax = taxable_amount * resolved_tax_rate

    total_fees = title_fee + registration_fee + doc_fee
    gross_out_the_door = float(vehicle["price"]) + sales_tax + total_fees
    net_out_the_door = max(0.0, gross_out_the_door - trade_in_value)

    user_input = (
        f"Estimate out-the-door pricing for {vehicle['year']} {vehicle['make']} "
        f"{vehicle['model']} (ID: {vehicle_id})"
    )

    data_context: dict[str, Any] = {
        "vehicle": {
            "id": vehicle["id"],
            "year": vehicle["year"],
            "make": vehicle["make"],
            "model": vehicle["model"],
            "trim": vehicle["trim"],
            "price": vehicle["price"],
        },
        "state": normalized_state,
        "tax_rate": round(resolved_tax_rate, 5),
        "trade_in_value": round(trade_in_value, 2),
        "fees": {
            "title_fee": round(title_fee, 2),
            "registration_fee": round(registration_fee, 2),
            "doc_fee": round(doc_fee, 2),
            "total_fees": round(total_fees, 2),
        },
        "totals": {
            "taxable_amount": round(taxable_amount, 2),
            "sales_tax": round(sales_tax, 2),
            "gross_out_the_door": round(gross_out_the_door, 2),
            "net_out_the_door": round(net_out_the_door, 2),
        },
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="estimate_out_the_door_price",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )


async def estimate_cost_of_ownership_impl(
    cip: CIP,
    *,
    vehicle_id: str,
    annual_miles: int = 12_000,
    ownership_years: int = 5,
    driver_age: int = 35,
    gas_price_per_gallon: float = 3.80,
    electricity_price_per_kwh: float = 0.16,
    insurance_zip_code: str = "",
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Estimate multi-year ownership cost including fuel, maintenance, insurance."""
    if annual_miles <= 0:
        return "Annual miles must be greater than 0."
    if ownership_years <= 0:
        return "Ownership years must be greater than 0."
    if driver_age <= 0:
        return "Driver age must be greater than 0."
    if gas_price_per_gallon < 0 or electricity_price_per_kwh < 0:
        return "Energy price assumptions must be greater than or equal to 0."

    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return f"Vehicle with ID '{vehicle_id}' not found in inventory."

    fuel_type = vehicle["fuel_type"].lower()
    combined_efficiency = _combined_efficiency(vehicle)

    if fuel_type == "electric":
        kwh_per_mile = 33.7 / combined_efficiency
        annual_energy = annual_miles * kwh_per_mile
        annual_energy_cost = annual_energy * electricity_price_per_kwh
        energy_label = "electricity"
    else:
        annual_gallons = annual_miles / max(combined_efficiency, 1)
        annual_energy_cost = annual_gallons * gas_price_per_gallon
        energy_label = "fuel"

    current_year = datetime.now(timezone.utc).year
    age = max(0, current_year - int(vehicle["year"]))
    maintenance_per_mile = _FUEL_MAINTENANCE_PER_MILE.get(fuel_type, 0.090)
    age_multiplier = 1 + min(0.40, age * 0.04)
    annual_maintenance = annual_miles * maintenance_per_mile * age_multiplier

    insurance = _estimate_insurance_range(
        vehicle=vehicle,
        driver_age=driver_age,
        annual_miles=annual_miles,
        zip_code=insurance_zip_code,
    )
    annual_insurance = insurance["annual_mid"]

    residual_rate = max(0.25, 0.72 - (0.09 * ownership_years) - (0.015 * age))
    projected_resale = float(vehicle["price"]) * residual_rate
    depreciation_cost = max(0.0, float(vehicle["price"]) - projected_resale)

    annual_registration = 150.0

    total_energy = annual_energy_cost * ownership_years
    total_maintenance = annual_maintenance * ownership_years
    total_insurance = annual_insurance * ownership_years
    total_registration = annual_registration * ownership_years

    total_cost = (
        total_energy
        + total_maintenance
        + total_insurance
        + total_registration
        + depreciation_cost
    )

    user_input = (
        f"Estimate total cost of ownership for {vehicle['year']} {vehicle['make']} "
        f"{vehicle['model']} (ID: {vehicle_id}) over {ownership_years} years"
    )

    data_context: dict[str, Any] = {
        "vehicle": {
            "id": vehicle["id"],
            "year": vehicle["year"],
            "make": vehicle["make"],
            "model": vehicle["model"],
            "trim": vehicle["trim"],
            "price": vehicle["price"],
            "fuel_type": vehicle["fuel_type"],
            "mpg_city": vehicle["mpg_city"],
            "mpg_highway": vehicle["mpg_highway"],
        },
        "assumptions": {
            "annual_miles": annual_miles,
            "ownership_years": ownership_years,
            "driver_age": driver_age,
            "gas_price_per_gallon": gas_price_per_gallon,
            "electricity_price_per_kwh": electricity_price_per_kwh,
        },
        "annual_costs": {
            "energy_type": energy_label,
            "energy_cost": round(annual_energy_cost, 2),
            "maintenance_cost": round(annual_maintenance, 2),
            "insurance_cost": round(annual_insurance, 2),
            "registration_cost": round(annual_registration, 2),
        },
        "multi_year_projection": {
            "total_energy": round(total_energy, 2),
            "total_maintenance": round(total_maintenance, 2),
            "total_insurance": round(total_insurance, 2),
            "total_registration": round(total_registration, 2),
            "depreciation_cost": round(depreciation_cost, 2),
            "projected_resale_value": round(projected_resale, 2),
            "estimated_total_cost": round(total_cost, 2),
        },
    }

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="estimate_cost_of_ownership",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )
