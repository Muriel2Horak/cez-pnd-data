#!/usr/bin/env python3
"""
Test 1: aiohttp with Cookies — Detailed Redirect Debugging

This script tests aiohttp POST requests with cookies extracted from Playwright login.
It logs all response details including redirect chain to understand why we get 302.
"""

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List
import aiohttp
from playwright.async_api import async_playwright  # type: ignore[import-not-found]


# Constants
PND_API_URL = "https://pnd.cezdistribuce.cz/cezpnd2/external/data"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def playwright_cookies_to_header(cookies: list[dict[str, Any]]) -> str:
    """Convert Playwright cookies to Cookie header string. Output: 'X=Y; A=B'"""
    if not cookies:
        return ""
    
    cookie_pairs = []
    for cookie in cookies:
        name = cookie.get("name", "")
        value = cookie.get("value", "")
        if name:
            cookie_pairs.append(f"{name}={value}")
    
    return "; ".join(cookie_pairs)


def filter_cookies_by_domain(cookies: list[dict[str, Any]], domain: str) -> list[dict[str, Any]]:
    """Filter cookies by domain."""
    filtered = []
    for cookie in cookies:
        if domain in cookie.get("domain", ""):
            filtered.append(cookie)
    return filtered


async def login_with_playwright(email: str, password: str) -> tuple[bool, str, list[dict[str, Any]]]:
    """Login to CEZ PND using Playwright and return session cookies."""
    async with async_playwright() as playwright:
        # Launch browser and login
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
        import re
        success_pattern = re.compile(r".*/(cezpnd2/dashboard/|cezpnd2/external/dashboard/view|irj/portal).*")
        await page.wait_for_url(success_pattern, timeout=120_000)
        
        # Get final URL and cookies
        final_url = page.url
        cookies = await context.cookies()
        
        await browser.close()
        return True, final_url, cookies


async def make_aiohttp_request(cookies: list[dict[str, Any]], electrometer_id: str) -> Dict[str, Any]:
    """Make aiohttp POST request and log all details."""
    # Create payload (same as PndClient)
    payload = {
        "format": "table",
        "idAssembly": 1,  # Default assembly ID
        "idDeviceSet": None,
        "intervalFrom": "14.02.2026",  # Fixed date for testing
        "intervalTo": "14.02.2026",
        "compareFrom": None,
        "opmId": None,
        "electrometerId": electrometer_id,
    }
    
    # Convert cookies to header
    cookie_header = playwright_cookies_to_header(cookies)
    
    # Create headers
    headers = {
        "Cookie": cookie_header,
        "User-Agent": DEFAULT_USER_AGENT,
        "Content-Type": "application/json"
    }
    
    # Create session with allow_redirects=False
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                PND_API_URL, 
                json=payload, 
                headers=headers, 
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=False
            ) as resp:
                # Read response body
                body = await resp.text()
                
                # Get all headers
                response_headers = dict(resp.headers)
                
                # Handle redirect chain
                redirect_chain = []
                if resp.status in (301, 302, 303, 307, 308):
                    location = response_headers.get("Location", "")
                    if location:
                        redirect_chain.append(location)
                        
                        # Follow the redirect manually to see where it goes
                        try:
                            async with session.get(
                                location,
                                headers={"User-Agent": DEFAULT_USER_AGENT},
                                timeout=aiohttp.ClientTimeout(total=30),
                                allow_redirects=False
                            ) as redirect_resp:
                                if redirect_resp.status in (301, 302, 303, 307, 308):
                                    redirect_location = dict(redirect_resp.headers).get("Location", "")
                                    if redirect_location:
                                        redirect_chain.append(redirect_location)
                        except Exception:
                            pass  # Ignore errors when following redirects
                
                return {
                    "status": resp.status,
                    "headers": response_headers,
                    "body_preview": body[:2000] if body else "",
                    "body_length": len(body) if body else 0,
                    "is_json": False,
                    "is_html": "<html" in body.lower() if body else False,
                    "redirect_chain": redirect_chain
                }
        except Exception as e:
            return {
                "status": 0,
                "headers": {},
                "body_preview": str(e),
                "body_length": len(str(e)),
                "is_json": False,
                "is_html": False,
                "redirect_chain": [],
                "error": str(e)
            }


async def main():
    """Main test function."""
    # Get credentials from environment
    email = os.getenv("CEZ_EMAIL", "horak.martin@seznam.cz")
    password = os.getenv("CEZ_PASSWORD", "horak123")
    electrometer_id = os.getenv("CEZ_ELECTROMETER_ID", "784703")
    
    print("Starting Test 1: aiohttp with Cookies — Detailed Redirect Debugging")
    
    # Step 1: Login with Playwright
    print("Step 1: Playwright login...")
    login_success, final_url, cookies = await login_with_playwright(email, password)
    
    if not login_success:
        print("❌ Login failed")
        return
    
    print(f"✓ Login successful, final URL: {final_url}")
    print(f"✓ Found {len(cookies)} cookies")
    
    # Filter cookies by domain
    pnd_cookies = filter_cookies_by_domain(cookies, "pnd.cezdistribuce.cz")
    dip_cookies = filter_cookies_by_domain(cookies, "dip.cezdistribuce.cz")
    
    print(f"✓ PND domain cookies: {len(pnd_cookies)}")
    print(f"✓ DIP domain cookies: {len(dip_cookies)}")
    
    # Check for CSRF token
    csrf_cookies = [c for c in cookies if c.get("name") == "pac4jCsrfToken"]
    print(f"✓ CSRF token cookies: {len(csrf_cookies)}")
    
    # Step 2: Make aiohttp request
    print("Step 2: Making aiohttp POST request...")
    response_data = await make_aiohttp_request(cookies, electrometer_id)
    
    # Step 3: Prepare result
    result = {
        "test_name": "test_1_aiohttp",
        "timestamp": datetime.now().isoformat(),
        "login": {
            "success": login_success,
            "final_url": final_url
        },
        "request": {
            "url": PND_API_URL,
            "method": "POST",
            "headers": {
                "Cookie": playwright_cookies_to_header(cookies),
                "User-Agent": DEFAULT_USER_AGENT,
                "Content-Type": "application/json"
            },
            "body_raw": json.dumps({
                "format": "table",
                "idAssembly": 1,
                "idDeviceSet": None,
                "intervalFrom": "14.02.2026",
                "intervalTo": "14.02.2026",
                "compareFrom": None,
                "opmId": None,
                "electrometerId": electrometer_id
            }, separators=(',', ':')),
            "body_type": "json_object"
        },
        "response": response_data,
        "cookies": {
            "all_cookies": cookies,
            "pnd_domain_cookies": pnd_cookies,
            "dip_domain_cookies": dip_cookies
        },
        "verdict": "PASS" if response_data.get("status") == 200 else "FAIL",
        "verdict_reason": (
            "Request successful" if response_data.get("status") == 200 
            else f"Got status {response_data.get('status')} instead of 200"
        ),
        "error": response_data.get("error") if response_data.get("error") else None
    }
    
    # Step 4: Save result
    output_path = "/Users/martinhorak/Projects/cez-pnd/evidence/poc-results/test_1_aiohttp.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Results saved to {output_path}")
    print(f"📊 Verdict: {result['verdict']}")
    print(f"📝 Reason: {result['verdict_reason']}")
    
    if response_data.get("redirect_chain"):
        print("🔄 Redirect chain:")
        for i, url in enumerate(response_data["redirect_chain"], 1):
            print(f"   {i}. {url}")


if __name__ == "__main__":
    asyncio.run(main())