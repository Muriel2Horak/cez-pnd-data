"""Test script to prove shared context hypothesis for HDO fetch.

Usage:
    export CEZ_EMAIL="your-email"
    export CEZ_PASSWORD="your-password"
    export CEZ_EAN="1234567890123"

    python3 scripts/test_shared_context_hypothesis.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from addon.src.auth import DEFAULT_USER_AGENT
from addon.src.dip_client import DIP_PORTAL_URL, SIGNALS_PATH_TEMPLATE

TOKEN_PATH = "rest-auth-api?path=/token/get"

DASHBOARD_URL = "https://pnd.cezdistribuce.cz/cezpnd2/dashboard/view"
PND_ENTRY_URL = "https://pnd.cezdistribuce.cz/cezpnd2"
DIP_FALLBACK_URL = "https://dip.cezdistribuce.cz/irj/portal?zpnd"


async def login_flow(page) -> bool:
    """Execute login flow. Returns True on success."""
    await page.goto(PND_ENTRY_URL, wait_until="domcontentloaded")

    try:
        await page.wait_for_selector('input[name="username"]', timeout=30_000)
    except Exception:
        await page.goto(DIP_FALLBACK_URL, wait_until="domcontentloaded")
        await page.wait_for_selector('input[name="username"]', timeout=120_000)

    login_target = page
    for frame in page.frames:
        if await frame.locator('input[name="username"]').count() > 0:
            login_target = frame
            break

    email = os.getenv("CEZ_EMAIL")
    password = os.getenv("CEZ_PASSWORD")

    await login_target.fill('input[name="username"]', email)
    await login_target.fill('input[name="password"]', password)

    submit = login_target.locator('input[type="submit"], button[type="submit"]').first
    await submit.click()

    success_pattern = re.compile(
        r".*/(cezpnd2/dashboard/|cezpnd2/external/dashboard/view|irj/portal).*"
    )
    await page.wait_for_url(success_pattern, timeout=120_000)
    return True


def create_context_options() -> dict:
    """Get context creation options matching live_verify_flow.py (NO viewport)."""
    return {
        "user_agent": DEFAULT_USER_AGENT,
        "locale": "cs-CZ",
        "timezone_id": "Europe/Prague",
    }


async def fetch_hdo_raw(context, ean: str) -> tuple[int, str, str]:
    """Fetch HDO data and return (status, content_type, body_preview)."""
    token_url = f"{DIP_PORTAL_URL}/{TOKEN_PATH}"
    token_resp = await context.request.get(token_url)

    if token_resp.status != 200:
        body = await token_resp.text()
        return token_resp.status, "token_failed", body[:200]

    try:
        token_data = await token_resp.json()
        token = token_data.get("token")
    except json.JSONDecodeError:
        body = await token_resp.text()
        return token_resp.status, "token_not_json", body[:200]

    if not token:
        body = await token_resp.text()
        return token_resp.status, "token_missing", body[:200]

    signals_url = f"{DIP_PORTAL_URL}/{SIGNALS_PATH_TEMPLATE.format(ean=ean)}"
    signals_resp = await context.request.get(
        signals_url, headers={"x-request-token": token}
    )

    content_type = signals_resp.headers.get("content-type", "")
    body = await signals_resp.text()

    return signals_resp.status, content_type, body[:200]


async def test_a_fresh_context_fails(browser, ean: str) -> dict:
    """Test A: Fresh context + injected cookies (BROKEN pattern from PlaywrightHdoFetcher)."""
    print("\n" + "=" * 60)
    print("TEST A: Fresh context + cookie injection (SHOULD FAIL)")
    print("=" * 60)

    # Step 1: Login and extract cookies
    print("  Step 1: Login and extract cookies...")
    context_login = await browser.new_context(**create_context_options())
    page_login = await context_login.new_page()

    try:
        await login_flow(page_login)
        print("    Login successful")
    except Exception as e:
        await context_login.close()
        return {"pass": False, "error": f"Login failed: {e}"}

    cookies = await context_login.cookies()
    print(f"    Extracted {len(cookies)} cookies")

    # Step 2: Close login context (simulate session loss)
    print("  Step 2: Close login context...")
    await context_login.close()

    # Step 3: Create NEW fresh context and inject cookies (PlaywrightHdoFetcher pattern)
    print("  Step 3: Create NEW context and inject cookies...")
    context_fresh = await browser.new_context(**create_context_options())
    await context_fresh.add_cookies(cookies)
    print(f"    Injected {len(cookies)} cookies into fresh context")

    # Step 4: Try HDO fetch
    print("  Step 4: Fetch HDO data...")
    try:
        status, content_type, body_preview = await fetch_hdo_raw(context_fresh, ean)
        print(f"    Status: {status}")
        print(f"    Content-Type: {content_type}")
        print(f"    Response preview: {body_preview[:100]}...")
    except Exception as e:
        await context_fresh.close()
        return {"pass": False, "error": f"Fetch failed: {e}"}
    finally:
        await context_fresh.close()

    # Determine if this is the expected FAILURE
    is_html = "text/html" in content_type.lower() or status != 200
    expected = is_html  # We expect this to fail (HTML or non-200)

    result = {
        "status": status,
        "content_type": content_type,
        "body_preview": body_preview,
        "is_html": is_html,
        "expected_failure": expected,
    }

    if expected:
        print("\n  RESULT: PASS (correctly reproduced broken pattern)")
        print("    → DIP returned HTML/error instead of JSON")
    else:
        print("\n  RESULT: UNEXPECTED (got valid data - hypothesis may be wrong)")

    return result


async def test_b_shared_context_succeeds(browser, ean: str) -> dict:
    """Test B: Shared context (WORKING pattern from live_verify_flow.py)."""
    print("\n" + "=" * 60)
    print("TEST B: Shared context (SHOULD SUCCEED)")
    print("=" * 60)

    # Step 1: Login with context that will be reused
    print("  Step 1: Login (keeping same context)...")
    context = await browser.new_context(**create_context_options())
    page = await context.new_page()

    try:
        await login_flow(page)
        print("    Login successful")
    except Exception as e:
        await context.close()
        return {"pass": False, "error": f"Login failed: {e}"}

    # Step 2: Navigate to dashboard + 5s wait (critical for session)
    print("  Step 2: Navigate to dashboard + 5s wait...")
    await page.goto(DASHBOARD_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)
    print("    Dashboard loaded, wait complete")

    # Step 3: Fetch HDO using SAME context
    print("  Step 3: Fetch HDO data (same context)...")
    try:
        status, content_type, body_preview = await fetch_hdo_raw(context, ean)
        print(f"    Status: {status}")
        print(f"    Content-Type: {content_type}")
        print(f"    Response preview: {body_preview[:100]}...")
    except Exception as e:
        await context.close()
        return {"pass": False, "error": f"Fetch failed: {e}"}
    finally:
        await context.close()

    # Determine if this is the expected SUCCESS
    is_json = "application/json" in content_type.lower() and status == 200
    has_data = "data" in body_preview or "signal" in body_preview.lower()

    result = {
        "status": status,
        "content_type": content_type,
        "body_preview": body_preview,
        "is_json": is_json,
        "has_hdo_data": is_json and has_data,
    }

    if is_json and has_data:
        print("\n  RESULT: PASS (correctly reproduced working pattern)")
        print("    → DIP returned valid HDO JSON data")
    else:
        print("\n  RESULT: UNEXPECTED (failed to get HDO data)")

    return result


async def async_main() -> int:
    """Run both tests and report results."""
    email = os.getenv("CEZ_EMAIL")
    password = os.getenv("CEZ_PASSWORD")
    ean = os.getenv("CEZ_EAN")

    if not all([email, password, ean]):
        print("ERROR: Missing required environment variables")
        print("Required: CEZ_EMAIL, CEZ_PASSWORD, CEZ_EAN")
        return 1

    print("=" * 60)
    print("SHARED CONTEXT HYPOTHESIS TEST")
    print("=" * 60)
    print(f"Email: {email[:3]}***@***")
    print(f"EAN: {ean}")
    print(f"Time: {datetime.now().isoformat()}")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)

        try:
            # Run Test A (should fail)
            result_a = await test_a_fresh_context_fails(browser, ean)

            # Run Test B (should succeed)
            result_b = await test_b_shared_context_succeeds(browser, ean)

        finally:
            await browser.close()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    test_a_passed = result_a.get("expected_failure", False)
    test_b_passed = result_b.get("has_hdo_data", False)

    print(f"\nTest A (Fresh Context):     {'PASS' if test_a_passed else 'FAIL'}")
    print("  → Expected: HTML/error (reproduces broken pattern)")
    print(f"  → Got: status={result_a.get('status')}, html={result_a.get('is_html')}")

    print(f"\nTest B (Shared Context):    {'PASS' if test_b_passed else 'FAIL'}")
    print("  → Expected: Valid HDO JSON data")
    print(f"  → Got: status={result_b.get('status')}, json={result_b.get('is_json')}")

    # Final verdict
    hypothesis_confirmed = test_a_passed and test_b_passed

    print("\n" + "=" * 60)
    if hypothesis_confirmed:
        print("HYPOTHESIS CONFIRMED: Shared context is required for HDO fetch")
        print("  → Fresh context + cookies = DIP returns HTML/error")
        print("  → Shared context = DIP returns valid HDO data")
    else:
        print("HYPOTHESIS NOT CONFIRMED: Results unexpected")
        print("  → Further investigation needed")
    print("=" * 60)

    # Save evidence
    evidence_dir = Path(".sisyphus/evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_file = evidence_dir / "task-1-hypothesis-test-output.txt"

    with open(evidence_file, "w") as f:
        f.write("SHARED CONTEXT HYPOTHESIS TEST OUTPUT\n")
        f.write(f"Time: {datetime.now().isoformat()}\n")
        f.write(f"EAN: {ean}\n\n")
        f.write("TEST A (Fresh Context - should fail):\n")
        f.write(f"  {json.dumps(result_a, indent=2)}\n\n")
        f.write("TEST B (Shared Context - should succeed):\n")
        f.write(f"  {json.dumps(result_b, indent=2)}\n\n")
        f.write(f"HYPOTHESIS CONFIRMED: {hypothesis_confirmed}\n")

    print(f"\nEvidence saved to: {evidence_file}")

    return 0 if hypothesis_confirmed else 1


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
