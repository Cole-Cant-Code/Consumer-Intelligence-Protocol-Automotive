"""Shared orchestration helpers for CIP-routed tool implementations.

Thin re-export layer: all logic now lives in ``cip_protocol.orchestration.runner``.
"""

from cip_protocol.orchestration.runner import (
    build_cross_domain_context,
    build_raw_response,
    run_tool_with_orchestration,
)

# Backward-compatible aliases — existing tool modules import the underscore-prefixed
# names from this module.
_build_raw_response = build_raw_response
_build_cross_domain_context = build_cross_domain_context

__all__ = [
    "_build_cross_domain_context",
    "_build_raw_response",
    "run_tool_with_orchestration",
]
