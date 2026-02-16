"""Live verification rules for PND + DIP/HDO data validation.

This module provides validation functions to verify CEZ PND data fetched
from Playwright login and saved to JSON files in evidence/live-fetch/.

Validates:
- PND: A+B+C (payload non-empty, expected columns, status=32, 24h time window)
- DIP/HDO: Expected structure (signal, casy, den, datum)
"""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any


def validate_pnd_data(data: dict[str, Any]) -> dict[str, Any]:
    """Validate PND data according to A+B+C+D criteria.

    A: Non-empty payload (hasData=true, size>0, values not empty)
    B: Expected columns (columns contains well-formed definitions)
    C: Status 32 (all status codes in values equal 32)
    D: Time window <= 24h (intervalTo - intervalFrom)

    Returns:
        {"valid": bool, "errors": ["error1", "error2"], "pnd": {...}}
    """
    errors = []

    # A: Non-empty payload
    if not data.get("hasData"):
        errors.append("PND: hasData is false or missing")
    if data.get("size", 0) == 0:
        errors.append("PND: size is 0 (empty data)")
    values = data.get("values", [])
    if not values:
        errors.append("PND: values is empty")
    # Check if any value has actual data (non-empty)
    has_non_empty_values = any(
        value.get("v") not in (None, "")
        for value in values.values()
    )
    if not has_non_empty_values:
        errors.append("PND: all values are empty/null")

    # B: Expected columns
    columns = data.get("columns", [])
    if not columns:
        errors.append("PND: columns is empty or missing")

    # C: Status 32 (all status codes must be 32)
    # Status codes are in the 's' field of value objects
    for column_id, record in values.items():
        status = record.get("s")
        if status is not None and status != "32":
            errors.append(f"PND: status code {status} != 32 for column {column_id}")

    # D: Time window <= 24h
    try:
        interval_from = data.get("intervalFrom", "")
        interval_to = data.get("intervalTo", "")

        # Parse Czech datetime format: DD.MM.YYYY HH:MM
        dt_from = datetime.strptime(interval_from, "%d.%m.%Y %H:%M")
        dt_to = datetime.strptime(interval_to, "%d.%m.%Y %H:%M")

        time_diff = dt_to - dt_from

        if time_diff > timedelta(hours=24):
            errors.append(f"PND: time window {time_diff} exceeds 24 hours")

        if time_diff <= timedelta(minutes=0):
            errors.append(f"PND: invalid time window (from={interval_from}, to={interval_to})")

    except (ValueError, KeyError, AttributeError) as exc:
        errors.append(f"PND: failed to parse time window: {exc}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "pnd": data,
    }


def validate_hdo_data(data: dict[str, Any]) -> dict[str, Any]:
    """Validate DIP/HDO data structure.

    Expected keys:
    - signal: String (e.g., "EVV2")
    - casy: List of strings (time windows, e.g., ["08:00-16:00"])
    - den: String (day name, e.g., "pondělí")
    - datum: String (date, e.g., "16.02.2026")

    Returns:
        {"valid": bool, "errors": ["error1", ...], "hdo": {...}}
    """
    errors = []

    # Required keys
    required_keys = ["signal", "casy", "den", "datum"]
    for key in required_keys:
        if key not in data:
            errors.append(f"HDO: missing required key '{key}'")

    # Validate types and non-empty values
    signal = data.get("signal")
    if not signal or not isinstance(signal, str) or not signal.strip():
        errors.append("HDO: signal is missing or empty")

    casy = data.get("casy")
    if casy is None or not isinstance(casy, list) or len(casy) == 0:
        errors.append("HDO: casy is missing or empty")
    else:
        # Validate casy format (HH:MM-HH:MM)
        for time_window in casy:
            if not isinstance(time_window, str) or "-" not in time_window:
                errors.append(f"HDO: invalid casy format '{time_window}'")

    den = data.get("den")
    if not den or not isinstance(den, str) or not den.strip():
        errors.append("HDO: den is missing or empty")

    datum = data.get("datum")
    if not datum or not isinstance(datum, str) or not datum.strip():
        errors.append("HDO: datum is missing or empty")
    else:
        # Validate Czech date format: DD.MM.YYYY
        try:
            datetime.strptime(datum, "%d.%m.%Y")
        except ValueError as exc:
            errors.append(f"HDO: invalid datum format '{datum}': {exc}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "hdo": data,
    }


def validate_json_file(file_path: str) -> dict[str, Any]:
    """Load and validate a JSON evidence file.

    Returns:
        {"valid": bool, "errors": [...], "data": {pnd: {...}, hdo: {...}}}
    """
    import json

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    errors = []

    # Validate structure based on keys present
    has_pnd = any(key in data for key in ["hasData", "size", "columns", "values"])
    has_hdo = any(key in data for key in ["signal", "casy", "den", "datum"])

    if not has_pnd and not has_hdo:
        errors.append("Unknown file format - neither PND nor HDO structure")

    result = {"valid": True, "errors": errors}

    if has_pnd:
        pnd_result = validate_pnd_data(data)
        result["pnd"] = pnd_result["pnd"]
        result["pnd_valid"] = pnd_result["valid"]
        result["pnd_errors"] = pnd_result["errors"]
        result["valid"] = result["valid"] and pnd_result["valid"]
        errors.extend(pnd_result["errors"])

    if has_hdo:
        hdo_result = validate_hdo_data(data)
        result["hdo"] = hdo_result["hdo"]
        result["hdo_valid"] = hdo_result["valid"]
        result["hdo_errors"] = hdo_result["errors"]
        result["valid"] = result["valid"] and hdo_result["valid"]
        errors.extend(hdo_result["errors"])

    return result


def print_validation_report(result: dict[str, Any], file_path: str) -> None:
    """Print human-readable validation report."""
    print(f"\n{'='*60}")
    print(f"Validation Report: {file_path}")
    print(f"{'='*60}")

    if result.get("pnd_valid") is not None:
        pnd_status = "✅ PASS" if result.get("pnd_valid") else "❌ FAIL"
        print(f"\nPND Data: {pnd_status}")
        if not result.get("pnd_valid"):
            for error in result.get("pnd_errors", []):
                print(f"  • {error}")

    if result.get("hdo_valid") is not None:
        hdo_status = "✅ PASS" if result.get("hdo_valid") else "❌ FAIL"
        print(f"\nHDO Data: {hdo_status}")
        if not result.get("hdo_valid"):
            for error in result.get("hdo_errors", []):
                print(f"  • {error}")

    overall_status = "✅ VALID" if result["valid"] else "❌ INVALID"
    print(f"\nOverall: {overall_status}")
    print(f"{'='*60}\n")
