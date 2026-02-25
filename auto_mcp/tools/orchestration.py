"""Shared orchestration helpers for CIP-routed tool implementations."""

from __future__ import annotations

import json
from typing import Any

from cip_protocol import CIP


def _build_raw_response(tool_name: str, data_context: dict[str, Any]) -> str:
    payload = {
        "_raw": True,
        "_tool": tool_name,
        "_meta": {"schema_version": 1},
        "data": data_context,
    }
    return json.dumps(payload, indent=2, default=str)


def _build_cross_domain_context(context_notes: str | None) -> dict[str, Any] | None:
    if not context_notes:
        return None
    normalized = context_notes.strip()
    if not normalized:
        return None
    return {"orchestrator_notes": normalized}


async def run_tool_with_orchestration(
    cip: CIP,
    *,
    user_input: str,
    tool_name: str,
    data_context: dict[str, Any],
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    if raw:
        return _build_raw_response(tool_name, data_context)

    result = await cip.run(
        user_input,
        tool_name=tool_name,
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        cross_domain_context=_build_cross_domain_context(context_notes),
    )
    return result.response.content
