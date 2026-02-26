"""Shared external API clients."""

from auto_mcp.clients.autodev import (
    SHARED_AUTODEV_CACHE,
    AutoDevClient,
    AutoDevClientError,
)
from auto_mcp.clients.nhtsa import SHARED_NHTSA_CACHE, NHTSAClient

__all__ = [
    "AutoDevClient",
    "AutoDevClientError",
    "NHTSAClient",
    "SHARED_AUTODEV_CACHE",
    "SHARED_NHTSA_CACHE",
]
