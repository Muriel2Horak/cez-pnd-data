"""Shared pytest fixtures for CEZ PND add-on testing.

Provides reusable fixtures for:
- PND API responses (happy path, redirects)
- DIP API responses (JSON, HTML maintenance pages)
- Playwright browser/context mocks
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

# =============================================================================
# PND API Response Fixtures (301/302 redirects, JSON data)
# =============================================================================


@pytest.fixture
def pnd_json_response() -> AsyncMock:
    """Standard PND JSON API response (happy path, status 200).

    Returns AsyncMock with:
    - status: 200
    - json(): AsyncMock returning valid PND data structure
    """
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={
            "hasData": True,
            "columns": [
                {"id": "1000", "name": "Datum", "unit": None},
                {"id": "1001", "name": "+A/784703", "unit": "kW"},
                {"id": "1002", "name": "-A/784703", "unit": "kW"},
                {"id": "1003", "name": "Rv/784703", "unit": "kW"},
            ],
            "values": [
                {
                    "1000": {"v": "14.02.2026 00:15"},
                    "1001": {"v": "1,42", "s": 32},
                    "1002": {"v": "0,05", "s": 32},
                    "1003": {"v": "5,46", "s": 32},
                },
            ],
        }
    )
    return response


@pytest.fixture
def pnd_301_redirect_response() -> AsyncMock:
    """PND 301 Permanent Redirect response.

    Simulates session expiry / permanent redirect scenario.
    Returns AsyncMock with:
    - status: 301
    - headers: Location header with redirect URL
    """
    response = AsyncMock()
    response.status = 301
    response.headers = {"Location": "https://pnd.cezdistribuce.cz/login"}
    return response


@pytest.fixture
def pnd_302_redirect_response() -> AsyncMock:
    """PND 302 Found redirect response.

    Simulates OAuth redirect / temporary redirect scenario (session expired).
    Returns AsyncMock with:
    - status: 302
    - headers: Location header with redirect URL
    """
    response = AsyncMock()
    response.status = 302
    response.headers = {"Location": "https://dip.cezdistribuce.cz/irj/portal"}
    return response


@pytest.fixture
def pnd_no_data_response() -> AsyncMock:
    """PND response with hasData: false (no data for requested date).

    Used for testing Tab 17 fallback logic.
    Returns AsyncMock with:
    - status: 200
    - json(): AsyncMock returning empty data structure
    """
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={"hasData": False, "columns": [], "values": []}
    )
    return response


@pytest.fixture
def pnd_waf_warmup_response() -> AsyncMock:
    """PND WAF warmup response (expected 400 Bad Request).

    The first POST request to PND API intentionally gets 400 to set
    WAF cookies/state. Second request with form-encoded data succeeds.
    Returns AsyncMock with:
    - status: 400 (expected for warmup)
    """
    response = AsyncMock()
    response.status = 400
    return response


# =============================================================================
# DIP API Response Fixtures (JSON, HTML maintenance)
# =============================================================================


@pytest.fixture
def dip_json_response() -> AsyncMock:
    """DIP API JSON response (happy path, status 200).

    Used for HDO signals endpoint and token endpoint.
    Returns AsyncMock with:
    - status: 200
    - json(): AsyncMock returning valid DIP data structure
    """
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={
            "token": "test-token-abc123",
            "data": {
                "signal": "EVV2",
                "den": "Pondělí",
                "datum": "16.02.2026",
                "casy": "00:00-08:00; 09:00-12:00; 13:00-15:00; 16:00-19:00; 20:00-24:00",
            },
        }
    )
    return response


@pytest.fixture
def dip_token_response() -> AsyncMock:
    """DIP token endpoint response.

    Returns AsyncMock with:
    - status: 200
    - json(): AsyncMock returning token only
    """
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"token": "test-token-xyz789"})
    return response


@pytest.fixture
def dip_html_maintenance_response() -> AsyncMock:
    """DIP HTML maintenance page response.

    Simulates DIP outage scenario where HTML is returned instead of JSON.
    Returns AsyncMock with:
    - status: 200 (or 503 for service unavailable)
    - text(): AsyncMock returning HTML content
    - headers: Content-Type: text/html (not JSON)
    """
    response = AsyncMock()
    response.status = 200
    response.headers = {"Content-Type": "text/html; charset=UTF-8"}
    response.text = AsyncMock(return_value="""
<!DOCTYPE html>
<html>
<head>
    <title>Údržba systému | CEZ Distribuce</title>
</head>
<body>
    <h1>Plánovaná údržba</h1>
    <p>Systém DIP je momentálně nedostupný z důvodu plánované údržby.</p>
    <p>Omlouváme se za nepříjemnosti.</p>
</body>
</html>
        """.strip())
    return response


@pytest.fixture
def dip_html_login_page_response() -> AsyncMock:
    """DIP HTML login page response.

    Simulates redirect to login form when session is expired.
    Returns AsyncMock with:
    - status: 200
    - text(): AsyncMock returning HTML login form
    """
    response = AsyncMock()
    response.status = 200
    response.headers = {"Content-Type": "text/html; charset=UTF-8"}
    response.text = AsyncMock(return_value="""
<!DOCTYPE html>
<html>
<head>
    <title>Přihlášení | CEZ Distribuce</title>
</head>
<body>
    <form id="loginForm">
        <input type="text" name="username" />
        <input type="password" name="password" />
        <button type="submit">Přihlásit</button>
    </form>
</body>
</html>
        """.strip())
    return response


@pytest.fixture
def dip_401_unauthorized_response() -> AsyncMock:
    """DIP 401 Unauthorized response.

    Used for testing token refresh / re-auth scenarios.
    Returns AsyncMock with:
    - status: 401
    """
    response = AsyncMock()
    response.status = 401
    return response


@pytest.fixture
def dip_503_service_unavailable_response() -> AsyncMock:
    """DIP 503 Service Unavailable response.

    Used for testing DIP downtime scenarios.
    Returns AsyncMock with:
    - status: 503
    - text(): AsyncMock returning service unavailable HTML
    """
    response = AsyncMock()
    response.status = 503
    response.headers = {"Content-Type": "text/html; charset=UTF-8"}
    response.text = AsyncMock(return_value="""
<!DOCTYPE html>
<html>
<head><title>Service Unavailable</title></head>
<body>
    <h1>503 Service Unavailable</h1>
    <p>The server is temporarily unable to service your request.</p>
</body>
</html>
        """.strip())
    return response


# =============================================================================
# Playwright Mock Fixtures (browser, context, request)
# =============================================================================


@pytest.fixture
def sample_cookies() -> list[dict[str, Any]]:
    """Sample cookies for testing.

    Returns list of cookie dicts with name, value, domain, path.
    """
    return [
        {
            "name": "JSESSIONID",
            "value": "test-session-abc123",
            "domain": ".cezdistribuce.cz",
            "path": "/",
        },
        {
            "name": "LWPCOOKIE",
            "value": "test-lwp-value",
            "domain": ".cezdistribuce.cz",
            "path": "/",
        },
    ]


@pytest.fixture
def mock_playwright_response(pnd_json_response: AsyncMock) -> AsyncMock:
    """Playwright APIResponse mock.

    Returns AsyncMock with:
    - status: from pnd_json_response
    - json(): from pnd_json_response
    - url(): Returns mock URL
    """
    response = pnd_json_response
    response.url = AsyncMock(
        return_value="https://pnd.cezdistribuce.cz/cezpnd2/external/data"
    )
    return response


@pytest.fixture
def mock_playwright_context() -> AsyncMock:
    """Playwright BrowserContext mock.

    Returns AsyncMock with:
    - add_cookies(): AsyncMock
    - cookies(): AsyncMock returning sample cookies
    - close(): AsyncMock
    - request: Request mock with post() returning mock response
    """
    context = AsyncMock()
    context.add_cookies = AsyncMock()
    context.cookies = AsyncMock(
        return_value=[
            {
                "name": "JSESSIONID",
                "value": "test-session-xyz789",
                "domain": ".cezdistribuce.cz",
                "path": "/",
            }
        ]
    )
    context.close = AsyncMock()

    # Mock request.post
    mock_request = AsyncMock()
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(
        return_value={
            "hasData": True,
            "columns": [],
            "values": [],
        }
    )
    mock_request.post = AsyncMock(return_value=mock_response)
    context.request = mock_request

    return context


@pytest.fixture
def mock_playwright_browser(mock_playwright_context: AsyncMock) -> AsyncMock:
    """Playwright Browser mock.

    Returns AsyncMock with:
    - new_context(): AsyncMock returning mock_playwright_context
    - close(): AsyncMock
    """
    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=mock_playwright_context)
    browser.close = AsyncMock()
    return browser


@pytest.fixture
def mock_playwright_launch(mock_playwright_browser: AsyncMock) -> AsyncMock:
    """Playwright launch mock (complete stack).

    Returns AsyncMock that acts as async context manager:
    - __aenter__: Returns Browser mock
    - __aexit__: Returns None
    """
    mock_pw = AsyncMock()
    mock_pw.chromium = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_playwright_browser)

    mock_async_pw = AsyncMock()
    mock_async_pw.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_async_pw.__aexit__ = AsyncMock(return_value=False)

    return mock_async_pw


# =============================================================================
# aiohttp Session Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_aiohttp_session() -> AsyncMock:
    """aiohttp ClientSession mock.

    Returns Mock (not AsyncMock) with:
    - get(): Mock returning async context manager
    - close(): AsyncMock
    """
    session = AsyncMock()
    session.close = AsyncMock()

    # Create async context manager for response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"data": "test"})
    mock_response.headers = {}

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    session.get = AsyncMock(return_value=mock_cm)

    return session
