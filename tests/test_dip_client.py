from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from addon.src.dip_client import (
    DipClient,
    DipFetchError,
    DipMaintenanceError,
    DipTokenError,
)


def _mock_page(
    token: str | None = "test-token",
    fetch_result: dict | None = None,
    wait_for_function_error: Exception | None = None,
    goto_error: Exception | None = None,
    evaluate_error: Exception | None = None,
) -> AsyncMock:
    page = AsyncMock()

    if goto_error:
        page.goto = AsyncMock(side_effect=goto_error)
    else:
        page.goto = AsyncMock()

    if wait_for_function_error:
        page.wait_for_function = AsyncMock(side_effect=wait_for_function_error)
    else:
        page.wait_for_function = AsyncMock()

    async def evaluate_side_effect(expr, args=None):
        if evaluate_error:
            raise evaluate_error
        if args is None:
            return token
        return fetch_result or {
            "status": 200,
            "contentType": "application/json",
            "body": '{"data": {"signal": "test"}}',
        }

    page.evaluate = AsyncMock(side_effect=evaluate_side_effect)
    page.close = AsyncMock()
    return page


def _mock_context(page: AsyncMock) -> Mock:
    context = Mock()
    context.new_page = AsyncMock(return_value=page)
    return context


@pytest.mark.asyncio
async def test_fetch_hdo_returns_data_field():
    expected_data = {"signal": "EVV2", "casy": ["08:00-16:00"]}
    page = _mock_page(
        fetch_result={
            "status": 200,
            "contentType": "application/json",
            "body": json.dumps({"data": expected_data}),
        }
    )
    context = _mock_context(page)

    result = await DipClient().fetch_hdo(context, ean="123")

    assert result == expected_data
    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_token_not_found_in_local_storage():
    page = _mock_page(wait_for_function_error=asyncio.TimeoutError())
    context = _mock_context(page)

    with pytest.raises(DipTokenError, match="Token not found in localStorage"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_empty_token():
    page = _mock_page(token="")
    context = _mock_context(page)

    with pytest.raises(DipTokenError, match="Empty dip-request-token"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_raises_maintenance_on_400():
    page = _mock_page(
        fetch_result={"status": 400, "contentType": "application/json", "body": "{}"}
    )
    context = _mock_context(page)

    with pytest.raises(
        DipMaintenanceError, match="Signals endpoint unavailable \\(HTTP 400\\)"
    ):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_raises_maintenance_on_503():
    page = _mock_page(
        fetch_result={"status": 503, "contentType": "application/json", "body": "{}"}
    )
    context = _mock_context(page)

    with pytest.raises(
        DipMaintenanceError, match="Signals endpoint unavailable \\(HTTP 503\\)"
    ):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_raises_fetch_error_on_500():
    page = _mock_page(
        fetch_result={"status": 500, "contentType": "application/json", "body": "{}"}
    )
    context = _mock_context(page)

    with pytest.raises(DipFetchError, match="Signals request failed: HTTP 500"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_raises_maintenance_on_html_content():
    page = _mock_page(
        fetch_result={
            "status": 200,
            "contentType": "text/html; charset=UTF-8",
            "body": "<html>maintenance</html>",
        }
    )
    context = _mock_context(page)

    with pytest.raises(DipMaintenanceError, match="Signals endpoint returned HTML"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_raises_fetch_error_on_missing_data_key():
    page = _mock_page(
        fetch_result={
            "status": 200,
            "contentType": "application/json",
            "body": '{"other": "value"}',
        }
    )
    context = _mock_context(page)

    with pytest.raises(DipFetchError, match="Data missing from response"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_raises_fetch_error_on_goto_timeout():
    page = _mock_page(goto_error=asyncio.TimeoutError())
    context = _mock_context(page)

    with pytest.raises(DipFetchError, match="Fetch failed:"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_raises_fetch_error_on_generic_exception():
    page = _mock_page(evaluate_error=RuntimeError("something went wrong"))
    context = _mock_context(page)

    with pytest.raises(DipFetchError, match="Fetch failed:"):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_page_closed_on_success():
    page = _mock_page()
    context = _mock_context(page)

    await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_page_closed_on_error():
    page = _mock_page(
        fetch_result={"status": 500, "contentType": "application/json", "body": "{}"}
    )
    context = _mock_context(page)

    with pytest.raises(DipFetchError):
        await DipClient().fetch_hdo(context, ean="123")

    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_correct_url_construction():
    page = _mock_page()
    context = _mock_context(page)

    await DipClient().fetch_hdo(context, ean="8591234567890")

    evaluate_calls = page.evaluate.call_args_list
    fetch_call = [c for c in evaluate_calls if len(c.args) > 1][0]
    args = fetch_call.args[1]
    assert "8591234567890" in args["url"]
    assert "signals/8591234567890" in args["url"]
    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_token_used_in_fetch():
    page = _mock_page(token="secret-token-xyz")
    context = _mock_context(page)

    await DipClient().fetch_hdo(context, ean="123")

    evaluate_calls = page.evaluate.call_args_list
    fetch_call = [c for c in evaluate_calls if len(c.args) > 1][0]
    args = fetch_call.args[1]
    assert args["token"] == "secret-token-xyz"
    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_preserves_return_format():
    expected_data = {
        "signal": "EVV2",
        "casy": ["08:00-16:00"],
        "den": "pondeli",
        "datum": "16.02.2026",
    }
    page = _mock_page(
        fetch_result={
            "status": 200,
            "contentType": "application/json",
            "body": json.dumps({"data": expected_data, "extra": "ignored"}),
        }
    )
    context = _mock_context(page)

    result = await DipClient().fetch_hdo(context, ean="123")

    assert result == expected_data
    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_navigates_to_dip_portal():
    page = _mock_page()
    context = _mock_context(page)

    await DipClient().fetch_hdo(context, ean="123")

    page.goto.assert_called_once()
    call_args = page.goto.call_args
    assert "dip.cezdistribuce.cz/irj/portal/prehled-om" in call_args[0][0]
    page.close.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_hdo_waits_for_token_in_local_storage():
    page = _mock_page()
    context = _mock_context(page)

    await DipClient().fetch_hdo(context, ean="123")

    page.wait_for_function.assert_called_once()
    call_args = page.wait_for_function.call_args
    assert "localStorage.getItem('dip-request-token')" in call_args[0][0]
    page.close.assert_called_once()


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


def test_dip_maintenance_error_is_subclass_of_dip_fetch_error():
    assert issubclass(DipMaintenanceError, DipFetchError)
