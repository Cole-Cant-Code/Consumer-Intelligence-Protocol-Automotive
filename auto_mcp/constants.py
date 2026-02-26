"""Shared constants used across multiple tool modules.

Single source of truth — avoids duplication of luxury makes, VIN regex, etc.
"""

from __future__ import annotations

import re

LUXURY_MAKES: frozenset[str] = frozenset({
    "audi",
    "bmw",
    "genesis",
    "lexus",
    "mercedes-benz",
    "tesla",
    "volvo",
})

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.IGNORECASE)
