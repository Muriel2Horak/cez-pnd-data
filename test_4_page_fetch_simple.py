#!/usr/bin/env python3
"""
Test 4: Playwright Browser Automation - page.evaluate(fetch)
Test fetch() from browser context with and without explicit Content-Type header.
"""

import asyncio
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional

async def test_page_fetch():
    """Execute fetch() from browser context test."""
    # Get credentials from environment
    email = os.getenv("CEZ_EMAIL", "horak.martin@seznam.cz")
    password = os.getenv("CEZ_PASSWORD", "horak123")
    electrometer_id = os.getenv("CEZ_ELECTROMETER_ID", "784703")
    
    print(f"Testing with email: {email}")
    print(f"Electrometer ID: {electrometer_id}")
    
    result = {
        "test_name": "test_4_page_fetch",
        "timestamp": datetime.now().isoformat(),
        "login": {
            "success": False,
            "final_url": None
        },
        "dashboard_navigation": {
            "url": "https://pnd.cezdistribuce.cz/cezpnd2/dashboard/view",
            "wait_seconds": 3
        },
        "fetch_check": {
            "is_native": None,
            "is_monkey_patched": None
        },
        "variants": {
            "explicit_content_type": None,
            "no_explicit_content_type": None
        },
        "verdict": "FAIL",
        "verdict_reason": "Test not executed",
        "error": None
    }
    
    try:
        # Import Playwright here to avoid import errors if not installed
        from playwright.async_api import async_playwright
        
        async with async_playwright() as playwright:
            print("Launching browser...")
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                locale="cs-CZ",
                timezone_id="Europe/Prague",
            )
            page = await context.new_page()
            
            # Step 1: Login
            print("Navigating to PND login page...")
            await page.goto("https://pnd.cezdistribuce.cz/cezpnd2", wait_until="domcontentloaded")
            
            try:
                await page.wait_for_selector('input[name="username"]', timeout=30_000)
                print("Found login form on PND")
            except Exception:
                print("PND login failed, trying DIP...")
                await page.goto("https://dip.cezdistribuce.cz/irj/portal?zpnd", wait_until="domcontentloaded")
                await page.wait_for_selector('input[name="username"]', timeout=120_000)
                print("Found login form on DIP")
            
            # Find login form (might be in iframe)
            login_target = page
            for frame in page.frames:
                if await frame.locator('input[name="username"]').count() > 0:
                    login_target = frame
                    print("Found login form in iframe")
                    break
            
            # Fill credentials
            print("Filling credentials...")
            await login_target.fill('input[name="username"]', email)
            await login_target.fill('input[name="password"]', password)
            
            # Submit
            print("Submitting login form...")
            submit = login_target.locator('input[type="submit"], button[type="submit"]').first
            await submit.click()
            
            # Wait for success
            print("Waiting for successful login...")
            await page.wait_for_url(r".*/(cezpnd2/dashboard/|cezpnd2/external/dashboard/view|irj/portal).*", timeout=120_000)
            
            result["login"]["success"] = True
            result["login"]["final_url"] = page.url
            print(f"Login successful! Final URL: {page.url}")
            
            # Navigate to PND dashboard
            print("Navigating to dashboard...")
            await page.goto("https://pnd.cezdistribuce.cz/cezpnd2/dashboard/view", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)  # Wait 3 seconds
            print("Dashboard loaded")
            
            # Check if fetch is monkey-patched
            print("Checking if fetch is monkey-patched...")
            fetch_to_string = await page.evaluate("fetch.toString()")
            result["fetch_check"]["is_native"] = "native code" in fetch_to_string.lower()
            result["fetch_check"]["is_monkey_patched"] = "native code" not in fetch_to_string.lower()
            print(f"Fetch is native: {result['fetch_check']['is_native']}")
            print(f"Fetch is monkey-patched: {result['fetch_check']['is_monkey_patched']}")
            
            # Build payload
            today = datetime.now()
            date_from = today.strftime("%d.%m.%Y 00:00")
            date_to = today.strftime("%d.%m.%Y 23:59")
            payload = {
                "d": -1003,
                "s": date_from,
                "e": date_to,
                "eid": electrometer_id,
                "lang": "cs",
                "version": "1.0",
                "isSum": False,
                "chartMode": False
            }
            
            # Test both variants
            print("\n=== Testing fetch variants ===")
            
            # Variant 1: Explicit Content-Type
            print("Testing fetch WITH explicit Content-Type...")
            explicit_result = await test_fetch_variant(page, payload, explicit_content_type=True)
            result["variants"]["explicit_content_type"] = explicit_result
            print(f"Result: {explicit_result['verdict']} - {explicit_result['verdict_reason']}")
            
            # Variant 2: No explicit Content-Type
            print("Testing fetch WITHOUT explicit Content-Type...")
            no_explicit_result = await test_fetch_variant(page, payload, explicit_content_type=False)
            result["variants"]["no_explicit_content_type"] = no_explicit_result
            print(f"Result: {no_explicit_result['verdict']} - {no_explicit_result['verdict_reason']}")
            
            # Overall verdict
            if explicit_result["verdict"] == "PASS" or no_explicit_result["verdict"] == "PASS":
                result["verdict"] = "PASS"
                result["verdict_reason"] = "At least one fetch variant succeeded"
            else:
                result["verdict"] = "FAIL"
                result["verdict_reason"] = "Both fetch variants failed"
            
            await browser.close()
            
    except Exception as e:
        result["error"] = str(e)
        result["verdict_reason"] = f"Test failed with exception: {str(e)}"
        print(f"ERROR: {e}")
    
    # Save results
    os.makedirs("evidence/poc-results", exist_ok=True)
    with open("evidence/poc-results/test_4_page_fetch.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"\nResults saved to evidence/poc-results/test_4_page_fetch.json")
    print(f"Overall verdict: {result['verdict']}")
    print(f"Verdict reason: {result['verdict_reason']}")
    
    return result["verdict"] == "PASS"

async def test_fetch_variant(page, payload: Dict[str, Any], explicit_content_type: bool) -> Dict[str, Any]:
    """Test a specific fetch variant."""
    result = {
        "request": {
            "url": "https://pnd.cezdistribuce.cz/cezpnd2/external/data",
            "method": "POST",
            "headers": {},
            "body_raw": json.dumps(payload),
            "body_type": "json_string"
        },
        "response": {
            "status": None,
            "headers": {},
            "body_preview": None,
            "is_json": False,
            "is_html": False
        },
        "verdict": "FAIL",
        "verdict_reason": "Test not executed"
    }
    
    try:
        # Build fetch options
        fetch_options = {
            "method": "POST",
            "body": json.dumps(payload)
        }
        
        if explicit_content_type:
            fetch_options["headers"] = {"Content-Type": "application/json"}
            result["request"]["headers"] = {"Content-Type": "application/json"}
        
        # Execute fetch in browser context
        js_code = f"""
        const response = await fetch('https://pnd.cezdistribuce.cz/cezpnd2/external/data', {json.dumps(fetch_options).replace('"', '\\"')});
        return {{
            status: response.status,
            headers: Object.fromEntries(response.headers.entries()),
            body: await response.text()
        }};
        """
        
        fetch_result = await page.evaluate(js_code)
        
        # Process response
        result["response"]["status"] = fetch_result["status"]
        result["response"]["headers"] = fetch_result["headers"]
        
        body_text = fetch_result["body"]
        result["response"]["body_preview"] = body_text[:500] if body_text else None
        
        # Check response type
        try:
            json.loads(body_text)
            result["response"]["is_json"] = True
        except:
            result["response"]["is_json"] = False
        
        result["response"]["is_html"] = body_text and body_text.strip().startswith("<")
        
        # Determine verdict
        if fetch_result["status"] == 200:
            result["verdict"] = "PASS"
            result["verdict_reason"] = "Fetch succeeded with 200 status"
        else:
            result["verdict"] = "FAIL"
            result["verdict_reason"] = f"Fetch failed with status {fetch_result['status']}"
            
    except Exception as e:
        result["verdict"] = "FAIL"
        result["verdict_reason"] = f"Fetch execution failed: {str(e)}"
    
    return result

if __name__ == "__main__":
    success = asyncio.run(test_page_fetch())
    exit(0 if success else 1)