from __future__ import annotations

import asyncio
import json
from typing import Any

DIP_PORTAL_URL = "https://dip.cezdistribuce.cz/irj/portal"
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
        page = await context.new_page()
        try:
            await page.goto(
                f"{DIP_PORTAL_URL}/prehled-om",
                wait_until="domcontentloaded",
                timeout=self.DEFAULT_TIMEOUT,
            )

            try:
                await page.wait_for_function(
                    "() => localStorage.getItem('dip-request-token') !== null",
                    timeout=self.DEFAULT_TIMEOUT,
                )
            except (TimeoutError, asyncio.TimeoutError) as exc:
                raise DipTokenError(
                    "Token not found in localStorage — Angular may not have loaded"
                ) from exc

            token = await page.evaluate(
                "() => localStorage.getItem('dip-request-token')"
            )
            if not token:
                raise DipTokenError("Empty dip-request-token in localStorage")

            result = await page.evaluate(
                """async (args) => {
                const resp = await fetch(args.url, {
                    headers: {
                        'X-Request-Token': args.token,
                        'Accept': 'application/json, text/plain, */*'
                    }
                });
                const contentType = resp.headers.get('content-type') || '';
                const text = await resp.text();
                return { status: resp.status, contentType: contentType, body: text };
            }""",
                {
                    "url": f"{DIP_PORTAL_URL}/{SIGNALS_PATH_TEMPLATE.format(ean=ean)}",
                    "token": token,
                },
            )

            status = result["status"]
            content_type = result["contentType"]
            body = result["body"]

            if status in (400, 503):
                raise DipMaintenanceError(
                    f"Signals endpoint unavailable (HTTP {status})"
                )
            if status != 200:
                raise DipFetchError(f"Signals request failed: HTTP {status}")
            if self._is_html_content_type(content_type):
                raise DipMaintenanceError(
                    "Signals endpoint returned HTML (maintenance page)"
                )

            data = json.loads(body)
            if "data" not in data:
                raise DipFetchError("Data missing from response")
            return data["data"]

        except (DipTokenError, DipFetchError):
            raise
        except (asyncio.TimeoutError, Exception) as exc:
            raise DipFetchError(f"Fetch failed: {exc}") from exc
        finally:
            await page.close()
