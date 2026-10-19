"""PND wire format and errors shared by authentication and polling."""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

PND_DATA_URL = "https://pnd.cezdistribuce.cz/cezpnd2/external/data"
PND_DEFINITION_URL = (
    "https://pnd.cezdistribuce.cz/cezpnd2/external/dashboard/window/definition"
)


class SessionExpiredError(Exception):
    """Raised when the CEZ session is expired or rejected (e.g. HTTP 401)."""


class ServiceMaintenanceError(Exception):
    """Raised when CEZ/DIP portal is in planned maintenance mode."""


class PndFetchError(Exception):
    """Raised when PND data fetch fails (non-200 response, network error, etc.)."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def build_pnd_payload(
    assembly_id: int, date_from: str, date_to: str, electrometer_id: Optional[str]
) -> dict[str, Any]:
    return {
        "format": "table",
        "idAssembly": assembly_id,
        "idDeviceSet": None,
        "intervalFrom": date_from,
        "intervalTo": date_to,
        "compareFrom": None,
        "opmId": None,
        "electrometerId": electrometer_id or "",
    }


async def request_data(
    context: Any,
    meter_id: Optional[str],
    assembly_id: int,
    date_from: str,
    date_to: str,
) -> dict[str, Any]:
    payload = build_pnd_payload(assembly_id, date_from, date_to, meter_id)
    response = await context.request.post(
        PND_DATA_URL,
        # Preserve the original request's JSON encoding. URL-encoded forms are
        # rejected by the portal protection layer before reaching PND.
        data={k: "" if v is None else v for k, v in payload.items()},
        max_redirects=0,
    )
    data = await _read_json_response(response, assembly_id)
    if not isinstance(data, dict) or not isinstance(data.get("hasData"), bool):
        raise PndFetchError("PND response is missing hasData")
    if data["hasData"] and not all(
        isinstance(data.get(k), list) for k in ("columns", "values")
    ):
        raise PndFetchError("PND response has invalid columns/values")
    logger.debug(
        "PND fetch assembly=%d status=%d hasData=%s",
        assembly_id,
        response.status,
        data["hasData"],
    )
    return data


async def request_meter_ids(context: Any) -> list[str]:
    """Read available meters without requiring a selected meter or readings."""
    response = await context.request.get(PND_DEFINITION_URL, max_redirects=0)
    data = await _read_json_response(response, None)
    if not isinstance(data, dict) or not isinstance(data.get("electrometers"), list):
        raise PndFetchError("PND definition has invalid electrometers")
    ids = set()
    for meter in data["electrometers"]:
        value = meter.get("value") if isinstance(meter, dict) else None
        if not isinstance(value, str) or not value.strip():
            raise PndFetchError("PND definition has invalid meter ID")
        ids.add(value.strip())
    return sorted(ids)


async def _read_json_response(response: Any, assembly_id: Optional[int]) -> Any:
    if response.status in (301, 302, 303, 307, 308, 401, 403):
        raise SessionExpiredError(f"PND session rejected (HTTP {response.status})")
    if response.status != 200:
        raise PndFetchError(
            f"PND fetch failed with status {response.status}", response.status
        )
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        text = (await response.text()).lower()
        if "odstávka" in text or "odstavka" in text:
            category = "maintenance"
        elif any(
            marker in text
            for marker in ('name="username"', "name='username'", "oauth", "login")
        ):
            category = "login"
        elif any(
            marker in text
            for marker in (
                "the requested url was rejected",
                "request rejected",
                "access denied",
                "captcha",
                "checking your browser",
            )
        ):
            category = "portal-protection"
        else:
            category = "unrecognized-html"
        # Log only fixed categories, never response HTML, cookies or tokens.
        logger.warning(
            "PND fetch returned non-JSON response "
            "(HTTP %d, Content-Type: %s, category: %s, assembly: %s, body length: %d)",
            response.status,
            content_type,
            category,
            assembly_id,
            len(text),
        )
        if category == "maintenance":
            raise ServiceMaintenanceError("PND portal is in maintenance")
        if category == "login":
            raise SessionExpiredError("PND fetch returned a login page")
        raise PndFetchError(
            f"PND fetch returned non-JSON response "
            f"(Content-Type: {content_type}, category: {category})"
        )
    try:
        data = await response.json()
    except Exception as exc:
        logger.warning("PND fetch JSON parse failed: %s", exc)
        raise PndFetchError(f"PND fetch JSON parse failed: {exc}") from exc
    return data
