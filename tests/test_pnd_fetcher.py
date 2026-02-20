from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from addon.src.main import PND_DATA_URL, PndFetcher, PndFetchError, build_pnd_payload
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
    response.headers = {"content-type": "application/json"}
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
        assert payload["electrometerId"] == ""

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
        assert sent_payload["electrometerId"] == ""

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


class TestFetchOneInContext:

    def _build_mock_context(
        self,
        response_data: dict[str, Any] | None = None,
        status: int = 200,
        content_type: str = "application/json",
    ) -> AsyncMock:
        response = AsyncMock()
        response.status = status
        response.headers = {"content-type": content_type}
        response.json = AsyncMock(return_value=response_data or SAMPLE_RESPONSE)
        response.text = AsyncMock(return_value="<html>error</html>")

        mock_context = AsyncMock()
        mock_context.request.post = AsyncMock(return_value=response)
        return mock_context

    @pytest.mark.asyncio
    async def test_returns_json_data(self) -> None:
        mock_context = self._build_mock_context()
        fetcher = PndFetcher(electrometer_id="784703")

        result = await fetcher._fetch_one_in_context(
            mock_context, "784703", -1003, "20.02.2026 00:00", "20.02.2026 23:59"
        )

        assert result["hasData"] is True
        mock_context.request.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_form_payload_normalization(self) -> None:
        mock_context = self._build_mock_context()
        fetcher = PndFetcher()

        await fetcher._fetch_one_in_context(
            mock_context, None, -1003, "20.02.2026 00:00", "20.02.2026 23:59"
        )

        sent = mock_context.request.post.call_args[1]["data"]
        assert sent["electrometerId"] == ""

    @pytest.mark.asyncio
    async def test_302_raises_session_expired(self) -> None:
        mock_context = self._build_mock_context(status=302)
        fetcher = PndFetcher()

        with pytest.raises(SessionExpiredError):
            await fetcher._fetch_one_in_context(
                mock_context, "784703", -1003, "20.02.2026 00:00", "20.02.2026 23:59"
            )

    @pytest.mark.asyncio
    async def test_500_raises_pnd_fetch_error(self) -> None:
        mock_context = self._build_mock_context(status=500)
        fetcher = PndFetcher()

        with pytest.raises(PndFetchError) as exc_info:
            await fetcher._fetch_one_in_context(
                mock_context, "784703", -1003, "20.02.2026 00:00", "20.02.2026 23:59"
            )

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_non_json_content_type_raises_pnd_fetch_error(self) -> None:
        mock_context = self._build_mock_context(content_type="text/html; charset=UTF-8")
        fetcher = PndFetcher()

        with pytest.raises(PndFetchError) as exc_info:
            await fetcher._fetch_one_in_context(
                mock_context, "784703", -1003, "20.02.2026 00:00", "20.02.2026 23:59"
            )

        assert "non-JSON" in str(exc_info.value)


class TestFetchAll:

    def _build_mocks(
        self,
        response_data: dict[str, Any] | None = None,
    ) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
        response = AsyncMock()
        response.status = 200
        response.headers = {"content-type": "application/json"}
        response.json = AsyncMock(return_value=response_data or SAMPLE_RESPONSE)

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()

        mock_context = AsyncMock()
        mock_context.add_cookies = AsyncMock()
        mock_context.close = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
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

    @pytest.mark.asyncio
    async def test_returns_results_for_all_assemblies(self) -> None:
        mock_async_pw, mock_browser, mock_context = self._build_mocks()
        assembly_configs = [
            {"id": -1003, "name": "profile_all"},
            {"id": -1021, "name": "daily_consumption"},
        ]

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_async_pw
        ):
            fetcher = PndFetcher(electrometer_id="784703")
            results = await fetcher.fetch_all(
                SAMPLE_COOKIES, "784703", assembly_configs
            )

        assert "profile_all" in results
        assert "daily_consumption" in results
        mock_browser.close.assert_called_once()
        mock_context.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_assembly_failure_is_skipped(self) -> None:
        mock_async_pw, _, mock_context = self._build_mocks()

        call_count = 0
        success_response = mock_context.request.post.return_value

        async def post_side_effect(*args: Any, **kwargs: Any) -> AsyncMock:
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise PndFetchError("network error")
            return success_response

        mock_context.request.post.side_effect = post_side_effect

        assembly_configs = [
            {"id": -1003, "name": "profile_all"},
            {"id": -1021, "name": "daily_consumption"},
        ]

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_async_pw
        ):
            fetcher = PndFetcher(electrometer_id="784703")
            results = await fetcher.fetch_all(
                SAMPLE_COOKIES, "784703", assembly_configs
            )

        assert "profile_all" in results
        assert "daily_consumption" not in results

    @pytest.mark.asyncio
    async def test_yesterday_fallback_for_flagged_assembly(self) -> None:
        no_data_response = AsyncMock()
        no_data_response.status = 200
        no_data_response.headers = {"content-type": "application/json"}
        no_data_response.json = AsyncMock(return_value={"hasData": False})

        has_data_response = AsyncMock()
        has_data_response.status = 200
        has_data_response.headers = {"content-type": "application/json"}
        has_data_response.json = AsyncMock(return_value={**SAMPLE_RESPONSE})

        call_count = 0

        async def post_side_effect(*args: Any, **kwargs: Any) -> AsyncMock:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return no_data_response
            return has_data_response

        mock_async_pw, _, mock_context = self._build_mocks()
        mock_context.request.post.side_effect = post_side_effect

        assembly_configs = [
            {"id": -1027, "name": "daily_registers", "fallback_yesterday": True},
        ]

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_async_pw
        ):
            fetcher = PndFetcher(electrometer_id="784703")
            results = await fetcher.fetch_all(
                SAMPLE_COOKIES, "784703", assembly_configs
            )

        assert "daily_registers" in results


class TestPndFetcherErrorPaths:

    @pytest.mark.asyncio
    async def test_fetch_non_json_content_type_raises_pnd_fetch_error(self) -> None:
        mock_pw, _, mock_context = _build_playwright_mocks()
        response = mock_context.request.post.return_value
        response.headers = {"content-type": "text/html; charset=UTF-8"}
        response.text = AsyncMock(return_value="<html>error</html>")

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_pw
        ):
            fetcher = PndFetcher(electrometer_id="784703")
            with pytest.raises(PndFetchError) as exc_info:
                await fetcher.fetch(
                    SAMPLE_COOKIES,
                    assembly_id=-1003,
                    date_from="20.02.2026 00:00",
                    date_to="20.02.2026 23:59",
                )

        assert "non-JSON" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_json_parse_failure_raises_pnd_fetch_error(self) -> None:
        mock_pw, _, mock_context = _build_playwright_mocks()
        response = mock_context.request.post.return_value
        response.headers = {"content-type": "application/json"}
        response.json = AsyncMock(side_effect=ValueError("invalid json"))
        response.text = AsyncMock(return_value="not-json-body")

        with patch(
            "addon.src.main._get_async_playwright", return_value=lambda: mock_pw
        ):
            fetcher = PndFetcher(electrometer_id="784703")
            with pytest.raises(PndFetchError) as exc_info:
                await fetcher.fetch(
                    SAMPLE_COOKIES,
                    assembly_id=-1003,
                    date_from="20.02.2026 00:00",
                    date_to="20.02.2026 23:59",
                )

        assert "JSON parse failed" in str(exc_info.value)
