#!/usr/bin/env python3
"""
Test 2: New Playwright Context + add_cookies (PndFetcher Clone)

This test creates a new context, adds cookies from login, and tests two variants:
1. Form encoding (data=dict) - PndFetcher approach
2. JSON string (json.dumps with headers) - live_verify_flow approach
"""

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from playwright.async_api import Page, Response, async_playwright

# Constants
DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
PND_DATA_URL = "https://pnd.cezdistribuce.cz/cezpnd2/external/data"

# Get environment variables
EMAIL = os.getenv("CEZ_EMAIL", "horak.martin@seznam.cz")
PASSWORD = os.getenv("CEZ_PASSWORD", "horak123")
ELECTROMETER_ID = os.getenv("CEZ_ELECTROMETER_ID", "784703")


def build_pnd_payload(
    assembly_id: int,
    date_from: str,
    date_to: str,
    electrometer_id: Optional[str],
) -> Dict[str, Any]:
    """Build PND data request payload."""
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


async def login_flow(page: Page) -> bool:
    """Perform login to CEZ PND/DIP."""
    try:
        # Navigate to PND
        await page.goto("https://pnd.cezdistribuce.cz/cezpnd2", wait_until="domcontentloaded")
        
        try:
            await page.wait_for_selector('input[name="username"]', timeout=30_000)
        except Exception:
            await page.goto("https://dip.cezdistribuce.cz/irj/portal?zpnd", wait_until="domcontentloaded")
            await page.wait_for_selector('input[name="username"]', timeout=120_000)

        # Find login form (might be in iframe)
        login_target = page
        for frame in page.frames:
            if await frame.locator('input[name="username"]').count() > 0:
                login_target = frame
                break

        # Fill credentials
        await login_target.fill('input[name="username"]', EMAIL)
        await login_target.fill('input[name="password"]', PASSWORD)
        
        # Submit
        submit = login_target.locator('input[type="submit"], button[type="submit"]').first
        await submit.click()
        
        # Wait for success
        import re
        success_pattern = re.compile(r".*/(cezpnd2/dashboard/|cezpnd2/external/dashboard/view|irj/portal).*")
        await page.wait_for_url(success_pattern, timeout=120_000)
        
        return True
    except Exception as e:
        print(f"Login failed: {e}")
        return False


def format_cookies_for_output(cookies):
    """Format cookies for JSON output."""
    return [
        {
            "name": cookie["name"],
            "value": cookie["value"],
            "domain": cookie.get("domain", ""),
            "path": cookie.get("path", "/"),
            "expires": cookie.get("expires", -1),
            "httpOnly": cookie.get("httpOnly", False),
            "secure": cookie.get("secure", False),
            "sameSite": cookie.get("sameSite", "Lax")
        }
        for cookie in cookies
    ]


def compare_cookies(before, after):
    """Compare cookies before and after add_cookies."""
    if len(before) != len(after):
        return f"Cookie count mismatch: before={len(before)}, after={len(after)}"
    
    # Simple comparison of key attributes
    for cookie_before, cookie_after in zip(before, after):
        for key in ["name", "value", "domain", "path"]:
            if cookie_before.get(key) != cookie_after.get(key):
                return f"Cookie {cookie_before['name']} attribute {key} mismatch: {cookie_before.get(key)} != {cookie_after.get(key)}"
    
    return "Cookies preserved correctly"


async def test_form_data_variant(context, cookies, payload):
    """Test form data variant (data=dict) - PndFetcher approach."""
    try:
        response = await context.request.post(
            PND_DATA_URL,
            data=payload,
        )
        
        # Get response details
        response_data = await response.text()
        
        return {
            "status": response.status,
            "headers": dict(response.headers),
            "body_preview": response_data[:1000] if response_data else "",
            "is_json": "application/json" in response.headers.get("content-type", ""),
            "is_html": "text/html" in response.headers.get("content-type", ""),
            "verdict": "PASS" if response.status == 200 else "FAIL",
            "verdict_reason": f"Status code {response.status}" + (" - Success" if response.status == 200 else " - Failed")
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "headers": {},
            "body_preview": str(e),
            "is_json": False,
            "is_html": False,
            "verdict": "FAIL",
            "verdict_reason": f"Exception: {str(e)}"
        }


async def test_json_string_variant(context, cookies, payload):
    """Test JSON string variant (json.dumps with headers) - live_verify_flow approach."""
    try:
        response = await context.request.post(
            PND_DATA_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"}
        )
        
        # Get response details
        response_data = await response.text()
        
        return {
            "status": response.status,
            "headers": dict(response.headers),
            "body_preview": response_data[:1000] if response_data else "",
            "is_json": "application/json" in response.headers.get("content-type", ""),
            "is_html": "text/html" in response.headers.get("content-type", ""),
            "verdict": "PASS" if response.status == 200 else "FAIL",
            "verdict_reason": f"Status code {response.status}" + (" - Success" if response.status == 200 else " - Failed")
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "headers": {},
            "body_preview": str(e),
            "is_json": False,
            "is_html": False,
            "verdict": "FAIL",
            "verdict_reason": f"Exception: {str(e)}"
        }


async def main():
    """Main test function."""
    results = {
        "test_name": "test_2_new_context",
        "timestamp": datetime.now().isoformat(),
        "login": {
            "success": False,
            "final_url": ""
        },
        "variants": {},
        "cookies": {
            "before_add": [],
            "after_add": [],
            "diff": ""
        },
        "verdict": "FAIL",
        "verdict_reason": "Test not completed",
        "error": None
    }

    # Login and extract cookies
    async with async_playwright() as playwright:
        browser1 = await playwright.chromium.launch(headless=True)
        context1 = await browser1.new_context(
            user_agent=DEFAULT_USER_AGENT,
            locale="cs-CZ",
            timezone_id="Europe/Prague",
        )
        page1 = await context1.new_page()

        try:
            # Perform login
            login_success = await login_flow(page1)
            results["login"]["success"] = login_success
            results["login"]["final_url"] = page1.url

            if not login_success:
                results["verdict"] = "FAIL"
                results["verdict_reason"] = "Login failed"
                results["error"] = "Login process failed"
                return results

            # Extract cookies
            login_cookies = await context1.cookies()
            results["cookies"]["before_add"] = format_cookies_for_output(login_cookies)
            
            # Close browser and context (important for PndFetcher clone test)
            await page1.close()
            await context1.close()
            await browser1.close()

            # Create NEW browser and context (PndFetcher clone)
            browser2 = await playwright.chromium.launch(headless=True)
            context2 = await browser2.new_context()

            # Add cookies to new context
            await context2.add_cookies(login_cookies)
            
            # Verify cookies were added correctly
            after_add_cookies = await context2.cookies()
            results["cookies"]["after_add"] = format_cookies_for_output(after_add_cookies)
            results["cookies"]["diff"] = compare_cookies(login_cookies, after_add_cookies)

            # Build payload
            payload = build_pnd_payload(-1003, "14.02.2026 00:00", "14.02.2026 00:00", ELECTROMETER_ID)

            # Test form data variant
            form_results = await test_form_data_variant(context2, after_add_cookies, payload)
            results["variants"]["form_data_variant"] = {
                "request": {
                    "url": PND_DATA_URL,
                    "method": "POST",
                    "headers": {},
                    "body_raw": str(payload),
                    "body_type": "form_dict"
                },
                **form_results
            }

            # Test JSON string variant
            json_results = await test_json_string_variant(context2, after_add_cookies, payload)
            results["variants"]["json_string_variant"] = {
                "request": {
                    "url": PND_DATA_URL,
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body_raw": json.dumps(payload),
                    "body_type": "json_string"
                },
                **json_results
            }

            # Determine overall verdict
            form_pass = form_results["verdict"] == "PASS"
            json_pass = json_results["verdict"] == "PASS"
            
            if form_pass or json_pass:
                results["verdict"] = "PASS"
                results["verdict_reason"] = f"At least one variant succeeded (form: {form_pass}, json: {json_pass})"
            else:
                results["verdict"] = "FAIL"
                results["verdict_reason"] = f"Both variants failed (form: {form_pass}, json: {json_pass})"

            # Cleanup
            await context2.close()
            await browser2.close()

        except Exception as e:
            results["verdict"] = "FAIL"
            results["verdict_reason"] = f"Test failed with exception: {str(e)}"
            results["error"] = str(e)

    return results


if __name__ == "__main__":
    result = asyncio.run(main())
    
    # Save results to JSON file
    os.makedirs("evidence/poc-results", exist_ok=True)
    with open("evidence/poc-results/test_2_new_context.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"Test completed. Results saved to evidence/poc-results/test_2_new_context.json")
    print(f"Overall verdict: {result['verdict']}")
    print(f"Reason: {result['verdict_reason']}")