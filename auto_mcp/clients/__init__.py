"""Shared external API clients."""

from auto_mcp.clients.nhtsa import SHARED_NHTSA_CACHE, NHTSAClient

__all__ = ["NHTSAClient", "SHARED_NHTSA_CACHE"]
