"""Live verification runner - Playwright login → Playwright request → JSON evidence + validation.

Usage:
    export CEZ_EMAIL="your-email"
    export CEZ_PASSWORD="your-password"
    export CEZ_ELECTROMETER_ID="784703"
    export CEZ_EAN="1234567890123"  # Optional

    python3 scripts/live_verify_flow.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from addon.src.auth import DEFAULT_USER_AGENT
from addon.src.pnd_client import PndClient
from scripts import live_verify_rules as validation

PND_DATA_URL = "https://pnd.cezdistribuce.cz/cezpnd2/external/data"
DIP_PORTAL_URL = "https://dip.cezdistribuce.cz/irj/portal"
DIP_TOKEN_PATH = "rest-auth-api?path=/token/get"
DIP_SIGNALS_PATH = "prehled-om?path=supply-point-detail/signals/{ean}"


def get_timestamp() -> str:
    """Generate timestamp for filename: YYYYMMDD_HHMMSS"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_evidence_dir() -> Path:
    """Create evidence directory if not exists."""
    evidence_dir = Path("evidence/live-fetch")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    return evidence_dir


def build_pnd_payload(
    assembly_id: int, date_from: str, date_to: str, electrometer_id: str
) -> dict:
    """Build PND API payload."""
    return {
        "format": "table",
        "idAssembly": assembly_id,
        "idDeviceSet": None,
        "intervalFrom": date_from,
        "intervalTo": date_to,
        "compareFrom": None,
        "opmId": None,
        "electrometerId": electrometer_id,
    }


async def async_main() -> int:
    """Main verification flow using Playwright for both login and API calls."""
    # Read credentials from environment
    email = os.getenv("CEZ_EMAIL")
    password = os.getenv("CEZ_PASSWORD")
    electrometer_id = os.getenv("CEZ_ELECTROMETER_ID")
    ean = os.getenv("CEZ_EAN")

    if not all([email, password, electrometer_id]):
        print("ERROR: Missing required environment variables")
        print("Required: CEZ_EMAIL, CEZ_PASSWORD, CEZ_ELECTROMETER_ID")
        print("Optional: CEZ_EAN (for HDO data)")
        return 1

    print(f"Starting live verification...")
    print(f"Electrometer ID: {electrometer_id}")
    if ean:
        print(f"EAN: {ean}")
    print()

    try:
        async with async_playwright() as playwright:
            # Step 1: Launch browser and login
            print("Step 1: Playwright login...")
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                locale="cs-CZ",
                timezone_id="Europe/Prague",
            )
            page = await context.new_page()

            # Navigate to PND
            await page.goto(
                "https://pnd.cezdistribuce.cz/cezpnd2", wait_until="domcontentloaded"
            )

            try:
                await page.wait_for_selector('input[name="username"]', timeout=30_000)
            except Exception:
                await page.goto(
                    "https://dip.cezdistribuce.cz/irj/portal?zpnd",
                    wait_until="domcontentloaded",
                )
                await page.wait_for_selector('input[name="username"]', timeout=120_000)

            # Find login form (might be in iframe)
            login_target = page
            for frame in page.frames:
                if await frame.locator('input[name="username"]').count() > 0:
                    login_target = frame
                    break

            # Fill credentials
            await login_target.fill('input[name="username"]', email)
            await login_target.fill('input[name="password"]', password)

            # Submit
            submit = login_target.locator(
                'input[type="submit"], button[type="submit"]'
            ).first
            await submit.click()

            # Wait for success
            import re

            success_pattern = re.compile(
                r".*/(cezpnd2/dashboard/|cezpnd2/external/dashboard/view|irj/portal).*"
            )
            await page.wait_for_url(success_pattern, timeout=120_000)

            print("✓ Login successful")

            # Navigate to PND dashboard to establish session
            await page.goto(
                "https://pnd.cezdistribuce.cz/cezpnd2/dashboard/view",
                wait_until="domcontentloaded",
            )
            await page.wait_for_timeout(5000)  # Wait for session

            # Step 2: Fetch PND data using Playwright's request API
            print("Step 2: Fetching PND data...")
            today = datetime.now()
            date_from = today.strftime("%d.%m.%Y 00:00")
            date_to = today.strftime("%d.%m.%Y 23:59")

            payload = build_pnd_payload(-1003, date_from, date_to, electrometer_id)

            print(f"  Payload: {json.dumps(payload, indent=2)}")

            # WAF warmup: Send JSON request first (will fail with 400, but sets WAF cookies/state)
            print("  WAF warmup (JSON request)...")
            try:
                warmup_response = await context.request.post(
                    PND_DATA_URL,
                    data=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                )
                print(f"    Warmup status: {warmup_response.status} (expected 400)")
            except Exception as e:
                print(f"    Warmup failed: {e} (expected)")

            await page.wait_for_timeout(1000)

            # Now the actual form request (should work after warmup)
            print("  Sending form request...")
            response = await context.request.post(
                PND_DATA_URL,
                data=payload,
            )

            print(f"  Response status: {response.status}")
            print(f"  Response URL: {response.url}")

            raw_text = await response.text()
            print(f"  Response length: {len(raw_text)} chars")
            try:
                pnd_data = json.loads(raw_text)
            except json.JSONDecodeError:
                print(f"✗ Response is not valid JSON")
                print(f"  Response preview: {raw_text[:1000]}")
                return 1

            if response.status != 200:
                print(f"✗ PND API returned {response.status}")
                print(f"  Response preview: {raw_text[:500]}")
                return 1

            print(f"✓ PND data fetched, size: {pnd_data.get('size', 0)}")

            # Step 3: Fetch HDO data (optional)
            hdo_data = None
            if ean:
                print("Step 3: Fetching HDO data...")
                try:
                    # Get token
                    token_url = f"{DIP_PORTAL_URL}/{DIP_TOKEN_PATH}"
                    token_resp = await context.request.get(token_url)
                    if token_resp.status == 200:
                        token_data = await token_resp.json()
                        token = token_data.get("token")

                        # Get signals
                        signals_url = (
                            f"{DIP_PORTAL_URL}/{DIP_SIGNALS_PATH.format(ean=ean)}"
                        )
                        signals_resp = await context.request.get(
                            signals_url, headers={"x-request-token": token}
                        )
                        if signals_resp.status == 200:
                            signals_data = await signals_resp.json()
                            hdo_data = signals_data.get("data")
                            print("✓ HDO data fetched")
                except Exception as exc:
                    print(f"⚠ HDO fetch failed: {exc}")

            # Step 4: Prepare evidence data
            print("Step 4: Preparing evidence data...")
            evidence_data = {
                "metadata": {
                    "fetched_at": datetime.now().isoformat(),
                    "electrometer_id": electrometer_id,
                    "ean": ean,
                },
                "pnd": pnd_data,
            }
            if hdo_data:
                evidence_data["hdo"] = hdo_data

            # Step 5: Save evidence
            print("Step 5: Saving evidence...")
            evidence_dir = ensure_evidence_dir()
            timestamp = get_timestamp()
            filename = f"pnd-{electrometer_id}-{timestamp}.json"
            filepath = evidence_dir / filename

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(evidence_data, f, indent=2, ensure_ascii=False)

            print(f"✓ Evidence saved: {filepath}")
            print()

            # Step 6: Validate
            print("Step 6: Validating evidence...")
            result = validation.validate_json_file(str(filepath))
            validation.print_validation_report(result, str(filepath))

            # Summary
            print("=" * 60)
            print("LIVE VERIFICATION SUMMARY")
            print("=" * 60)

            if result["valid"]:
                print("✓ VALIDATION PASSED")
                print()
                print("Evidence file contains valid CEZ PND data.")
                if hdo_data:
                    print("Both PND and HDO data successfully fetched and validated.")
                print()
                print(f"File: {filepath}")
                return 0
            else:
                print("✗ VALIDATION FAILED")
                print()
                print("Errors found:")
                for i, error in enumerate(result["errors"], 1):
                    print(f"  {i}. {error}")
                print()
                print(f"File: {filepath}")
                return 1

    except Exception as exc:
        print(f"\n✗ FATAL ERROR: {exc}")
        import traceback

        traceback.print_exc()
        return 1


def main() -> int:
    """Entry point."""
    return asyncio.run(async_main())


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
