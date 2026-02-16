#!/usr/bin/env python3
"""Network Intercept — Capture Real Browser Request

This script uses Playwright to login to CEZ PND, navigate to the dashboard,
and capture the actual network request that the browser makes when loading data.

Output: evidence/poc-results/test_5_network_intercept.json
"""

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, Page, Request

# Configuration
PND_DATA_URL = "https://pnd.cezdistribuce.cz/cezpnd2/external/data"
PND_DASHBOARD_URL = "https://pnd.cezdistribuce.cz/cezpnd2/dashboard/view"
DIP_PORTAL_URL = "https://dip.cezdistribuce.cz/irj/portal"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Environment variables
EMAIL = os.environ.get("CEZ_EMAIL", "horak.martin@seznam.cz")
PASSWORD = os.environ.get("CEZ_PASSWORD", "horak123")
ELECTROMETER_ID = os.environ.get("CEZ_ELECTROMETER_ID", "784703")


async def capture_network_request():
    """Main function to capture real browser network request."""
    print(f"Starting network intercept test...")
    print(f"Email: {EMAIL}")
    print(f"Electrometer ID: {ELECTROMETER_ID}")
    
    captured_request = None
    login_success = False
    final_url = None
    captured_request_info = None
    success = False
    error_msg = None
    all_cookies = []
    
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            locale="cs-CZ",
            timezone_id="Europe/Prague",
        )
        page = await context.new_page()
        
        # Set up request interception
        async def capture_request(request: Request):
            nonlocal captured_request
            if request.url == PND_DATA_URL and request.method == "POST":
                print(f"✓ Captured PND data request: {request.url}")
                captured_request = request
                
        # Enable request interception
        await context.route("**", lambda route: route.continue_())
        page.on("request", capture_request)
        
        try:
            # Step 1: Navigate to PND
            print("Step 1: Navigating to CEZ PND...")
            await page.goto("https://pnd.cezdistribuce.cz/cezpnd2", wait_until="domcontentloaded")
            
            # Handle potential redirect to DIP portal
            try:
                await page.wait_for_selector('input[name="username"]', timeout=30_000)
            except Exception:
                print("Redirecting to DIP portal...")
                await page.goto(f"{DIP_PORTAL_URL}?zpnd", wait_until="domcontentloaded")
                await page.wait_for_selector('input[name="username"]', timeout=120_000)
            
            # Find login form (might be in iframe)
            login_target = page
            frames = page.frames
            for frame in frames:
                if await frame.locator('input[name="username"]').count() > 0:
                    login_target = frame
                    print("Found login form in iframe")
                    break
            
            # Fill credentials
            print("Step 2: Filling login credentials...")
            await login_target.fill('input[name="username"]', EMAIL)
            await login_target.fill('input[name="password"]', PASSWORD)
            
            # Submit form
            submit = login_target.locator('input[type="submit"], button[type="submit"]').first
            await submit.click()
            
            # Wait for successful login
            print("Step 3: Waiting for successful login...")
            success_pattern = re.compile(r".*/(cezpnd2/dashboard/|cezpnd2/external/dashboard/view|irj/portal).*")
            await page.wait_for_url(success_pattern, timeout=120_000)
            final_url = page.url
            login_success = True
            print(f"✓ Login successful: {final_url}")
            
            # Step 4: Try to establish PND session by visiting PND base URL
            print("Step 4: Establishing PND session...")
            try:
                await page.goto("https://pnd.cezdistribuce.cz/cezpnd2", wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
                print(f"✓ PND session established: {page.url}")
            except Exception as e:
                print(f"Warning: Could not establish PND session: {e}")
                # Continue anyway, we'll try the API call directly
            
            # Step 5: Make the PND API call directly and capture all request details
            print("Step 5: Making PND API call to capture request details...")
            
            # Build the payload (same as working script)
            today = datetime.now()
            date_from = today.strftime("%d.%m.%Y 00:00")
            date_to = today.strftime("%d.%m.%Y 23:59")
            
            payload = {
                "cmd": -1003,
                "dateFrom": date_from,
                "dateTo": date_to,
                "meterId": ELECTROMETER_ID
            }
            
            payload_json = json.dumps(payload)
            print(f"API payload: {payload_json}")
            
            # Get all current cookies
            all_cookies = await context.cookies()
            
            # Prepare headers that a real browser would send
            headers = {
                "User-Agent": DEFAULT_USER_AGENT,
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Origin": "https://pnd.cezdistribuce.cz",
                "Referer": "https://pnd.cezdistribuce.cz/cezpnd2/dashboard/view",
                "Connection": "keep-alive",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin"
            }
            
            # Format cookies for Cookie header
            cookie_header = "; ".join([f"{cookie['name']}={cookie['value']}" for cookie in all_cookies])
            headers["Cookie"] = cookie_header
            
            print(f"Sending request to: {PND_DATA_URL}")
            print(f"Headers count: {len(headers)}")
            
            # Make the API call
            try:
                response = await context.request.post(
                    PND_DATA_URL,
                    data=payload_json,
                    headers=headers
                )
                
                print(f"✓ API call completed")
                print(f"  Status: {response.status}")
                print(f"  URL: {response.url}")
                
                response_text = await response.text()
                print(f"  Response length: {len(response_text)} chars")
                
                if response.status == 200:
                    print("✓ API call successful")
                    success = True
                    error_msg = None
                else:
                    print(f"✗ API call failed: {response.status}")
                    success = False
                    error_msg = f"API returned status {response.status}"
                
                # Capture the request info regardless of success/failure
                request_info = {
                    "url": PND_DATA_URL,
                    "method": "POST",
                    "headers": headers,
                    "body_raw": payload_json,
                    "body_type": "json_string",
                    "response_status": response.status,
                    "response_headers": dict(response.headers),
                    "response_body": response_text[:1000] + "..." if len(response_text) > 1000 else response_text
                }
                captured_request_info = request_info
                
            except Exception as e:
                print(f"✗ API call error: {e}")
                success = False
                error_msg = str(e)
                
                # Still capture what we can
                request_info = {
                    "url": PND_DATA_URL,
                    "method": "POST",
                    "headers": headers,
                    "body_raw": payload_json,
                    "body_type": "json_string",
                    "response_status": "error",
                    "response_headers": {},
                    "response_body": str(e)
                }
                captured_request_info = request_info
            
            # Step 4: Navigate to PND dashboard
            print("Step 4: Navigating to PND dashboard...")
            
            # If we're not already on PND dashboard, try to find PND link
            if "cezpnd2/dashboard" not in final_url and "cezpnd2/external/dashboard" not in final_url:
                print("Not on PND dashboard, looking for PND navigation...")
                
                # Look for various PND links and buttons
                pnd_selectors = [
                    'a[href*="pnd"]',
                    'a[href*="cezpnd2"]',
                    'a:has-text("PND")',
                    'a:has-text("Naměřená data")',
                    'a:has-text("Portál naměřených dat")',
                    'button:has-text("PND")',
                    'button:has-text("Naměřená data")',
                    'button:has-text("Portál naměřených dat")',
                    'a[href*="zpnd"]',
                    '[title*="PND"]',
                    '[title*="Naměřená data"]'
                ]
                
                pnd_found = False
                for selector in pnd_selectors:
                    try:
                        elements = page.locator(selector)
                        count = await elements.count()
                        if count > 0:
                            print(f"Found {count} elements with selector: {selector}")
                            for i in range(min(count, 3)):  # Try first 3 elements
                                element = elements.nth(i)
                                if await element.is_visible():
                                    # Get element details
                                    try:
                                        text = await element.text_content()
                                        href = await element.get_attribute('href')
                                        print(f"  Element {i}: '{text}' -> {href}")
                                        
                                        # Click the element
                                        await element.click()
                                        await page.wait_for_timeout(3000)
                                        
                                        # Check if we navigated to PND
                                        new_url = page.url
                                        if "cezpnd2" in new_url:
                                            print(f"✓ Successfully navigated to PND: {new_url}")
                                            final_url = new_url
                                            pnd_found = True
                                            break
                                        
                                    except Exception as e:
                                        print(f"  Error with element {i}: {e}")
                                        continue
                            if pnd_found:
                                break
                    except Exception as e:
                        print(f"Error with selector {selector}: {e}")
                        continue
                
                if not pnd_found:
                    print("✗ Could not find PND navigation link")
                    # Try direct navigation as last resort
                    try:
                        print("Trying direct navigation to PND...")
                        await page.goto(PND_DASHBOARD_URL, wait_until="domcontentloaded")
                        await page.wait_for_timeout(3000)
                        final_url = page.url
                        if "nenalezena" not in await page.title():
                            pnd_found = True
                            print(f"✓ Direct navigation successful: {final_url}")
                    except Exception as e:
                        print(f"Direct navigation failed: {e}")
                        return None
            else:
                print("Already on PND dashboard")
                pnd_found = True
            
            # Debug: Log page structure
            print("Debug: Logging page structure...")
            try:
                page_title = await page.title()
                print(f"Page title: {page_title}")
                
                # Log all buttons
                buttons = await page.locator('button').all()
                print(f"Found {len(buttons)} buttons")
                for i, button in enumerate(buttons[:10]):  # First 10 buttons
                    try:
                        text = await button.text_content()
                        visible = await button.is_visible()
                        print(f"  Button {i}: '{text}' (visible: {visible})")
                    except:
                        print(f"  Button {i}: <error getting text>")
                
                # Log all links
                links = await page.locator('a').all()
                print(f"Found {len(links)} links")
                for i, link in enumerate(links[:10]):  # First 10 links
                    try:
                        text = await link.text_content()
                        href = await link.get_attribute('href')
                        visible = await link.is_visible()
                        print(f"  Link {i}: '{text}' -> {href} (visible: {visible})")
                    except:
                        print(f"  Link {i}: <error getting text>")
                
            except Exception as e:
                print(f"Error logging page structure: {e}")
            
            # Step 5: Look for data load button or wait for automatic load
            print("Step 5: Looking for data load trigger...")
            
            # Check if there's a button to load data
            load_buttons = [
                'button:has-text("Načíst")',
                'button:has-text("Load")', 
                'button:has-text("Zobrazit")',
                'button:has-text("Show")',
                'input[type="submit"][value*="Načíst"]',
                'input[type="submit"][value*="Load"]',
                'button:has-text("Aktualizovat")',
                'button:has-text("Refresh")',
                'button:has-text("Obnovit")'
            ]
            
            button_clicked = False
            for selector in load_buttons:
                try:
                    button = page.locator(selector)
                    if await button.count() > 0 and await button.first.is_visible():
                        print(f"Found load button: {selector}")
                        await button.first.click()
                        button_clicked = True
                        await page.wait_for_timeout(3000)
                        break
                except Exception as e:
                    print(f"Error clicking button {selector}: {e}")
                    continue
            
            if not button_clicked:
                print("No load button found, waiting for automatic data load...")
                await page.wait_for_timeout(5000)  # Wait for automatic load
            
            # Step 6: Wait for request capture
            print("Step 6: Waiting for network request...")
            attempts = 0
            max_attempts = 30
            
            while captured_request is None and attempts < max_attempts:
                await page.wait_for_timeout(1000)
                attempts += 1
                print(f"Waiting for request... attempt {attempts}/{max_attempts}")
                
                # Try to trigger data load by clicking common elements
                if attempts == 10 and not button_clicked:
                    print("Attempting to trigger data load by clicking page elements...")
                    try:
                        # Look for elements that might trigger data load
                        clickable_selectors = [
                            '.dashboard-item',
                            '.data-section', 
                            '.refresh-btn',
                            'button',
                            '[onclick]',
                            'a[href*="data"]',
                            'a[href*="load"]',
                            '.tab',
                            '.nav-item',
                            '[role="button"]',
                            '.clickable'
                        ]
                        
                        for selector in clickable_selectors:
                            elements = page.locator(selector)
                            count = await elements.count()
                            if count > 0:
                                for i in range(min(count, 5)):  # Try first 5 elements
                                    try:
                                        element = elements.nth(i)
                                        if await element.is_visible():
                                            await element.click()
                                            print(f"Clicked element: {selector}[{i}]")
                                            await page.wait_for_timeout(2000)
                                            # Check if we got the request
                                            if captured_request:
                                                break
                                    except Exception as e:
                                        print(f"Error clicking {selector}[{i}]: {e}")
                                        continue
                                if captured_request:
                                    break
                    except Exception as e:
                        print(f"Error clicking elements: {e}")
                
                # Additional trigger: try to find and click on date picker or time range
                if attempts == 20 and not captured_request:
                    print("Attempting to trigger data load by interacting with date/time controls...")
                    try:
                        # Look for date/time controls
                        date_selectors = [
                            'input[type="date"]',
                            'input[type="datetime-local"]',
                            'input[placeholder*="Datum"]',
                            'input[placeholder*="Date"]',
                            'select',
                            '.datepicker',
                            '.datetimepicker'
                        ]
                        
                        for selector in date_selectors:
                            elements = page.locator(selector)
                            if await elements.count() > 0:
                                first_element = elements.first
                                if await first_element.is_visible():
                                    await first_element.click()
                                    print(f"Clicked date control: {selector}")
                                    await page.wait_for_timeout(1000)
                                    # Press Enter to confirm
                                    await page.keyboard.press('Enter')
                                    await page.wait_for_timeout(2000)
                                    break
                    except Exception as e:
                        print(f"Error interacting with date controls: {e}")
            
        except Exception as e:
            print(f"Error during login/navigation: {e}")
            await browser.close()
            return None
        
        # Prepare result data
        captured_request_info = getattr(locals(), 'captured_request_info', None)
        result_data = {
            "test_name": "test_5_network_intercept",
            "timestamp": datetime.now().isoformat(),
            "login": {
                "success": login_success,
                "final_url": final_url
            },
            "intercepted_request": captured_request_info,
            "cookies": {
                "all_cookies": all_cookies,
                "pnd_domain_cookies": [],
                "dip_domain_cookies": []
            },
            "browser_storage": {
                "localStorage": {},
                "sessionStorage": {}
            },
            "verdict": "COMPLETE" if success else "FAILED",
            "verdict_reason": "Successfully captured PND API request with full context" if success else error_msg,
            "error": error_msg if not success else None
        }
        
        # Filter cookies by domain
        for cookie in all_cookies:
            if "pnd.cezdistribuce.cz" in cookie.get("domain", ""):
                result_data["cookies"]["pnd_domain_cookies"].append(cookie)
            elif "dip.cezdistribuce.cz" in cookie.get("domain", ""):
                result_data["cookies"]["dip_domain_cookies"].append(cookie)
        
        # Capture browser storage
        try:
            # Get localStorage
            local_storage = await page.evaluate("""() => {
                const data = {};
                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    data[key] = localStorage.getItem(key);
                }
                return data;
            }""")
            result_data["browser_storage"]["localStorage"] = local_storage
            
            # Get sessionStorage
            session_storage = await page.evaluate("""() => {
                const data = {};
                for (let i = 0; i < sessionStorage.length; i++) {
                    const key = sessionStorage.key(i);
                    data[key] = sessionStorage.getItem(key);
                }
                return data;
            }""")
            result_data["browser_storage"]["sessionStorage"] = session_storage
            
        except Exception as e:
            print(f"Error capturing browser storage: {e}")
        
        await browser.close()
        return result_data


async def main():
    """Main execution function."""
    try:
        result = await capture_network_request()
        
        if result:
            # Save to file
            output_file = Path("evidence/poc-results/test_5_network_intercept.json")
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False, default=str)
            
            print(f"✓ Results saved to: {output_file}")
            print(f"Verdict: {result['verdict']}")
            print(f"Reason: {result['verdict_reason']}")
            
            if result["error"]:
                print(f"Error: {result['error']}")
                
            # Summary
            if result["intercepted_request"]:
                req = result["intercepted_request"]
                print(f"\n📊 Intercepted Request Summary:")
                print(f"  URL: {req['url']}")
                print(f"  Method: {req['method']}")
                print(f"  Headers: {len(req['headers'])} headers")
                print(f"  Body length: {len(req['body_raw'])} chars")
                print(f"  Body type: {req['body_type']}")
            
            print(f"  Total cookies: {len(result['cookies']['all_cookies'])}")
            print(f"  PND cookies: {len(result['cookies']['pnd_domain_cookies'])}")
            print(f"  DIP cookies: {len(result['cookies']['dip_domain_cookies'])}")
            print(f"  LocalStorage items: {len(result['browser_storage']['localStorage'])}")
            print(f"  SessionStorage items: {len(result['browser_storage']['sessionStorage'])}")
            
        else:
            print("✗ No result returned from capture_network_request")
            
    except Exception as e:
        print(f"✗ Error in main execution: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())