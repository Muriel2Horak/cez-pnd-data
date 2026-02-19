# PND API client – fetch data via aiohttp
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .auth import DEFAULT_USER_AGENT
from .cookie_utils import playwright_cookies_to_header
from .orchestrator import SessionExpiredError


class PndFetchError(Exception):
    pass


class PndClient:
    PND_API_URL = "https://pnd.cezdistribuce.cz/cezpnd2/external/data"
    DEFAULT_TIMEOUT = 30

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def fetch_data(
        self,
        cookies: list[dict[str, Any]],
        *,
        assembly_id: int,
        date_from: str,
        date_to: str,
        electrometer_id: str,
    ) -> dict[str, Any]:
        payload = {
            "format": "table",
            "idAssembly": assembly_id,
            "idDeviceSet": None,
            "intervalFrom": date_from,
            "intervalTo": date_to,
            "compareFrom": None,
            "opmId": None,
            "electrometerId": electrometer_id,
        }
        headers = {
            "Cookie": playwright_cookies_to_header(cookies),
            "User-Agent": DEFAULT_USER_AGENT,
            "Content-Type": "application/json",
        }
        try:
            async with self._session.post(
                self.PND_API_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.DEFAULT_TIMEOUT),
                allow_redirects=False,
            ) as resp:
                if resp.status == 401:
                    raise SessionExpiredError("PND API returned 401")
                if resp.status != 200:
                    raise PndFetchError(f"PND API returned {resp.status}")
                return await resp.json()
        except SessionExpiredError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, Exception) as exc:
            raise PndFetchError(f"PND fetch failed: {exc}") from exc
