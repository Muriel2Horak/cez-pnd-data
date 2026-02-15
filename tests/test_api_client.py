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
    mock_login_page = '<html><input type="hidden" name="execution" value="test-execution-token-12345"/></html>'

    service_url = "https://pnd.cezdistribuce.cz/cezpnd2/login/oauth2/code/mepas-external"
    login_get_url = f"https://cas.cez.cz/cas/login?service={service_url}"

    with aioresponses() as mocked:
        # Step 1: GET CAS login page
        mocked.get(login_get_url, body=mock_login_page)
        # Step 2: POST credentials
        mocked.post("https://cas.cez.cz/cas/login", body="<html>OK</html>")
        # Step 3: GET authorize
        mocked.get(
            "https://cas.cez.cz/cas/oidc/authorize",
            body="OK",
            repeat=True,
        )
        # Step 5: GET dashboard
        mocked.get(
            "https://pnd.cezdistribuce.cz/cezpnd2/external/dashboard/view",
            body="<html>Dashboard</html>",
        )

        async with aiohttp.ClientSession() as session:
            client = CezPndApiClient("test@example.com", "password123", session)
            user_id = await client.authenticate()

    assert user_id == "test@example.com"


@pytest.mark.asyncio
async def test_authenticate_invalid_credentials() -> None:
    """Test authentication with invalid credentials."""
    mock_login_page = '<html><input type="hidden" name="execution" value="tok"/></html>'
    mock_error_response = "<html><div>Invalid credentials</div></html>"

    service_url = "https://pnd.cezdistribuce.cz/cezpnd2/login/oauth2/code/mepas-external"
    login_get_url = f"https://cas.cez.cz/cas/login?service={service_url}"

    with aioresponses() as mocked:
        mocked.get(login_get_url, body=mock_login_page)
        mocked.post("https://cas.cez.cz/cas/login", body=mock_error_response)

        async with aiohttp.ClientSession() as session:
            client = CezPndApiClient("test@example.com", "wrongpassword", session)
            with pytest.raises(AuthenticationError) as exc_info:
                await client.authenticate()

    assert "Invalid credentials" in str(exc_info.value)


@pytest.mark.asyncio
async def test_authenticate_network_error() -> None:
    """Test authentication with network error."""
    service_url = "https://pnd.cezdistribuce.cz/cezpnd2/login/oauth2/code/mepas-external"
    login_get_url = f"https://cas.cez.cz/cas/login?service={service_url}"

    with aioresponses() as mocked:
        mocked.get(login_get_url, exception=aiohttp.ClientError("Network error"))

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

    async with aiohttp.ClientSession() as session:
        client = CezPndApiClient("test@example.com", "password123", session)
        token = await client._extract_execution_token(mock_html)

    assert token == "test-execution-token"


@pytest.mark.asyncio
async def test_extract_execution_token_missing() -> None:
    """Test extraction of execution token raises when missing."""
    mock_html = "<html><body>No token here</body></html>"

    async with aiohttp.ClientSession() as session:
        client = CezPndApiClient("test@example.com", "password123", session)
        with pytest.raises(AuthenticationError, match="execution token"):
            await client._extract_execution_token(mock_html)
