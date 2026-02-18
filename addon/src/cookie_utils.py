from __future__ import annotations

from typing import Any


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
