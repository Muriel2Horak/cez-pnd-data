#!/usr/bin/env python3
"""Test 3: Reuse Login Context — Direct API Call

Login via Playwright, navigate to dashboard, wait, use SAME context for context.request.post.
Test both JSON string and form data variants.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

# Import constants from live_verify_flow
PND_DATA_URL = "https://pnd.cezdistribuce.cz/cezpnd2/external/data"


def build_pnd_payload(assembly_id: int, date_from: str, date_to: str, electrometer_id: str) -> dict:
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


async def main():
    """Main test function."""
    # Read credentials from environment
    email = os.getenv("CEZ_EMAIL")
    password = os.getenv("CEZ_PASSWORD")
    electrometer_id = os.getenv("CEZ_ELECTROMETER_ID")
    
    if not all([email, password, electrometer_id]):
        print("ERROR: Missing required environment variables")
        print("Required: CEZ_EMAIL, CEZ_PASSWORD, CEZ_ELECTROMETER_ID")
        return 1
    
    print(f"Starting test_3_reuse_context...")
    print(f"Electrometer ID: {electrometer_id}")
    print()
    
    test_result = {
        "test_name": "test_3_reuse_context",
        "timestamp": datetime.now().isoformat(),
        "login": {
            "success": False,
            "final_url": None
        },
        "dashboard_navigation": {
            "url": "https://pnd.cezdistribuce.cz/cezpnd2/dashboard/view",
            "wait_seconds": 3
        },
        "variants": {},
        "cookies": {
            "before_call": [],
            "after_call": [],
            "diff": ""
        },
        "verdict": "FAIL",
        "verdict_reason": "",
        "error": None
    }
    
    try:
        async with async_playwright() as playwright:
            # Step 1: Launch browser and login
            print("Step 1: Playwright login...")
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
            
            print("✓ Login successful")
            test_result["login"]["success"] = True
            test_result["login"]["final_url"] = page.url
            
            # Navigate to PND dashboard to establish session
            await page.goto("https://pnd.cezdistribuce.cz/cezpnd2/dashboard/view", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)  # Wait 3 seconds for session initialization
            
            # Prepare payload
            today = datetime.now()
            date_from = today.strftime("%d.%m.%Y 00:00")
            date_to = today.strftime("%d.%m.%Y 23:59")
            payload = build_pnd_payload(-1003, date_from, date_to, electrometer_id)
            
            # Test variant 1: JSON string
            print("Testing variant 1: JSON string...")
            cookies_before = await context.cookies()
            test_result["cookies"]["before_call"] = cookies_before
            
            try:
                response = await context.request.post(
                    PND_DATA_URL,
                    data=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                )
                
                raw_text = await response.text()
                response_headers = response.headers
                
                variant1_result = {
                    "request": {
                        "url": PND_DATA_URL,
                        "method": "POST",
                        "headers": {
                            "Content-Type": "application/json",
                            "other_headers": {k: v for k, v in response_headers.items() if k.lower() != "content-type"}
                        },
                        "body_raw": json.dumps(payload),
                        "body_type": "json_string"
                    },
                    "response": {
                        "status": response.status,
                        "headers": dict(response_headers),
                        "body_preview": raw_text[:500] if len(raw_text) > 500 else raw_text,
                        "is_json": False,
                        "is_html": "<html" in raw_text.lower()
                    },
                    "verdict": "PASS" if response.status == 200 else "FAIL",
                    "verdict_reason": f"HTTP {response.status}" if response.status != 200 else "Success"
                }
                
                # Try to parse JSON
                try:
                    json.loads(raw_text)
                    variant1_result["response"]["is_json"] = True
                except json.JSONDecodeError:
                    variant1_result["response"]["is_json"] = False
                
                test_result["variants"]["json_string_variant"] = variant1_result
                
                print(f"  Status: {response.status}")
                
            except Exception as e:
                test_result["variants"]["json_string_variant"] = {
                    "request": {
                        "url": PND_DATA_URL,
                        "method": "POST",
                        "headers": {"Content-Type": "application/json"},
                        "body_raw": json.dumps(payload),
                        "body_type": "json_string"
                    },
                    "response": {
                        "status": -1,
                        "headers": {},
                        "body_preview": str(e),
                        "is_json": False,
                        "is_html": False
                    },
                    "verdict": "FAIL",
                    "verdict_reason": f"Exception: {str(e)}"
                }
                print(f"  Error: {e}")
            
            cookies_after_json = await context.cookies()
            
            # Wait a bit between requests
            await page.wait_for_timeout(1000)
            
            # Test variant 2: Form data (dict)
            print("Testing variant 2: Form data...")
            
            try:
                response = await context.request.post(
                    PND_DATA_URL,
                    data=payload  # Pass dict directly for form encoding
                )
                
                raw_text = await response.text()
                response_headers = response.headers
                
                variant2_result = {
                    "request": {
                        "url": PND_DATA_URL,
                        "method": "POST",
                        "headers": {
                            "other_headers": {k: v for k, v in response_headers.items()}
                        },
                        "body_raw": json.dumps(payload),
                        "body_type": "form_dict"
                    },
                    "response": {
                        "status": response.status,
                        "headers": dict(response_headers),
                        "body_preview": raw_text[:500] if len(raw_text) > 500 else raw_text,
                        "is_json": False,
                        "is_html": "<html" in raw_text.lower()
                    },
                    "verdict": "PASS" if response.status == 200 else "FAIL",
                    "verdict_reason": f"HTTP {response.status}" if response.status != 200 else "Success"
                }
                
                # Try to parse JSON
                try:
                    json.loads(raw_text)
                    variant2_result["response"]["is_json"] = True
                except json.JSONDecodeError:
                    variant2_result["response"]["is_json"] = False
                
                test_result["variants"]["form_data_variant"] = variant2_result
                
                print(f"  Status: {response.status}")
                
            except Exception as e:
                test_result["variants"]["form_data_variant"] = {
                    "request": {
                        "url": PND_DATA_URL,
                        "method": "POST",
                        "headers": {},
                        "body_raw": json.dumps(payload),
                        "body_type": "form_dict"
                    },
                    "response": {
                        "status": -1,
                        "headers": {},
                        "body_preview": str(e),
                        "is_json": False,
                        "is_html": False
                    },
                    "verdict": "FAIL",
                    "verdict_reason": f"Exception: {str(e)}"
                }
                print(f"  Error: {e}")
            
            cookies_after_form = await context.cookies()
            test_result["cookies"]["after_call"] = cookies_after_form
            
            # Compare cookies
            def compare_cookies(before, after):
                before_names = {c["name"] for c in before}
                after_names = {c["name"] for c in after}
                added = after_names - before_names
                removed = before_names - after_names
                changed = []
                
                for after_cookie in after:
                    for before_cookie in before:
                        if after_cookie["name"] == before_cookie["name"]:
                            if after_cookie["value"] != before_cookie["value"]:
                                changed.append(after_cookie["name"])
                            break
                
                diff_parts = []
                if added:
                    diff_parts.append(f"Added: {', '.join(added)}")
                if removed:
                    diff_parts.append(f"Removed: {', '.join(removed)}")
                if changed:
                    diff_parts.append(f"Changed: {', '.join(changed)}")
                
                return "; ".join(diff_parts) if diff_parts else "No changes"
            
            test_result["cookies"]["diff"] = compare_cookies(cookies_before, cookies_after_form)
            
            # Determine overall verdict
            variants = test_result["variants"]
            any_pass = any(v["verdict"] == "PASS" for v in variants.values())
            
            if any_pass:
                test_result["verdict"] = "PASS"
                test_result["verdict_reason"] = "At least one variant succeeded"
            else:
                test_result["verdict"] = "FAIL"
                reasons = [f"{name}: {v['verdict_reason']}" for name, v in variants.items()]
                test_result["verdict_reason"] = "; ".join(reasons)
            
            # Close browser
            await browser.close()
            
    except Exception as e:
        test_result["error"] = str(e)
        test_result["verdict_reason"] = f"Test failed with exception: {str(e)}"
        print(f"✗ Test failed: {e}")
        return 1
    
    # Save results
    evidence_dir = Path("evidence/poc-results")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = evidence_dir / "test_3_reuse_context.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(test_result, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Results saved to: {output_file}")
    print(f"Overall verdict: {test_result['verdict']}")
    print(f"Reason: {test_result['verdict_reason']}")
    
    return 0 if test_result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))