"""DIP API client – HDO signals via aiohttp with Playwright cookies."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .auth import DEFAULT_USER_AGENT
from .cookie_utils import playwright_cookies_to_header

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

    DEFAULT_TIMEOUT = 30  # seconds

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    @staticmethod
    def _is_html_content_type(content_type: str | None) -> bool:
        """Check if Content-Type header indicates HTML response.

        Args:
            content_type: Value of Content-Type header (may be None)

        Returns:
            True if content type indicates HTML (maintenance page), False otherwise
        """
        return content_type is not None and "text/html" in content_type.lower()

    async def fetch_hdo(
        self, cookies: list[dict[str, Any]], ean: str
    ) -> dict[str, Any]:
        """Fetch HDO signals using aiohttp with Playwright cookies."""
        cookie_header = playwright_cookies_to_header(cookies)
        headers = {
            "Cookie": cookie_header,
            "User-Agent": DEFAULT_USER_AGENT,
        }
        timeout = aiohttp.ClientTimeout(total=self.DEFAULT_TIMEOUT)

        try:
            # Step 1: Get token
            async with self._session.get(
                f"{DIP_PORTAL_URL}/{TOKEN_PATH}",
                headers=headers,
                timeout=timeout,
            ) as token_resp:
                if token_resp.status in {400, 503}:
                    raise DipMaintenanceError(
                        f"Token endpoint unavailable (HTTP {token_resp.status})"
                    )
                if token_resp.status != 200:
                    raise DipTokenError(
                        f"Token request failed: HTTP {token_resp.status}"
                    )
                content_type = token_resp.headers.get("Content-Type", "")
                if self._is_html_content_type(content_type):
                    raise DipMaintenanceError(
                        "Token endpoint returned HTML (maintenance page)"
                    )
                token_data = await token_resp.json()
                if "token" not in token_data:
                    raise DipTokenError("Token missing from response")
                token = token_data["token"]

            # Step 2: Get signals with x-request-token header
            signal_headers = {**headers, "x-request-token": token}
            async with self._session.get(
                f"{DIP_PORTAL_URL}/{SIGNALS_PATH_TEMPLATE.format(ean=ean)}",
                headers=signal_headers,
                timeout=timeout,
            ) as signals_resp:
                if signals_resp.status in {400, 503}:
                    raise DipMaintenanceError(
                        f"Signals endpoint unavailable (HTTP {signals_resp.status})"
                    )
                if signals_resp.status != 200:
                    raise DipFetchError(
                        f"Signals request failed: HTTP {signals_resp.status}"
                    )
                content_type = signals_resp.headers.get("Content-Type", "")
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
        except (aiohttp.ClientError, asyncio.TimeoutError, Exception) as exc:
            raise DipFetchError(f"Fetch failed: {exc}") from exc
