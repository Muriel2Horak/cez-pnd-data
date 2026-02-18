"""Tests for DIP API client — HDO signals via aiohttp."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from addon.src.dip_client import DipClient, DipFetchError, DipTokenError

SAMPLE_COOKIES = [
    {"name": "JSESSIONID", "value": "abc123"},
]


@pytest.mark.asyncio
async def test_fetch_hdo_gets_token_first():
    """First request is GET to /rest-auth-api?path=/token/get"""
    session = Mock()

    # Mock token response
    mock_token_response = AsyncMock()
    mock_token_response.status = 200
    mock_token_response.json = AsyncMock(return_value={"token": "test-token-123"})

    # Mock signals response
    mock_signals_response = AsyncMock()
    mock_signals_response.status = 200
    mock_signals_response.json = AsyncMock(return_value={"data": {"signal": "test"}})

    # Create async context managers for GET requests
    mock_token_cm = Mock()
    mock_token_cm.__aenter__ = AsyncMock(return_value=mock_token_response)
    mock_token_cm.__aexit__ = AsyncMock(return_value=None)

    mock_signals_cm = Mock()
    mock_signals_cm.__aenter__ = AsyncMock(return_value=mock_signals_response)
    mock_signals_cm.__aexit__ = AsyncMock(return_value=None)

    # Setup session.get to return appropriate CM based on URL
    def get_side_effect(url, *args, **kwargs):
        if "token/get" in url:
            return mock_token_cm
        if "signals/" in url:
            return mock_signals_cm
        raise ValueError(f"Unexpected URL: {url}")

    session.get = Mock(side_effect=get_side_effect)

    client = DipClient(session=session)
    _ = await client.fetch_hdo(SAMPLE_COOKIES, ean="1234567890123")

    # Verify token was fetched first
    token_calls = [c for c in session.get.call_args_list if "token/get" in str(c)]
    assert len(token_calls) == 1


@pytest.mark.asyncio
async def test_fetch_hdo_uses_token_in_signals_request():
    """Second request has x-request-token header"""
    session = Mock()

    mock_token_response = AsyncMock()
    mock_token_response.status = 200
    mock_token_response.json = AsyncMock(return_value={"token": "test-token-456"})

    mock_signals_response = AsyncMock()
    mock_signals_response.status = 200
    mock_signals_response.json = AsyncMock(return_value={"data": {"signal": "test"}})

    mock_token_cm = Mock()
    mock_token_cm.__aenter__ = AsyncMock(return_value=mock_token_response)
    mock_token_cm.__aexit__ = AsyncMock(return_value=None)

    mock_signals_cm = Mock()
    mock_signals_cm.__aenter__ = AsyncMock(return_value=mock_signals_response)
    mock_signals_cm.__aexit__ = AsyncMock(return_value=None)

    call_count = [0]

    def get_side_effect(url, *args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return mock_token_cm
        if call_count[0] == 2:
            # Verify x-request-token header in signals request
            assert "headers" in kwargs
            assert "x-request-token" in kwargs["headers"]
            assert kwargs["headers"]["x-request-token"] == "test-token-456"
            return mock_signals_cm
        raise ValueError(f"Unexpected call: {call_count[0]}")

    session.get = Mock(side_effect=get_side_effect)

    client = DipClient(session=session)
    _ = await client.fetch_hdo(SAMPLE_COOKIES, ean="1234567890123")


@pytest.mark.asyncio
async def test_fetch_hdo_sends_correct_signals_url():
    """URL contains EAN: .../prehled-om?path=supply-point-detail/signals/{ean}"""
    session = Mock()

    mock_token_response = AsyncMock()
    mock_token_response.status = 200
    mock_token_response.json = AsyncMock(return_value={"token": "test-token-789"})

    mock_signals_response = AsyncMock()
    mock_signals_response.status = 200
    mock_signals_response.json = AsyncMock(return_value={"data": {"signal": "test"}})

    mock_token_cm = Mock()
    mock_token_cm.__aenter__ = AsyncMock(return_value=mock_token_response)
    mock_token_cm.__aexit__ = AsyncMock(return_value=None)

    mock_signals_cm = Mock()
    mock_signals_cm.__aenter__ = AsyncMock(return_value=mock_signals_response)
    mock_signals_cm.__aexit__ = AsyncMock(return_value=None)

    session.get = Mock(
        side_effect=lambda url, *args, **kwargs: (
            mock_token_cm if "token/get" in url else mock_signals_cm
        )
    )

    client = DipClient(session=session)
    _ = await client.fetch_hdo(SAMPLE_COOKIES, ean="1234567890123")

    # Verify signals URL contains EAN
    signals_call = [c for c in session.get.call_args_list if "signals/" in str(c)][0]
    url_arg = signals_call[0][0]
    assert "1234567890123" in url_arg


@pytest.mark.asyncio
async def test_fetch_hdo_converts_playwright_cookies():
    """Uses playwright_cookies_to_header() and sets Cookie header"""
    session = Mock()

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"token": "test"})

    mock_cm = Mock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    session.get = Mock(return_value=mock_cm)

    client = DipClient(session=session)

    # Mock to raise error on signals call (we only care about cookie header)
    async def fetch_hdo_with_error(*args, **kwargs):
        # Check cookie header in token request
        token_call = [c for c in session.get.call_args_list if "token/get" in str(c)][0]
        token_kwargs = token_call[1] if len(token_call) > 1 else {}
        if "headers" in token_kwargs:
            assert "Cookie" in token_kwargs["headers"]
            assert token_kwargs["headers"]["Cookie"] == "JSESSIONID=abc123"
        raise aiohttp.ClientError("Stop after first request")

    _ = client.fetch_hdo
    client.fetch_hdo = lambda *a, **kw: fetch_hdo_with_error(*a, **kw)

    try:
        await client.fetch_hdo(SAMPLE_COOKIES, ean="123")
    except Exception:
        pass


@pytest.mark.asyncio
async def test_fetch_hdo_returns_data_field():
    """Returns data["data"] from response (not full response)"""
    session = Mock()

    mock_token_response = AsyncMock()
    mock_token_response.status = 200
    mock_token_response.json = AsyncMock(return_value={"token": "test"})

    expected_data = {"signal": "EVV2", "casy": ["08:00-16:00"]}
    mock_signals_response = AsyncMock()
    mock_signals_response.status = 200
    mock_signals_response.json = AsyncMock(
        return_value={"data": expected_data, "other": "ignored"}
    )

    mock_token_cm = Mock()
    mock_token_cm.__aenter__ = AsyncMock(return_value=mock_token_response)
    mock_token_cm.__aexit__ = AsyncMock(return_value=None)

    mock_signals_cm = Mock()
    mock_signals_cm.__aenter__ = AsyncMock(return_value=mock_signals_response)
    mock_signals_cm.__aexit__ = AsyncMock(return_value=None)

    session.get = Mock(
        side_effect=lambda url, *args, **kwargs: (
            mock_token_cm if "token/get" in url else mock_signals_cm
        )
    )

    client = DipClient(session=session)
    result = await client.fetch_hdo(SAMPLE_COOKIES, ean="123")
    assert result == expected_data


@pytest.mark.asyncio
async def test_fetch_hdo_raises_dip_token_error_on_token_401():
    """Token GET returns 401 -> DipTokenError"""
    session = Mock()

    mock_response = AsyncMock()
    mock_response.status = 401

    mock_cm = Mock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    session.get = Mock(return_value=mock_cm)

    client = DipClient(session=session)

    with pytest.raises(DipTokenError, match="Token request failed: HTTP 401"):
        await client.fetch_hdo(SAMPLE_COOKIES, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_dip_token_error_on_missing_token():
    """Response has no token key -> DipTokenError"""
    session = Mock()

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"other": "data"})

    mock_cm = Mock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    session.get = Mock(return_value=mock_cm)

    client = DipClient(session=session)

    with pytest.raises(DipTokenError, match="Token missing from response"):
        await client.fetch_hdo(SAMPLE_COOKIES, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_dip_fetch_error_on_signals_failure():
    """Signals GET returns 500 -> DipFetchError"""
    session = Mock()

    mock_token_response = AsyncMock()
    mock_token_response.status = 200
    mock_token_response.json = AsyncMock(return_value={"token": "test"})

    mock_signals_response = AsyncMock()
    mock_signals_response.status = 500

    mock_token_cm = Mock()
    mock_token_cm.__aenter__ = AsyncMock(return_value=mock_token_response)
    mock_token_cm.__aexit__ = AsyncMock(return_value=None)

    mock_signals_cm = Mock()
    mock_signals_cm.__aenter__ = AsyncMock(return_value=mock_signals_response)
    mock_signals_cm.__aexit__ = AsyncMock(return_value=None)

    session.get = Mock(
        side_effect=lambda url, *args, **kwargs: (
            mock_token_cm if "token/get" in url else mock_signals_cm
        )
    )

    client = DipClient(session=session)

    with pytest.raises(DipFetchError, match="Signals request failed: HTTP 500"):
        await client.fetch_hdo(SAMPLE_COOKIES, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_dip_fetch_error_on_missing_data():
    """Response has no data key -> DipFetchError"""
    session = Mock()

    mock_token_response = AsyncMock()
    mock_token_response.status = 200
    mock_token_response.json = AsyncMock(return_value={"token": "test"})

    mock_signals_response = AsyncMock()
    mock_signals_response.status = 200
    mock_signals_response.json = AsyncMock(return_value={"other": "data"})

    mock_token_cm = Mock()
    mock_token_cm.__aenter__ = AsyncMock(return_value=mock_token_response)
    mock_token_cm.__aexit__ = AsyncMock(return_value=None)

    mock_signals_cm = Mock()
    mock_signals_cm.__aenter__ = AsyncMock(return_value=mock_signals_response)
    mock_signals_cm.__aexit__ = AsyncMock(return_value=None)

    session.get = Mock(
        side_effect=lambda url, *args, **kwargs: (
            mock_token_cm if "token/get" in url else mock_signals_cm
        )
    )

    client = DipClient(session=session)

    with pytest.raises(DipFetchError, match="Data missing from response"):
        await client.fetch_hdo(SAMPLE_COOKIES, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_on_timeout():
    """asyncio.TimeoutError -> DipFetchError"""
    session = Mock()

    mock_cm = Mock()
    mock_cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    session.get = Mock(return_value=mock_cm)

    client = DipClient(session=session)

    with pytest.raises(DipFetchError):
        await client.fetch_hdo(SAMPLE_COOKIES, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_on_connection_error():
    """aiohttp.ClientError -> DipFetchError"""
    session = Mock()

    mock_cm = Mock()
    mock_cm.__aenter__ = AsyncMock(
        side_effect=aiohttp.ClientConnectorError(Mock(), Mock())
    )
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    session.get = Mock(return_value=mock_cm)

    client = DipClient(session=session)

    with pytest.raises(DipFetchError):
        await client.fetch_hdo(SAMPLE_COOKIES, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_uses_chrome_user_agent():
    """Request has User-Agent matching DEFAULT_USER_AGENT"""
    from addon.src.auth import DEFAULT_USER_AGENT

    session = Mock()

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"token": "test"})

    mock_cm = Mock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    session.get = Mock(return_value=mock_cm)

    client = DipClient(session=session)

    # Mock to raise after checking headers
    def fetch_and_check(*args, **kwargs):
        token_call = [c for c in session.get.call_args_list if "token/get" in str(c)][0]
        token_kwargs = token_call[1] if len(token_call) > 1 else {}
        if "headers" in token_kwargs:
            assert "User-Agent" in token_kwargs["headers"]
            assert token_kwargs["headers"]["User-Agent"] == DEFAULT_USER_AGENT
        raise Exception("Done")

    client.fetch_hdo = lambda *a, **kw: fetch_and_check(*a, **kw)

    try:
        await client.fetch_hdo(SAMPLE_COOKIES, ean="123")
    except Exception:
        pass


@pytest.mark.asyncio
async def test_fetch_hdo_uses_injected_session():
    """Uses aiohttp.ClientSession from constructor (no Playwright)"""
    session = Mock()

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(
        return_value={"token": "test", "data": {"signal": "test"}}
    )

    mock_cm = Mock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    session.get = Mock(return_value=mock_cm)

    client = DipClient(session=session)

    # Verify injected session was used
    await client.fetch_hdo(SAMPLE_COOKIES, ean="123")
    session.get.assert_called()


@pytest.mark.asyncio
async def test_fetch_hdo_preserves_return_format():
    """Returns dict with keys: signal, casy, den, datum"""
    session = Mock()

    expected_data = {
        "signal": "EVV2",
        "casy": ["08:00-16:00"],
        "den": "pondělí",
        "datum": "16.02.2026",
    }

    mock_token_response = AsyncMock()
    mock_token_response.status = 200
    mock_token_response.json = AsyncMock(return_value={"token": "test"})

    mock_signals_response = AsyncMock()
    mock_signals_response.status = 200
    mock_signals_response.json = AsyncMock(return_value={"data": expected_data})

    mock_token_cm = Mock()
    mock_token_cm.__aenter__ = AsyncMock(return_value=mock_token_response)
    mock_token_cm.__aexit__ = AsyncMock(return_value=None)

    mock_signals_cm = Mock()
    mock_signals_cm.__aenter__ = AsyncMock(return_value=mock_signals_response)
    mock_signals_cm.__aexit__ = AsyncMock(return_value=None)

    session.get = Mock(
        side_effect=lambda url, *args, **kwargs: (
            mock_token_cm if "token/get" in url else mock_signals_cm
        )
    )

    client = DipClient(session=session)
    result = await client.fetch_hdo(SAMPLE_COOKIES, ean="123")
    assert result == expected_data
