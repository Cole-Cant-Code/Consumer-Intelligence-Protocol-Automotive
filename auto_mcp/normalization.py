"""Shared canonical normalization functions for vehicle data.

Single source of truth — imported by both ``tools.ingestion`` (manual CRUD)
and ``ingestion.pipeline`` (bulk Auto.dev import).

Generic parsing utilities (``clean_numeric_string``, ``parse_price``, etc.)
now live in ``cip_protocol.engagement.parsing`` and are re-exported here.
"""

from __future__ import annotations

from cip_protocol.engagement.parsing import (
    clean_numeric_string,
    parse_float,
    parse_int,
    parse_price,
)

BODY_TYPE_MAP: dict[str, str] = {
    "sedan": "sedan",
    "coupe": "coupe",
    "hatchback": "hatchback",
    "suv": "suv",
    "crossover": "suv",
    "truck": "truck",
    "pickup": "truck",
    "van": "van",
    "minivan": "minivan",
    "wagon": "wagon",
    "convertible": "convertible",
}

FUEL_TYPE_MAP: dict[str, str] = {
    "gasoline": "gasoline",
    "diesel": "diesel",
    "electric": "electric",
    "hybrid": "hybrid",
    "plug-in hybrid": "hybrid",
    "flex fuel": "gasoline",
}


def normalize_body_type(raw: str | None) -> str:
    """Map raw body-type string to canonical value.  Returns ``""`` for empty."""
    if not raw:
        return ""
    normalized = raw.strip().lower()
    return BODY_TYPE_MAP.get(normalized, normalized)


def normalize_fuel_type(raw: str | None) -> str:
    """Map raw fuel-type string to canonical value.  Returns ``""`` for empty."""
    if not raw:
        return ""
    normalized = raw.strip().lower()
    return FUEL_TYPE_MAP.get(normalized, normalized)

__all__ = [
    "BODY_TYPE_MAP",
    "FUEL_TYPE_MAP",
    "clean_numeric_string",
    "normalize_body_type",
    "normalize_fuel_type",
    "parse_float",
    "parse_int",
    "parse_price",
]
