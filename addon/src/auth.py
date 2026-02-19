from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .session_manager import (
    Credentials,
    CredentialsProvider,
    SessionStore,
)

logger = logging.getLogger(__name__)

PND_BASE_URL = "https://pnd.cezdistribuce.cz/cezpnd2"
PORTAL_URL = "https://dip.cezdistribuce.cz/irj/portal?zpnd"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class AuthSession:
    cookies: list[dict[str, Any]]
    reused: bool


class ServiceMaintenanceError(Exception):
    """Raised when CEZ/DIP portal is in planned maintenance mode."""


class PlaywrightAuthClient:
    def __init__(
        self,
        credentials_provider: CredentialsProvider,
        session_store: SessionStore,
        login_runner: (
            Callable[[Credentials], Awaitable[list[dict[str, Any]]]] | None
        ) = None,
    ) -> None:
        self._credentials_provider = credentials_provider
        self._session_store = session_store
        self._login_runner = login_runner or self._login_via_playwright

    async def ensure_session(self) -> AuthSession:
        state = self._session_store.load()
        if state and not self._session_store.is_expired(state):
            return AuthSession(cookies=state.cookies, reused=True)
        credentials = self._credentials_provider.get_credentials()
        cookies = await self._login_runner(credentials)
        self._session_store.save(cookies)
        return AuthSession(cookies=cookies, reused=False)

    async def _login_via_playwright(
        self, credentials: Credentials
    ) -> list[dict[str, Any]]:
        from playwright.async_api import (  # type: ignore[import-not-found]
            async_playwright,
        )

        logger.info("Starting Playwright login for %s", credentials.email)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                locale="cs-CZ",
                timezone_id="Europe/Prague",
                viewport={"width": 1280, "height": 720},
            )
            page = await context.new_page()

            logger.debug("Navigating to %s", PND_BASE_URL)
            await page.goto(PND_BASE_URL, wait_until="domcontentloaded")
            try:
                await page.wait_for_selector('input[name="username"]', timeout=30_000)
            except Exception:
                logger.debug("Username not found, trying portal URL %s", PORTAL_URL)
                await page.goto(PORTAL_URL, wait_until="domcontentloaded")
                await page.wait_for_selector('input[name="username"]', timeout=120_000)

            login_target = await _get_login_target(page)
            logger.debug("Filling login form")
            await login_target.fill('input[name="username"]', credentials.email)
            await login_target.fill('input[name="password"]', credentials.password)
            submit_locator = login_target.locator(
                'input[type="submit"], button[type="submit"]'
            ).first
            await submit_locator.wait_for(timeout=120_000)
            logger.info("Submitting login form")
            await submit_locator.click()

            logger.debug("Waiting for login success")
            await _wait_for_login_success(page)
            cookies = await context.cookies()
            await browser.close()
            logger.info("Login successful, got %d cookies", len(cookies))
            return [dict(c) for c in cookies]


async def _wait_for_login_success(page: Any) -> None:
    success_pattern = re.compile(
        r".*/(cezpnd2/dashboard/|cezpnd2/external/dashboard/view|irj/portal).*"
    )
    try:
        await page.wait_for_url(success_pattern, timeout=120_000)
    except Exception as exc:
        content = (await page.content()).lower()
        if "odstávka" in content and "právě probíhá odstávka systému" in content:
            raise ServiceMaintenanceError(
                "DIP/PND portal is in maintenance window"
            ) from exc
        raise


async def _get_login_target(page: Any) -> Any:
    for frame in page.frames:
        if (
            await frame.locator('input[name="username"]').count() > 0
            and await frame.locator('input[name="password"]').count() > 0
        ):
            return frame
    return page
