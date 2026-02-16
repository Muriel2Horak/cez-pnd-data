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

from playwright.async_api import async_playwright

# Configuration
PND_DATA_URL = "https://pnd.cezdistribuce.cz/cezpnd2/external/data"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

def build_pnd_payload(device_id: int, date_from: str, date_to: str, electrometer_id: str) -> Dict[str, Any]:
    """Build PND data request payload."""
    return {
        "d": device_id,
        "s": date_from,
        "e": date_to,
        "eid": electrometer_id,
        "lang": "cs",
        "version": "1.0",
        "isSum": False,
        "chartMode": False
    }

async def test_page_fetch():
    """Execute fetch() from browser context test."""
    # Get credentials from environment
    email = os.getenv("CEZ_EMAIL", "horak.martin@seznam.cz")
    password = os.getenv("CEZ_PASSWORD", "horak123")
    electrometer_id = os.getenv("CEZ_ELECTROMETER_ID", "784703")
    
    if not all([email, password, electrometer_id]):
        print("Missing required environment variables: CEZ_EMAIL, CEZ_PASSWORD, CEZ_ELECTROMETER_ID")
        return False
    
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
        async with async_playwright() as playwright:
            # Step 1: Launch browser and login
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                locale="cs-CZ",
                timezone_id="Europe/Prague",
            )
            page = await context.new_page()
            
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
            await login_target.fill('input[name="username"]', email)
            await login_target.fill('input[name="password"]', password)
            
            # Submit
            submit = login_target.locator('input[type="submit"], button[type="submit"]').first
            await submit.click()
            
            # Wait for success
            await page.wait_for_url(r".*/(cezpnd2/dashboard/|cezpnd2/external/dashboard/view|irj/portal).*", timeout=120_000)
            
            result["login"]["success"] = True
            result["login"]["final_url"] = page.url
            
            # Navigate to PND dashboard to establish session
            await page.goto("https://pnd.cezdistribuce.cz/cezpnd2/dashboard/view", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)  # Wait 3 seconds for session initialization
            
            # Check if fetch is monkey-patched
            fetch_to_string = await page.evaluate("fetch.toString()")
            result["fetch_check"]["is_native"] = "native code" in fetch_to_string.lower()
            result["fetch_check"]["is_monkey_patched"] = "native code" not in fetch_to_string.lower()
            
            # Build payload for fetch
            today = datetime.now()
            date_from = today.strftime("%d.%m.%Y 00:00")
            date_to = today.strftime("%d.%m.%Y 23:59")
            payload = build_pnd_payload(-1003, date_from, date_to, electrometer_id)
            
            # Execute variant 1: fetch with explicit Content-Type
            print("Testing fetch with explicit Content-Type...")
            explicit_result = await test_fetch_variant(
                page, 
                payload, 
                explicit_content_type=True
            )
            result["variants"]["explicit_content_type"] = explicit_result
            
            # Execute variant 2: fetch without explicit Content-Type
            print("Testing fetch without explicit Content-Type...")
            no_explicit_result = await test_fetch_variant(
                page, 
                payload, 
                explicit_content_type=False
            )
            result["variants"]["no_explicit_content_type"] = no_explicit_result
            
            # Determine overall verdict
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
    
    # Save results
    os.makedirs("evidence/poc-results", exist_ok=True)
    with open("evidence/poc-results/test_4_page_fetch.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"Results saved to evidence/poc-results/test_4_page_fetch.json")
    print(f"Overall verdict: {result['verdict']}")
    print(f"Verdict reason: {result['verdict_reason']}")
    
    return result["verdict"] == "PASS"

async def test_fetch_variant(page, payload: Dict[str, Any], explicit_content_type: bool) -> Dict[str, Any]:
    """Test a specific fetch variant and return results."""
    result = {
        "request": {
            "url": PND_DATA_URL,
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
        const response = await fetch('{PND_DATA_URL}', {json.dumps(fetch_options)});
        const status = response.status;
        const headers = {{}};
        response.headers.forEach((value, name) => {{
            headers[name] = value;
        }});
        const bodyText = await response.text();
        return {{
            status: status,
            headers: headers,
            body: bodyText
        }};
        """
        
        fetch_result = await page.evaluate(js_code)
        
        # Process response
        result["response"]["status"] = fetch_result["status"]
        result["response"]["headers"] = fetch_result["headers"]
        
        body_text = fetch_result["body"]
        result["response"]["body_preview"] = body_text[:500] if body_text else None
        
        # Check if response is JSON
        try:
            json.loads(body_text)
            result["response"]["is_json"] = True
        except:
            result["response"]["is_json"] = False
        
        # Check if response is HTML
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