from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta

from playwright.async_api import async_playwright  # type: ignore[import-not-found]


USERNAME = "test@example.com"
PASSWORD = "testpassword123"
ELECTROMETER_ID = "784703"

PND_BASE_URL = "https://pnd.cezdistribuce.cz/cezpnd2"
PORTAL_URL = "https://dip.cezdistribuce.cz/irj/portal?zpnd"
DASHBOARD_URL = f"{PND_BASE_URL}/external/dashboard/view"
DATA_ENDPOINT = f"{PND_BASE_URL}/external/data"

EVIDENCE_DIR = os.path.join(os.path.dirname(__file__), "evidence")
DATA_PATH = os.path.join(EVIDENCE_DIR, "pnd-playwright-data.json")
SCREENSHOT_PATH = os.path.join(EVIDENCE_DIR, "playwright-auth-success.png")


def _format_pnd_datetime(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y %H:%M")


async def _wait_for_login_success(page) -> None:
    success_pattern = re.compile(
        r".*/(cezpnd2/dashboard/|cezpnd2/external/dashboard/view|irj/portal).*"
    )
    await page.wait_for_url(success_pattern, timeout=120_000)


async def _get_login_target(page):
    for frame in page.frames:
        if (
            await frame.locator('input[name="username"]').count() > 0
            and await frame.locator('input[name="password"]').count() > 0
        ):
            return frame
    return page


async def main() -> int:
    os.makedirs(EVIDENCE_DIR, exist_ok=True)

    today = datetime.now().date()
    interval_to = datetime.combine(today, datetime.min.time())
    interval_from = interval_to - timedelta(days=1)
    payload = {
        "format": "table",
        "idAssembly": -1003,
        "idDeviceSet": None,
        "intervalFrom": _format_pnd_datetime(interval_from),
        "intervalTo": _format_pnd_datetime(interval_to),
        "compareFrom": None,
        "opmId": None,
        "electrometerId": ELECTROMETER_ID,
    }
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": DASHBOARD_URL,
    }

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="cs-CZ",
            timezone_id="Europe/Prague",
            viewport={"width": 1280, "height": 720},
        )
        page = await context.new_page()

        start_url = PND_BASE_URL
        print(f"Step 1: Navigating to {start_url}", flush=True)
        await page.goto(start_url, wait_until="domcontentloaded")

        print("Step 2: Waiting for CAS login form", flush=True)
        try:
            await page.wait_for_selector('input[name="username"]', timeout=30_000)
        except Exception:
            print(f"CAS login not detected, navigating to {PORTAL_URL}", flush=True)
            await page.goto(PORTAL_URL, wait_until="domcontentloaded")
            await page.wait_for_selector('input[name="username"]', timeout=120_000)

        login_target = await _get_login_target(page)
        await login_target.fill('input[name="username"]', USERNAME)
        await login_target.fill('input[name="password"]', PASSWORD)
        submit_locator = login_target.locator('input[type="submit"], button[type="submit"]').first
        await submit_locator.wait_for(timeout=120_000)
        await submit_locator.click()

        print("Step 3: Waiting for login success", flush=True)
        await _wait_for_login_success(page)

        print("Step 4: Capturing success screenshot", flush=True)
        await page.screenshot(path=SCREENSHOT_PATH, full_page=True)

        cookies = await context.cookies()
        cookie_names = {cookie["name"] for cookie in cookies}
        needed = {"JSESSIONID", "TGC", "DISSESSION"}
        print(f"Cookies captured: {sorted(cookie_names)}", flush=True)
        missing = sorted(needed - cookie_names)
        if missing:
            print(f"Warning: missing cookies {missing}", flush=True)

        print("Step 5: Navigating to dashboard", flush=True)
        await page.goto(DASHBOARD_URL, wait_until="domcontentloaded")

        print("Step 6: Fetching meter data", flush=True)
        response = await context.request.post(
            DATA_ENDPOINT,
            data=json.dumps(payload),
            headers=headers,
        )
        if response.status != 200:
            body_text = await response.text()
            print(
                f"Data fetch failed: HTTP {response.status}\n{body_text[:500]}",
                flush=True,
            )
            await browser.close()
            return 1
        try:
            data = await response.json()
        except Exception:
            body_text = await response.text()
            print(
                f"Data fetch failed: invalid JSON\n{body_text[:500]}",
                flush=True,
            )
            await browser.close()
            return 1
        with open(DATA_PATH, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)

        print("Meter data saved:", DATA_PATH, flush=True)
        print("PLAYWRIGHT TEST: PASS", flush=True)
        await browser.close()
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
