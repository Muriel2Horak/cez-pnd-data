from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Playwright  # type: ignore[import-not-found]

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


@dataclass
class AuthSession:
    cookies: list[dict[str, Any]]
    reused: bool
    browser: Browser | None = None
    context: BrowserContext | None = None

    @property
    def has_live_context(self) -> bool:
        return self.context is not None and not self.context.closed  # type: ignore[attr-defined]

    async def close(self) -> None:
        if self.context and not self.context.closed:  # type: ignore[attr-defined]
            await self.context.close()
        if self.browser and self.browser.is_connected():
            await self.browser.close()


class ServiceMaintenanceError(Exception):
    """Raised when CEZ/DIP portal is in planned maintenance mode."""


class PlaywrightAuthClient:
    def __init__(
        self,
        credentials_provider: CredentialsProvider,
        session_store: SessionStore,
        login_runner: Callable[[Credentials], Awaitable[AuthSession]] | None = None,
    ) -> None:
        self._credentials_provider = credentials_provider
        self._session_store = session_store
        self._login_runner = login_runner or self._login_via_playwright
        self._playwright: Playwright | None = None

    async def ensure_session(self) -> AuthSession:
        state = self._session_store.load()
        if state and not self._session_store.is_expired(state):
            live_context = self._session_store.get_live_context()
            if live_context and not live_context.closed:  # type: ignore[attr-defined]
                return AuthSession(
                    cookies=state.cookies,
                    reused=True,
                    context=live_context,
                    browser=self._session_store.get_live_browser(),
                )
            logger.info(
                "Session valid but no live browser context — re-login needed for HDO"
            )
        await self._session_store.close_live_context()
        credentials = self._credentials_provider.get_credentials()
        session = await self._login_runner(credentials)
        self._session_store.save(session.cookies)
        return session

    async def close(self) -> None:
        await self._session_store.close_live_context()
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _login_via_playwright(self, credentials: Credentials) -> AuthSession:
        from playwright.async_api import (  # type: ignore[import-not-found]
            async_playwright,
        )

        logger.info("Starting Playwright login for %s", credentials.email)
        if not self._playwright:
            self._playwright = await async_playwright().start()
        assert self._playwright is not None  # for type checker
        browser = await self._playwright.chromium.launch(headless=True)
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
        self._session_store.set_live_context(context, browser)
        logger.info("Login successful, got %d cookies", len(cookies))
        return AuthSession(
            cookies=[dict(c) for c in cookies],
            reused=False,
            browser=browser,
            context=context,
        )


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
