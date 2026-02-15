"""Test API client for CEZ PND integration."""

from __future__ import annotations

from datetime import datetime

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses

from custom_components.cez_pnd.api_client import (
    AuthenticationError,
    CezPndApiClient,
    PndMeter,
    PndMeterData,
)


@pytest.mark.asyncio
async def test_fetch_meter_data_success() -> None:
    response_payload = {
        "hasData": True,
        "size": 96,
        "columns": [
            {"id": "1000", "name": "Datum", "unit": None},
            {"id": "1001", "name": "+A/784703", "unit": "kW"},
            {"id": "1002", "name": "-A/784703", "unit": "kW"},
            {"id": "1003", "name": "Rv/784703", "unit": "kW"},
        ],
        "values": [
            {
                "1000": {"v": "15.02.2026 00:15"},
                "1001": {"v": "0,705", "s": 32},
                "1002": {"v": "0,000", "s": 32},
                "1003": {"v": "0,010", "s": 64},
            },
            {
                "1000": {"v": "15.02.2026 00:30"},
                "1001": {"v": "0,650", "s": 32},
                "1002": {"v": "0,000", "s": 32},
                "1003": {"v": "0,011", "s": 32},
            },
        ],
        "statuses": {
            "32": {"n": "naměřená data OK", "c": "#222222", "m": 32},
            "64": {"n": "odhad", "c": "#999999", "m": 64},
        },
    }
    url = "https://pnd.cezdistribuce.cz/cezpnd2/external/data"
    interval_from = datetime(2026, 2, 14, 0, 0)
    interval_to = datetime(2026, 2, 15, 0, 0)

    def request_callback(url, **kwargs):
        assert kwargs["json"] == {
            "format": "table",
            "idAssembly": -1003,
            "idDeviceSet": None,
            "intervalFrom": "14.02.2026 00:00",
            "intervalTo": "15.02.2026 00:00",
            "compareFrom": None,
            "opmId": None,
            "electrometerId": "784703",
        }
        return CallbackResult(payload=response_payload)

    with aioresponses() as mocked:
        mocked.post(url, callback=request_callback)
        async with aiohttp.ClientSession() as session:
            client = CezPndApiClient("user", "pass", session)
            data = await client.fetch_meter_data(
                electrometer_id="784703",
                interval_from=interval_from,
                interval_to=interval_to,
            )

    assert isinstance(data, PndMeterData)
    assert data.has_data is True
    assert data.size == 96
    assert len(data.readings) == 2
    first = data.readings[0]
    assert first.timestamp == datetime(2026, 2, 15, 0, 15)
    assert first.consumption_kw == 0.705
    assert first.production_kw == 0.0
    assert first.reactive_kw == 0.01
    assert first.status == 32
    assert first.status_text == "naměřená data OK"


@pytest.mark.asyncio
async def test_fetch_meter_data_parses_czech_decimals() -> None:
    response_payload = {
        "hasData": True,
        "size": 1,
        "columns": [
            {"id": "1000", "name": "Datum", "unit": None},
            {"id": "1001", "name": "+A/784703", "unit": "kW"},
            {"id": "1002", "name": "-A/784703", "unit": "kW"},
            {"id": "1003", "name": "Rv/784703", "unit": "kW"},
        ],
        "values": [
            {
                "1000": {"v": "15.02.2026 00:15"},
                "1001": {"v": "1,234", "s": 32},
                "1002": {"v": "0,500", "s": 32},
                "1003": {"v": "0,010", "s": 32},
            }
        ],
        "statuses": {"32": {"n": "naměřená data OK", "c": "#222222", "m": 32}},
    }
    url = "https://pnd.cezdistribuce.cz/cezpnd2/external/data"

    with aioresponses() as mocked:
        mocked.post(url, payload=response_payload)
        async with aiohttp.ClientSession() as session:
            client = CezPndApiClient("user", "pass", session)
            data = await client.fetch_meter_data(
                electrometer_id="784703",
                interval_from=datetime(2026, 2, 14, 0, 0),
                interval_to=datetime(2026, 2, 15, 0, 0),
            )

    assert data.readings[0].consumption_kw == 1.234
    assert data.readings[0].production_kw == 0.5


@pytest.mark.asyncio
async def test_fetch_meter_data_handles_empty_response() -> None:
    response_payload = {
        "hasData": False,
        "size": 0,
        "columns": [],
        "values": [],
        "statuses": {},
    }
    url = "https://pnd.cezdistribuce.cz/cezpnd2/external/data"

    with aioresponses() as mocked:
        mocked.post(url, payload=response_payload)
        async with aiohttp.ClientSession() as session:
            client = CezPndApiClient("user", "pass", session)
            data = await client.fetch_meter_data(
                electrometer_id="784703",
                interval_from=datetime(2026, 2, 14, 0, 0),
                interval_to=datetime(2026, 2, 15, 0, 0),
            )

    assert data.has_data is False
    assert data.readings == []


@pytest.mark.asyncio
async def test_fetch_meter_data_handles_missing_intervals() -> None:
    response_payload = {
        "hasData": True,
        "size": 96,
        "columns": [
            {"id": "1000", "name": "Datum", "unit": None},
            {"id": "1001", "name": "+A/784703", "unit": "kW"},
        ],
        "values": [
            {
                "1000": {"v": "15.02.2026 00:15"},
                "1001": {"v": "0,705", "s": 32},
            }
        ],
        "statuses": {"32": {"n": "naměřená data OK", "c": "#222222", "m": 32}},
    }
    url = "https://pnd.cezdistribuce.cz/cezpnd2/external/data"

    with aioresponses() as mocked:
        mocked.post(url, payload=response_payload)
        async with aiohttp.ClientSession() as session:
            client = CezPndApiClient("user", "pass", session)
            data = await client.fetch_meter_data(
                electrometer_id="784703",
                interval_from=datetime(2026, 2, 14, 0, 0),
                interval_to=datetime(2026, 2, 15, 0, 0),
            )

    assert data.size == 96
    assert len(data.readings) == 1
    assert data.readings[0].consumption_kw == 0.705


@pytest.mark.asyncio
async def test_fetch_meter_data_session_expired() -> None:
    url = "https://pnd.cezdistribuce.cz/cezpnd2/external/data"

    with aioresponses() as mocked:
        mocked.post(url, status=401)
        async with aiohttp.ClientSession() as session:
            client = CezPndApiClient("user", "pass", session)
            with pytest.raises(AuthenticationError):
                await client.fetch_meter_data(
                    electrometer_id="784703",
                    interval_from=datetime(2026, 2, 14, 0, 0),
                    interval_to=datetime(2026, 2, 15, 0, 0),
                )


@pytest.mark.asyncio
async def test_fetch_meters_list() -> None:
    response_payload = {
        "electrometers": [
            {"id": "784703", "name": "Main Meter"},
            {"electrometerId": "123456", "name": "Garage"},
        ]
    }
    url = "https://pnd.cezdistribuce.cz/cezpnd2/external/dashboard/window/definition"

    with aioresponses() as mocked:
        mocked.get(url, payload=response_payload)
        async with aiohttp.ClientSession() as session:
            client = CezPndApiClient("user", "pass", session)
            meters = await client.fetch_available_meters()

    assert meters == [
        PndMeter(electrometer_id="784703", name="Main Meter"),
        PndMeter(electrometer_id="123456", name="Garage"),
    ]


def test_parse_status_codes() -> None:
    statuses = {
        "32": {"n": "naměřená data OK", "c": "#222222", "m": 32},
        "64": {"n": "odhad", "c": "#999999", "m": 64},
    }

    parsed = CezPndApiClient._parse_status_codes(statuses)

    assert parsed[32] == "naměřená data OK"
    assert parsed[64] == "odhad"
    assert parsed.get(999, "unknown") == "unknown"


# ===========================================================================
# Authentication Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_authenticate_success() -> None:
    """Test successful authentication flow."""
    # Mock the 5-step OAuth2 redirect chain
    mock_login_page = """
    <html>
    <input type="hidden" name="execution" value="test-execution-token-12345"/>
    </html>
    """
    mock_post_login_response = """
    HTTP/1.1 302 Found
    Location: https://cas.cez.cz/cas/oauth2.0/callbackAuthorize?ticket=ST-test-ticket-abc
    """
    mock_authorize_response = """
    HTTP/1.1 302 Found
    Location: https://cas.cez.cz/cas/oidc/authorize?response_type=code&client_id=M7z7ZnPjX3FNMouD.onpremise.bp.pnd.prod&redirect_uri=https://pnd.cezdistribuce.cz/cezpnd2/login/oauth2/code/mepas-external&scope=openid+profile&code=OC-test-code-xyz
    """
    mock_oidc_response = """
    HTTP/1.1 302 Found
    Location: https://pnd.cezdistribuce.cz/cezpnd2/login/oauth2/code/mepas-external?code=OC-test-code-xyz&state=xyz
    """
    mock_dashboard_response = """
    HTTP/1.1 200 OK
    <html>Dashboard loaded</html>
    """
    
    def request_callback(url, **kwargs):
        assert kwargs.get("method", "GET") == "GET"
        
        if "callbackAuthorize" in url:
            return CallbackResult(payload=mock_authorize_response)
        elif "oidc/authorize" in url:
            return CallbackResult(payload=mock_oidc_response)
        elif "dashboard/view" in url:
            return CallbackResult(payload=mock_dashboard_response)
        # For login page GET
        return CallbackResult(payload=mock_login_page)
    
    with aioresponses() as mocked:
        # Login page GET
        mocked.get(
            "https://cas.cez.cz/cas/login?service=https://pnd.cezdistribuce.cz/cezpnd2/login/oauth2/code/mepas-external",
            callback=request_callback,
        )
        # POST credentials
        mocked.post(
            "https://cas.cez.cz/cas/login",
            callback=request_callback,
        )
        # Follow redirects (authorize, oidc, dashboard)
        mocked.get(
            "https://cas.cez.cz/cas/oauth2.0/callbackAuthorize?ticket=ST-test-ticket-abc",
            callback=request_callback,
        )
        mocked.get(
            "https://cas.cez.cz/cas/oidc/authorize",
            callback=request_callback,
        )
        mocked.get(
            "https://pnd.cezdistribuce.cz/cezpnd2/login/oauth2/code/mepas-external?code=OC-test-code-xyz&state=xyz",
            callback=request_callback,
        )
        
        async with aiohttp.ClientSession() as session:
            client = CezPndApiClient("test@example.com", "password123", session)
            user_id = await client.authenticate()
    
    assert user_id == "test@example.com"


@pytest.mark.asyncio
async def test_authenticate_invalid_credentials() -> None:
    """Test authentication with invalid credentials."""
    mock_error_response = """
    <html>
    <div class="error">Invalid credentials</div>
    </html>
    """
    
    def request_callback(url, **kwargs):
        if "cas/login" in url and kwargs.get("method", "POST"):
            return CallbackResult(text=mock_error_response)
        return CallbackResult(text=mock_login_page)
    
    with aioresponses() as mocked:
        mocked.get(
            "https://cas.cez.cz/cas/login?service=...",
            callback=request_callback,
        )
        mocked.post(
            "https://cas.cez.cz/cas/login",
            callback=request_callback,
        )
        
        async with aiohttp.ClientSession() as session:
            client = CezPndApiClient("test@example.com", "wrongpassword", session)
            with pytest.raises(AuthenticationError) as exc_info:
                await client.authenticate()
    
    assert str(exc_info.value) == "Invalid credentials"


@pytest.mark.asyncio
async def test_authenticate_network_error() -> None:
    """Test authentication with network error."""
    
    def request_callback(url, **kwargs):
        # First call returns successfully
        if "cas/login" in url and kwargs.get("method", "POST"):
            return CallbackResult(text="<html>Login page</html>")
        raise aiohttp.ClientError("Network error")
    
    with aioresponses() as mocked:
        mocked.get(
            "https://cas.cez.cz/cas/login?service=...",
            callback=request_callback,
        )
        
        async with aiohttp.ClientSession() as session:
            client = CezPndApiClient("test@example.com", "password123", session)
            with pytest.raises(aiohttp.ClientError):
                await client.authenticate()


@pytest.mark.asyncio
async def test_extract_execution_token() -> None:
    """Test extraction of execution token from CAS login page HTML."""
    mock_html = """
    <html>
    <form name="fm1">
        <input type="hidden" name="execution" value="test-execution-token"/>
    </form>
    </html>
    """
    
    with aioresponses() as mocked:
        mocked.get(
            "https://cas.cez.cz/cas/login",
            callback=CallbackResult(text=mock_html),
        )
        
        async with aiohttp.ClientSession() as session:
            client = CezPndApiClient("test@example.com", "password123", session)
            # Call the private method
            token = await client._extract_execution_token(mock_html)
    
    assert token == "test-execution-token"


@pytest.mark.asyncio
async def test_follow_oauth2_redirects() -> None:
    """Test following OAuth2 redirect chain."""
    # Mock 5-step redirect chain
    redirects = []
    
    def request_callback(url, **kwargs):
        redirects.append(url)
        # Last redirect is to dashboard
        if "dashboard/view" in url:
            return CallbackResult(text="<html>Dashboard</html>")
        # All other redirects return 302 with Location header
        raise aiohttp.ClientError("Redirect", status=302, headers={"Location": url})
    
    with aioresponses() as mocked:
        # Login page
        mocked.get(
            "https://cas.cez.cz/cas/login?service=...",
            callback=CallbackResult(text="<html>Login page</html>"),
        )
        # POST credentials
        mocked.post(
            "https://cas.cez.cz/cas/login",
            callback=request_callback,
        )
        
        async with aiohttp.ClientSession() as session:
            client = CezPndApiClient("test@example.com", "password123", session)
            user_id = await client.authenticate()
    
    assert len(redirects) == 4  # authorize, oidc, code, dashboard
