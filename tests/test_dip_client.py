from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from addon.src.dip_client import (
    DipClient,
    DipFetchError,
    DipMaintenanceError,
    DipTokenError,
)
from addon.src.main import PlaywrightHdoFetcher


def _mock_response(
    status: int = 200,
    json_data: dict | None = None,
    content_type: str = "application/json",
) -> AsyncMock:
    response = AsyncMock()
    response.status = status
    response.headers = Mock()
    response.headers.get = Mock(return_value=content_type)
    if json_data is not None:
        response.json = AsyncMock(return_value=json_data)
    return response


def _mock_context(
    token_response: AsyncMock, signals_response: AsyncMock | None = None
) -> Mock:
    request = Mock()

    async def get_side_effect(url, **kwargs):
        if "token/get" in url:
            return token_response
        if signals_response is not None:
            return signals_response
        raise ValueError(f"Unexpected URL: {url}")

    request.get = AsyncMock(side_effect=get_side_effect)
    context = Mock()
    context.request = request
    return context


@pytest.mark.asyncio
async def test_fetch_hdo_gets_token_first():
    token_resp = _mock_response(json_data={"token": "test-token-123"})
    signals_resp = _mock_response(json_data={"data": {"signal": "test"}})
    context = _mock_context(token_resp, signals_resp)

    await DipClient().fetch_hdo(context, ean="1234567890123")

    token_calls = [
        c for c in context.request.get.call_args_list if "token/get" in str(c)
    ]
    assert len(token_calls) == 1


@pytest.mark.asyncio
async def test_fetch_hdo_uses_token_in_signals_request():
    token_resp = _mock_response(json_data={"token": "test-token-456"})
    signals_resp = _mock_response(json_data={"data": {"signal": "test"}})

    request = Mock()
    call_count = [0]

    async def get_side_effect(url, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return token_resp
        headers = kwargs.get("headers", {})
        assert "x-request-token" in headers
        assert headers["x-request-token"] == "test-token-456"
        return signals_resp

    request.get = AsyncMock(side_effect=get_side_effect)
    context = Mock()
    context.request = request

    await DipClient().fetch_hdo(context, ean="1234567890123")


@pytest.mark.asyncio
async def test_fetch_hdo_sends_correct_signals_url():
    token_resp = _mock_response(json_data={"token": "test-token-789"})
    signals_resp = _mock_response(json_data={"data": {"signal": "test"}})
    context = _mock_context(token_resp, signals_resp)

    await DipClient().fetch_hdo(context, ean="1234567890123")

    signals_calls = [
        c for c in context.request.get.call_args_list if "signals/" in str(c)
    ]
    assert len(signals_calls) == 1
    url_arg = signals_calls[0][0][0]
    assert "1234567890123" in url_arg


@pytest.mark.asyncio
async def test_fetch_hdo_returns_data_field():
    expected_data = {"signal": "EVV2", "casy": ["08:00-16:00"]}
    token_resp = _mock_response(json_data={"token": "test"})
    signals_resp = _mock_response(json_data={"data": expected_data, "other": "ignored"})
    context = _mock_context(token_resp, signals_resp)

    result = await DipClient().fetch_hdo(context, ean="123")
    assert result == expected_data


@pytest.mark.asyncio
async def test_fetch_hdo_raises_dip_token_error_on_token_401():
    token_resp = _mock_response(status=401)
    context = _mock_context(token_resp)

    with pytest.raises(DipTokenError, match="Token request failed: HTTP 401"):
        await DipClient().fetch_hdo(context, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_dip_token_error_on_missing_token():
    token_resp = _mock_response(json_data={"other": "data"})
    context = _mock_context(token_resp)

    with pytest.raises(DipTokenError, match="Token missing from response"):
        await DipClient().fetch_hdo(context, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_dip_fetch_error_on_signals_failure():
    token_resp = _mock_response(json_data={"token": "test"})
    signals_resp = _mock_response(status=500)
    context = _mock_context(token_resp, signals_resp)

    with pytest.raises(DipFetchError, match="Signals request failed: HTTP 500"):
        await DipClient().fetch_hdo(context, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_dip_fetch_error_on_missing_data():
    token_resp = _mock_response(json_data={"token": "test"})
    signals_resp = _mock_response(json_data={"other": "data"})
    context = _mock_context(token_resp, signals_resp)

    with pytest.raises(DipFetchError, match="Data missing from response"):
        await DipClient().fetch_hdo(context, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_on_timeout():
    request = Mock()
    request.get = AsyncMock(side_effect=asyncio.TimeoutError())
    context = Mock()
    context.request = request

    with pytest.raises(DipFetchError):
        await DipClient().fetch_hdo(context, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_on_exception():
    request = Mock()
    request.get = AsyncMock(side_effect=Exception("network error"))
    context = Mock()
    context.request = request

    with pytest.raises(DipFetchError):
        await DipClient().fetch_hdo(context, ean="123")


def test_is_html_content_type_detects_html():
    assert DipClient._is_html_content_type("text/html") is True
    assert DipClient._is_html_content_type("text/html; charset=UTF-8") is True
    assert DipClient._is_html_content_type("TEXT/HTML") is True
    assert DipClient._is_html_content_type("application/xhtml+xml") is False


def test_is_html_content_type_rejects_json():
    assert DipClient._is_html_content_type("application/json") is False
    assert DipClient._is_html_content_type("application/json; charset=utf-8") is False


def test_is_html_content_type_handles_none():
    assert DipClient._is_html_content_type(None) is False


@pytest.mark.asyncio
async def test_fetch_hdo_raises_maintenance_on_html_token_response():
    token_resp = _mock_response(status=200, content_type="text/html; charset=UTF-8")
    context = _mock_context(token_resp)

    with pytest.raises(
        DipMaintenanceError, match=r"Token endpoint returned HTML \(maintenance page\)"
    ):
        await DipClient().fetch_hdo(context, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_maintenance_on_html_signals_response():
    token_resp = _mock_response(json_data={"token": "test-token"})
    signals_resp = _mock_response(status=200, content_type="text/html; charset=UTF-8")
    context = _mock_context(token_resp, signals_resp)

    with pytest.raises(
        DipMaintenanceError, match=r"Signals endpoint returned HTML \(maintenance page\)"
    ):
        await DipClient().fetch_hdo(context, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_maintenance_on_400_token():
    token_resp = _mock_response(status=400)
    context = _mock_context(token_resp)

    with pytest.raises(
        DipMaintenanceError, match=r"Token endpoint unavailable \(HTTP 400\)"
    ):
        await DipClient().fetch_hdo(context, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_maintenance_on_503_token():
    token_resp = _mock_response(status=503)
    context = _mock_context(token_resp)

    with pytest.raises(
        DipMaintenanceError, match=r"Token endpoint unavailable \(HTTP 503\)"
    ):
        await DipClient().fetch_hdo(context, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_maintenance_on_400_signals():
    token_resp = _mock_response(json_data={"token": "test-token"})
    signals_resp = _mock_response(status=400)
    context = _mock_context(token_resp, signals_resp)

    with pytest.raises(
        DipMaintenanceError, match=r"Signals endpoint unavailable \(HTTP 400\)"
    ):
        await DipClient().fetch_hdo(context, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_raises_maintenance_on_503_signals():
    token_resp = _mock_response(json_data={"token": "test-token"})
    signals_resp = _mock_response(status=503)
    context = _mock_context(token_resp, signals_resp)

    with pytest.raises(
        DipMaintenanceError, match=r"Signals endpoint unavailable \(HTTP 503\)"
    ):
        await DipClient().fetch_hdo(context, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_non_maintenance_error_uses_dip_fetch_error():
    token_resp = _mock_response(json_data={"token": "test-token"})
    signals_resp = _mock_response(status=500)
    context = _mock_context(token_resp, signals_resp)

    with pytest.raises(DipFetchError, match="Signals request failed: HTTP 500"):
        await DipClient().fetch_hdo(context, ean="123")


@pytest.mark.asyncio
async def test_fetch_hdo_preserves_return_format():
    expected_data = {
        "signal": "EVV2",
        "casy": ["08:00-16:00"],
        "den": "pondeli",
        "datum": "16.02.2026",
    }
    token_resp = _mock_response(json_data={"token": "test"})
    signals_resp = _mock_response(json_data={"data": expected_data})
    context = _mock_context(token_resp, signals_resp)

    result = await DipClient().fetch_hdo(context, ean="123")
    assert result == expected_data


def test_dip_maintenance_error_is_subclass_of_dip_fetch_error():
    assert issubclass(DipMaintenanceError, DipFetchError)


def _build_hdo_playwright_mocks(hdo_result: dict) -> tuple:
    mock_context = AsyncMock()
    mock_context.add_cookies = AsyncMock()
    mock_context.close = AsyncMock()

    mock_browser = AsyncMock()
    mock_browser.close = AsyncMock()

    mock_pw = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_async_pw = AsyncMock()
    mock_async_pw.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_async_pw.__aexit__ = AsyncMock(return_value=False)

    return mock_async_pw, mock_browser, mock_context, hdo_result


@pytest.mark.asyncio
async def test_playwright_hdo_fetcher_returns_dip_result():
    expected = {"signal": "EVV2", "casy": ["08:00-16:00"]}
    mock_async_pw, mock_browser, mock_context, _ = _build_hdo_playwright_mocks(expected)

    with (
        patch(
            "addon.src.main._get_async_playwright",
            return_value=lambda: mock_async_pw,
        ),
        patch(
            "addon.src.main.PndFetcher._create_browser_context",
            new=AsyncMock(return_value=mock_context),
        ),
        patch.object(DipClient, "fetch_hdo", new=AsyncMock(return_value=expected)),
    ):
        result = await PlaywrightHdoFetcher().fetch(cookies=[{"name": "x"}], ean="123")

    assert result == expected


@pytest.mark.asyncio
async def test_playwright_hdo_fetcher_adds_cookies_to_context():
    cookies = [{"name": "JSESSIONID", "value": "sess", "domain": ".cez.cz", "path": "/"}]
    mock_async_pw, mock_browser, mock_context, _ = _build_hdo_playwright_mocks({})

    with (
        patch(
            "addon.src.main._get_async_playwright",
            return_value=lambda: mock_async_pw,
        ),
        patch(
            "addon.src.main.PndFetcher._create_browser_context",
            new=AsyncMock(return_value=mock_context),
        ),
        patch.object(DipClient, "fetch_hdo", new=AsyncMock(return_value={})),
    ):
        await PlaywrightHdoFetcher().fetch(cookies=cookies, ean="123")

    mock_context.add_cookies.assert_called_once_with(cookies)
