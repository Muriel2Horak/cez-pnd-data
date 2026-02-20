from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from addon.src.main import PND_DATA_URL, PndFetchError, PndFetcher, build_pnd_payload
from addon.src.orchestrator import SessionExpiredError

SAMPLE_COOKIES: list[dict[str, Any]] = [
    {
        "name": "JSESSIONID",
        "value": "test-session",
        "domain": ".cezdistribuce.cz",
        "path": "/",
    },
]

SAMPLE_RESPONSE: dict[str, Any] = {
    "hasData": True,
    "columns": [
        {"id": "1000", "name": "Datum", "unit": None},
        {"id": "1001", "name": "+A/784703", "unit": "kW"},
    ],
    "values": [
        {"1000": {"v": "14.02.2026 00:15"}, "1001": {"v": "1,42", "s": 32}},
    ],
}


def _build_playwright_mocks(
    response_data: dict[str, Any] | None = None,
    status: int = 200,
) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
    response = AsyncMock()
    response.status = status
    response.json = AsyncMock(return_value=response_data or SAMPLE_RESPONSE)

    mock_context = AsyncMock()
    mock_context.add_cookies = AsyncMock()
    mock_context.close = AsyncMock()
    mock_context.request.post = AsyncMock(return_value=response)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_pw = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_async_pw = AsyncMock()
    mock_async_pw.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_async_pw.__aexit__ = AsyncMock(return_value=False)

    return mock_async_pw, mock_browser, mock_context


class TestBuildPndPayload:

    def test_builds_correct_payload_structure(self) -> None:
        payload = build_pnd_payload(
            -1003, "14.02.2026 00:00", "14.02.2026 00:00", "784703"
        )
        assert payload == {
            "format": "table",
            "idAssembly": -1003,
            "idDeviceSet": None,
            "intervalFrom": "14.02.2026 00:00",
            "intervalTo": "14.02.2026 00:00",
            "compareFrom": None,
            "opmId": None,
            "electrometerId": "784703",
        }

    def test_none_electrometer_id(self) -> None:
        payload = build_pnd_payload(-1012, "14.02.2026 00:00", "14.02.2026 00:00", None)
        assert payload["electrometerId"] is None

    def test_different_assembly_ids(self) -> None:
        for assembly_id in [-1003, -1012, -1011, -1021, -1022, -1027]:
            payload = build_pnd_payload(
                assembly_id, "01.01.2026 00:00", "01.01.2026 00:00", "123"
            )
            assert payload["idAssembly"] == assembly_id


class TestPndFetcher:

    @pytest.mark.asyncio
    async def test_fetch_posts_to_pnd_url(self) -> None:
        mock_pw, mock_browser, mock_context = _build_playwright_mocks()

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_pw
        ):
            fetcher = PndFetcher(electrometer_id="784703")
            await fetcher.fetch(
                SAMPLE_COOKIES,
                assembly_id=-1003,
                date_from="14.02.2026 00:00",
                date_to="14.02.2026 00:00",
            )

        # WAF warmup + actual form request = 2 calls
        assert mock_context.request.post.call_count == 2
        # First call: WAF warmup (JSON)
        warmup_call = mock_context.request.post.call_args_list[0]
        assert warmup_call[0][0] == PND_DATA_URL
        assert "Content-Type" in warmup_call[1].get("headers", {})
        # Second call: actual form request
        form_call = mock_context.request.post.call_args_list[1]
        assert form_call[0][0] == PND_DATA_URL

    @pytest.mark.asyncio
    async def test_fetch_adds_cookies_to_context(self) -> None:
        mock_pw, mock_browser, mock_context = _build_playwright_mocks()

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_pw
        ):
            fetcher = PndFetcher()
            await fetcher.fetch(
                SAMPLE_COOKIES,
                assembly_id=-1003,
                date_from="14.02.2026 00:00",
                date_to="14.02.2026 00:00",
            )

        mock_context.add_cookies.assert_called_once_with(SAMPLE_COOKIES)

    @pytest.mark.asyncio
    async def test_fetch_returns_parsed_json(self) -> None:
        mock_pw, _, _ = _build_playwright_mocks()

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_pw
        ):
            fetcher = PndFetcher(electrometer_id="784703")
            result = await fetcher.fetch(
                SAMPLE_COOKIES,
                assembly_id=-1003,
                date_from="14.02.2026 00:00",
                date_to="14.02.2026 00:00",
            )

        assert result == SAMPLE_RESPONSE
        assert result["hasData"] is True

    @pytest.mark.asyncio
    async def test_fetch_sends_correct_payload(self) -> None:
        mock_pw, _, mock_context = _build_playwright_mocks()

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_pw
        ):
            fetcher = PndFetcher(electrometer_id="784703")
            await fetcher.fetch(
                SAMPLE_COOKIES,
                assembly_id=-1021,
                date_from="15.02.2026 00:00",
                date_to="15.02.2026 00:00",
            )

        call_kwargs = mock_context.request.post.call_args[1]
        sent_payload = call_kwargs["data"]
        assert sent_payload["idAssembly"] == -1021
        assert sent_payload["intervalFrom"] == "15.02.2026 00:00"
        assert sent_payload["electrometerId"] == "784703"

    @pytest.mark.asyncio
    async def test_browser_closed_after_success(self) -> None:
        mock_pw, mock_browser, mock_context = _build_playwright_mocks()

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_pw
        ):
            fetcher = PndFetcher()
            await fetcher.fetch(
                SAMPLE_COOKIES,
                assembly_id=-1003,
                date_from="14.02.2026 00:00",
                date_to="14.02.2026 00:00",
            )

        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_browser_closed_after_error(self) -> None:
        mock_pw, mock_browser, mock_context = _build_playwright_mocks()
        mock_context.request.post = AsyncMock(
            side_effect=ConnectionError("Network error")
        )

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_pw
        ):
            fetcher = PndFetcher()
            with pytest.raises(ConnectionError):
                await fetcher.fetch(
                    SAMPLE_COOKIES,
                    assembly_id=-1003,
                    date_from="14.02.2026 00:00",
                    date_to="14.02.2026 00:00",
                )

        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_electrometer_id_passed_in_payload(self) -> None:
        mock_pw, _, mock_context = _build_playwright_mocks()

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_pw
        ):
            fetcher = PndFetcher(electrometer_id="999999")
            await fetcher.fetch(
                SAMPLE_COOKIES,
                assembly_id=-1003,
                date_from="14.02.2026 00:00",
                date_to="14.02.2026 00:00",
            )

        sent_payload = mock_context.request.post.call_args[1]["data"]
        assert sent_payload["electrometerId"] == "999999"

    @pytest.mark.asyncio
    async def test_no_electrometer_id_sends_none(self) -> None:
        mock_pw, _, mock_context = _build_playwright_mocks()

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_pw
        ):
            fetcher = PndFetcher()
            await fetcher.fetch(
                SAMPLE_COOKIES,
                assembly_id=-1003,
                date_from="14.02.2026 00:00",
                date_to="14.02.2026 00:00",
            )

        sent_payload = mock_context.request.post.call_args[1]["data"]
        assert sent_payload["electrometerId"] is None

    @pytest.mark.asyncio
    async def test_302_redirect_raises_session_expired_error(self) -> None:
        mock_pw, mock_browser, mock_context = _build_playwright_mocks(status=302)

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_pw
        ):
            fetcher = PndFetcher()
            with pytest.raises(SessionExpiredError) as exc_info:
                await fetcher.fetch(
                    SAMPLE_COOKIES,
                    assembly_id=-1003,
                    date_from="14.02.2026 00:00",
                    date_to="14.02.2026 00:00",
                )

        assert "302" in str(exc_info.value)
        assert "session expired" in str(exc_info.value).lower()
        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_500_error_raises_pnd_fetch_error(self) -> None:
        mock_pw, mock_browser, mock_context = _build_playwright_mocks(status=500)

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_pw
        ):
            fetcher = PndFetcher()
            with pytest.raises(PndFetchError) as exc_info:
                await fetcher.fetch(
                    SAMPLE_COOKIES,
                    assembly_id=-1003,
                    date_from="14.02.2026 00:00",
                    date_to="14.02.2026 00:00",
                )

        assert exc_info.value.status_code == 500
        assert "500" in str(exc_info.value)
        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_403_error_raises_pnd_fetch_error(self) -> None:
        mock_pw, mock_browser, mock_context = _build_playwright_mocks(status=403)

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_pw
        ):
            fetcher = PndFetcher()
            with pytest.raises(PndFetchError) as exc_info:
                await fetcher.fetch(
                    SAMPLE_COOKIES,
                    assembly_id=-1003,
                    date_from="14.02.2026 00:00",
                    date_to="14.02.2026 00:00",
                )

        assert exc_info.value.status_code == 403
        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()
