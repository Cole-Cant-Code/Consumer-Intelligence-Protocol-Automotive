"""NHTSA safety data tool implementations (recalls, complaints, safety ratings)."""

from __future__ import annotations

from typing import Any

from cip_protocol import CIP

from auto_mcp.clients.nhtsa import SHARED_NHTSA_CACHE, NHTSAClient
from auto_mcp.data.inventory import get_vehicle
from auto_mcp.tools.orchestration import _build_raw_response, run_tool_with_orchestration

_TOOL_RECALLS = "get_nhtsa_recalls"
_TOOL_COMPLAINTS = "get_nhtsa_complaints"
_TOOL_RATINGS = "get_nhtsa_safety_ratings"


def _resolve_vehicle(vehicle_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a vehicle from inventory, returning (vehicle, error_message)."""
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        return None, f"Vehicle with ID '{vehicle_id}' not found in inventory."
    return vehicle, None


def _extract_make_model_year(
    vehicle: dict[str, Any],
) -> tuple[str, str, int]:
    make = str(vehicle.get("make", "")).strip()
    model = str(vehicle.get("model", "")).strip()
    if not make or not model:
        raise ValueError("inventory vehicle is missing make/model")

    year_raw = vehicle.get("year")
    try:
        model_year = int(year_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("inventory vehicle has invalid model year") from exc

    return make, model, model_year


def _validate_direct_params(
    make: str | None, model: str | None, model_year: int | None
) -> str | None:
    """Return error message if direct params are invalid, else None."""
    if not make or not make.strip():
        return "make is required when vehicle_id is not provided."
    if not model or not model.strip():
        return "model is required when vehicle_id is not provided."
    if model_year is None:
        return "model_year is required when vehicle_id is not provided."
    return None


def _format_error(
    *,
    tool_name: str,
    raw: bool,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> str:
    if not raw:
        return message

    payload: dict[str, Any] = {
        "error": True,
        "code": code,
        "message": message,
    }
    if details:
        payload["details"] = details
    return _build_raw_response(tool_name, payload)


def _resolve_request_params(
    *,
    tool_name: str,
    raw: bool,
    make: str | None,
    model: str | None,
    model_year: int | None,
    vehicle_id: str | None,
) -> tuple[str, str, int, str, str | None]:
    """Resolve inputs and precedence rules.

    Returns: (make, model, model_year, resolution_note, error_response)
    """
    resolution_note = ""

    if vehicle_id:
        vehicle, err = _resolve_vehicle(vehicle_id)
        if err:
            return "", "", 0, resolution_note, _format_error(
                tool_name=tool_name,
                raw=raw,
                code="VEHICLE_NOT_FOUND",
                message=err,
            )
        if vehicle is None:
            return "", "", 0, resolution_note, _format_error(
                tool_name=tool_name,
                raw=raw,
                code="VEHICLE_NOT_FOUND",
                message=f"Vehicle with ID '{vehicle_id}' not found in inventory.",
            )
        if make or model or model_year is not None:
            resolution_note = (
                f"Resolved from inventory vehicle {vehicle_id}; "
                "explicit make/model/year ignored."
            )
        try:
            make, model, model_year = _extract_make_model_year(vehicle)
        except ValueError as exc:
            return "", "", 0, resolution_note, _format_error(
                tool_name=tool_name,
                raw=raw,
                code="INVALID_VEHICLE_CONTEXT",
                message=str(exc),
                details={"vehicle_id": vehicle_id},
            )
    else:
        err = _validate_direct_params(make, model, model_year)
        if err:
            return "", "", 0, resolution_note, _format_error(
                tool_name=tool_name,
                raw=raw,
                code="INVALID_INPUT",
                message=err,
            )
        make = str(make).strip() if make is not None else ""
        model = str(model).strip() if model is not None else ""

    if model_year is not None and not isinstance(model_year, int):
        try:
            model_year = int(model_year)
        except (TypeError, ValueError):
            return "", "", 0, resolution_note, _format_error(
                tool_name=tool_name,
                raw=raw,
                code="INVALID_INPUT",
                message="model_year must be a valid integer year.",
                details={"model_year": model_year},
            )

    if not make or not model or model_year is None:
        return "", "", 0, resolution_note, _format_error(
            tool_name=tool_name,
            raw=raw,
            code="INVALID_INPUT",
            message="make, model, and model_year are required.",
        )

    return make, model, model_year, resolution_note, None


async def get_nhtsa_recalls_impl(
    cip: CIP,
    *,
    make: str | None = None,
    model: str | None = None,
    model_year: int | None = None,
    vehicle_id: str | None = None,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Look up NHTSA recall data for a vehicle."""
    make, model, model_year, metadata_note, error_response = _resolve_request_params(
        tool_name=_TOOL_RECALLS,
        raw=raw,
        make=make,
        model=model,
        model_year=model_year,
        vehicle_id=vehicle_id,
    )
    if error_response:
        return error_response

    try:
        async with NHTSAClient(cache=SHARED_NHTSA_CACHE) as client:
            data = await client.get_recalls(make, model, model_year)
    except ValueError as exc:
        return _format_error(
            tool_name=_TOOL_RECALLS,
            raw=raw,
            code="INVALID_INPUT",
            message=str(exc),
            details={"make": make, "model": model, "model_year": model_year},
        )

    user_input = (
        f"Summarize NHTSA recall data for {model_year} {make} {model}."
    )

    data_context: dict[str, Any] = {
        "vehicle": {"make": make, "model": model, "model_year": model_year},
        "nhtsa_recalls": data,
        "data_source": "NHTSA Recalls API (api.nhtsa.gov)",
    }
    if vehicle_id:
        data_context["vehicle"]["vehicle_id"] = vehicle_id
    if metadata_note:
        data_context["resolution_note"] = metadata_note

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="get_nhtsa_recalls",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )


async def get_nhtsa_complaints_impl(
    cip: CIP,
    *,
    make: str | None = None,
    model: str | None = None,
    model_year: int | None = None,
    vehicle_id: str | None = None,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Look up NHTSA complaint data for a vehicle."""
    make, model, model_year, metadata_note, error_response = _resolve_request_params(
        tool_name=_TOOL_COMPLAINTS,
        raw=raw,
        make=make,
        model=model,
        model_year=model_year,
        vehicle_id=vehicle_id,
    )
    if error_response:
        return error_response

    try:
        async with NHTSAClient(cache=SHARED_NHTSA_CACHE) as client:
            data = await client.get_complaints(make, model, model_year)
    except ValueError as exc:
        return _format_error(
            tool_name=_TOOL_COMPLAINTS,
            raw=raw,
            code="INVALID_INPUT",
            message=str(exc),
            details={"make": make, "model": model, "model_year": model_year},
        )

    user_input = (
        f"Summarize NHTSA complaint data for {model_year} {make} {model}."
    )

    data_context: dict[str, Any] = {
        "vehicle": {"make": make, "model": model, "model_year": model_year},
        "nhtsa_complaints": data,
        "data_source": "NHTSA Complaints API (api.nhtsa.gov)",
    }
    if vehicle_id:
        data_context["vehicle"]["vehicle_id"] = vehicle_id
    if metadata_note:
        data_context["resolution_note"] = metadata_note

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="get_nhtsa_complaints",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )


async def get_nhtsa_safety_ratings_impl(
    cip: CIP,
    *,
    make: str | None = None,
    model: str | None = None,
    model_year: int | None = None,
    vehicle_id: str | None = None,
    scaffold_id: str | None = None,
    policy: str | None = None,
    context_notes: str | None = None,
    raw: bool = False,
) -> str:
    """Look up NHTSA safety ratings for a vehicle."""
    make, model, model_year, metadata_note, error_response = _resolve_request_params(
        tool_name=_TOOL_RATINGS,
        raw=raw,
        make=make,
        model=model,
        model_year=model_year,
        vehicle_id=vehicle_id,
    )
    if error_response:
        return error_response

    try:
        async with NHTSAClient(cache=SHARED_NHTSA_CACHE) as client:
            data = await client.get_safety_ratings(make, model, model_year)
    except ValueError as exc:
        return _format_error(
            tool_name=_TOOL_RATINGS,
            raw=raw,
            code="INVALID_INPUT",
            message=str(exc),
            details={"make": make, "model": model, "model_year": model_year},
        )

    user_input = (
        f"Summarize NHTSA safety ratings for {model_year} {make} {model}."
    )

    data_context: dict[str, Any] = {
        "vehicle": {"make": make, "model": model, "model_year": model_year},
        "nhtsa_safety_ratings": data,
        "data_source": "NHTSA Safety Ratings API (api.nhtsa.gov)",
    }
    if vehicle_id:
        data_context["vehicle"]["vehicle_id"] = vehicle_id
    if metadata_note:
        data_context["resolution_note"] = metadata_note

    return await run_tool_with_orchestration(
        cip,
        user_input=user_input,
        tool_name="get_nhtsa_safety_ratings",
        data_context=data_context,
        scaffold_id=scaffold_id,
        policy=policy,
        context_notes=context_notes,
        raw=raw,
    )
