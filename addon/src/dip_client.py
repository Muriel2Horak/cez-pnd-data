from __future__ import annotations

import asyncio
from typing import Any

from .auth import DEFAULT_USER_AGENT

DIP_PORTAL_URL = "https://dip.cezdistribuce.cz/irj/portal"
TOKEN_PATH = "rest-auth-api?path=/token/get"
SIGNALS_PATH_TEMPLATE = "prehled-om?path=supply-point-detail/signals/{ean}"


class DipTokenError(Exception):
    """Raised when token acquisition fails."""


class DipFetchError(Exception):
    """Raised when HDO signals fetch fails."""


class DipMaintenanceError(DipFetchError):
    """Raised when DIP endpoint is temporarily unavailable (maintenance)."""


class DipClient:
    """DIP API client for HDO tariff data."""

    DEFAULT_TIMEOUT = 30_000

    @staticmethod
    def _is_html_content_type(content_type: str | None) -> bool:
        return content_type is not None and "text/html" in content_type.lower()

    async def fetch_hdo(self, context: Any, ean: str) -> dict[str, Any]:
        try:
            token_resp = await context.request.get(
                f"{DIP_PORTAL_URL}/{TOKEN_PATH}",
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=self.DEFAULT_TIMEOUT,
            )
            if token_resp.status in {400, 503}:
                raise DipMaintenanceError(
                    f"Token endpoint unavailable (HTTP {token_resp.status})"
                )
            if token_resp.status != 200:
                raise DipTokenError(f"Token request failed: HTTP {token_resp.status}")
            content_type = token_resp.headers.get("content-type", "")
            if self._is_html_content_type(content_type):
                raise DipMaintenanceError(
                    "Token endpoint returned HTML (maintenance page)"
                )
            token_data = await token_resp.json()
            if "token" not in token_data:
                raise DipTokenError("Token missing from response")
            token = token_data["token"]

            signals_resp = await context.request.get(
                f"{DIP_PORTAL_URL}/{SIGNALS_PATH_TEMPLATE.format(ean=ean)}",
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "x-request-token": token,
                },
                timeout=self.DEFAULT_TIMEOUT,
            )
            if signals_resp.status in {400, 503}:
                raise DipMaintenanceError(
                    f"Signals endpoint unavailable (HTTP {signals_resp.status})"
                )
            if signals_resp.status != 200:
                raise DipFetchError(
                    f"Signals request failed: HTTP {signals_resp.status}"
                )
            content_type = signals_resp.headers.get("content-type", "")
            if self._is_html_content_type(content_type):
                raise DipMaintenanceError(
                    "Signals endpoint returned HTML (maintenance page)"
                )
            data = await signals_resp.json()
            if "data" not in data:
                raise DipFetchError("Data missing from response")
            return data["data"]

        except (DipTokenError, DipFetchError):
            raise
        except (asyncio.TimeoutError, Exception) as exc:
            raise DipFetchError(f"Fetch failed: {exc}") from exc
