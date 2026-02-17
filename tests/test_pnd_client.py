# Testy pro PndClient
import asyncio
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from addon.src.auth import DEFAULT_USER_AGENT
from addon.src.cookie_utils import playwright_cookies_to_header
from addon.src.orchestrator import SessionExpiredError
from addon.src.pnd_client import PndClient, PndFetchError


@pytest.mark.asyncio
async def test_fetch_data_builds_correct_payload():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    # Create mock response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"hasData": True})

    # Create async context manager mock
    mock_post_cm = AsyncMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    # Set session.post to return the context manager
    session.post = Mock(return_value=mock_post_cm)

    result = await client.fetch_data(
        cookies,
        assembly_id=-1003,
        date_from="16.02.2026 00:00",
        date_to="16.02.2026 00:00",
    )

    call_kwargs = session.post.call_args.kwargs
    payload = call_kwargs["json"]
    assert payload["format"] == "table"
    assert payload["idAssembly"] == -1003
    assert payload["electrometerId"] == "784703"
    assert payload["idDeviceSet"] is None
    assert payload["compareFrom"] is None
    assert payload["opmId"] is None


@pytest.mark.asyncio
async def test_fetch_data_sends_post_to_correct_url():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"hasData": True})

    mock_post_cm = AsyncMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    await client.fetch_data(
        cookies,
        assembly_id=-1003,
        date_from="16.02.2026 00:00",
        date_to="16.02.2026 00:00",
    )

    session.post.assert_called_once()
    call_args = session.post.call_args
    assert "https://pnd.cezdistribuce.cz/cezpnd2/external/data" in str(call_args)


@pytest.mark.asyncio
async def test_fetch_data_converts_playwright_cookies():
    cookies = [
        {"name": "JSESSIONID", "value": "abc123"},
        {"name": "test", "value": "456"},
    ]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"hasData": True})

    mock_post_cm = AsyncMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    await client.fetch_data(
        cookies,
        assembly_id=-1003,
        date_from="16.02.2026 00:00",
        date_to="16.02.2026 00:00",
    )

    call_kwargs = session.post.call_args.kwargs
    headers = call_kwargs["headers"]
    assert headers["Cookie"] == "JSESSIONID=abc123; test=456"


@pytest.mark.asyncio
async def test_fetch_data_returns_json_response():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    expected = {"hasData": True, "columns": [], "values": []}
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=expected)

    mock_post_cm = AsyncMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    result = await client.fetch_data(
        cookies,
        assembly_id=-1003,
        date_from="16.02.2026 00:00",
        date_to="16.02.2026 00:00",
    )
    assert result == expected


@pytest.mark.asyncio
async def test_fetch_data_raises_session_expired_on_401():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    mock_response = AsyncMock()
    mock_response.status = 401

    mock_post_cm = AsyncMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    with pytest.raises(SessionExpiredError):
        await client.fetch_data(
            cookies,
            assembly_id=-1003,
            date_from="16.02.2026 00:00",
            date_to="16.02.2026 00:00",
        )


@pytest.mark.asyncio
async def test_fetch_data_raises_on_non_200():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    mock_response = AsyncMock()
    mock_response.status = 500

    mock_post_cm = Mock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    with pytest.raises(PndFetchError, match="PND API returned 500"):
        await client.fetch_data(
            cookies,
            assembly_id=-1003,
            date_from="16.02.2026 00:00",
            date_to="16.02.2026 00:00",
        )


@pytest.mark.asyncio
async def test_fetch_data_raises_on_timeout():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    # Create context manager that raises timeout on enter
    mock_post_cm = Mock()
    mock_post_cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    with pytest.raises(PndFetchError):
        await client.fetch_data(
            cookies,
            assembly_id=-1003,
            date_from="16.02.2026 00:00",
            date_to="16.02.2026 00:00",
        )


@pytest.mark.asyncio
async def test_fetch_data_raises_on_connection_error():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    # Create context manager that raises connection error on enter
    mock_post_cm = Mock()
    mock_post_cm.__aenter__ = AsyncMock(
        side_effect=aiohttp.ClientConnectorError(Mock(), Mock())
    )
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    with pytest.raises(PndFetchError):
        await client.fetch_data(
            cookies,
            assembly_id=-1003,
            date_from="16.02.2026 00:00",
            date_to="16.02.2026 00:00",
        )


@pytest.mark.asyncio
async def test_fetch_data_raises_on_invalid_json():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(side_effect=ValueError("Invalid JSON"))

    mock_post_cm = Mock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    with pytest.raises(PndFetchError):
        await client.fetch_data(
            cookies,
            assembly_id=-1003,
            date_from="16.02.2026 00:00",
            date_to="16.02.2026 00:00",
        )


def test_constructor_stores_electrometer_id():
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)
    assert client._electrometer_id == "784703"


@pytest.mark.asyncio
async def test_fetch_data_uses_stored_electrometer_id():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="123456", session=session)

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"hasData": True})

    mock_post_cm = AsyncMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    await client.fetch_data(
        cookies,
        assembly_id=-1003,
        date_from="16.02.2026 00:00",
        date_to="16.02.2026 00:00",
    )

    call_kwargs = session.post.call_args.kwargs
    payload = call_kwargs["json"]
    assert payload["electrometerId"] == "123456"


@pytest.mark.asyncio
async def test_fetch_data_handles_has_data_false():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    expected = {"hasData": False, "columns": [], "values": []}
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=expected)

    mock_post_cm = AsyncMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    result = await client.fetch_data(
        cookies,
        assembly_id=-1003,
        date_from="16.02.2026 00:00",
        date_to="16.02.2026 00:00",
    )
    assert result == expected


@pytest.mark.asyncio
async def test_fetch_data_passes_assembly_id_kwarg():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"hasData": True})

    mock_post_cm = AsyncMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    await client.fetch_data(
        cookies,
        assembly_id=-1003,
        date_from="16.02.2026 00:00",
        date_to="16.02.2026 00:00",
    )

    call_kwargs = session.post.call_args.kwargs
    payload = call_kwargs["json"]
    assert payload["idAssembly"] == -1003


@pytest.mark.asyncio
async def test_fetch_data_passes_date_from_kwargs():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"hasData": True})

    mock_post_cm = AsyncMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    await client.fetch_data(
        cookies,
        assembly_id=-1003,
        date_from="16.02.2026 00:00",
        date_to="16.02.2026 00:00",
    )

    call_kwargs = session.post.call_args.kwargs
    payload = call_kwargs["json"]
    assert payload["intervalFrom"] == "16.02.2026 00:00"


@pytest.mark.asyncio
async def test_fetch_data_passes_date_to_kwargs():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"hasData": True})

    mock_post_cm = AsyncMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    await client.fetch_data(
        cookies,
        assembly_id=-1003,
        date_from="16.02.2026 00:00",
        date_to="16.02.2026 23:59",
    )

    call_kwargs = session.post.call_args.kwargs
    payload = call_kwargs["json"]
    assert payload["intervalTo"] == "16.02.2026 23:59"


@pytest.mark.asyncio
async def test_content_type_is_application_json():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"hasData": True})

    mock_post_cm = AsyncMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    await client.fetch_data(
        cookies,
        assembly_id=-1003,
        date_from="16.02.2026 00:00",
        date_to="16.02.2026 00:00",
    )

    call_kwargs = session.post.call_args.kwargs
    headers = call_kwargs["headers"]
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_uses_chrome_user_agent():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"hasData": True})

    mock_post_cm = AsyncMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    await client.fetch_data(
        cookies,
        assembly_id=-1003,
        date_from="16.02.2026 00:00",
        date_to="16.02.2026 00:00",
    )

    call_kwargs = session.post.call_args.kwargs
    headers = call_kwargs["headers"]
    assert headers["User-Agent"] == DEFAULT_USER_AGENT


@pytest.mark.asyncio
async def test_uses_injected_session():
    cookies = [{"name": "test", "value": "123"}]
    session = AsyncMock()
    client = PndClient(electrometer_id="784703", session=session)

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"hasData": True})

    mock_post_cm = AsyncMock()
    mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_cm.__aexit__ = AsyncMock(return_value=None)

    session.post = Mock(return_value=mock_post_cm)

    await client.fetch_data(
        cookies,
        assembly_id=-1003,
        date_from="16.02.2026 00:00",
        date_to="16.02.2026 00:00",
    )

    # Verify injected session was used
    session.post.assert_called_once()
