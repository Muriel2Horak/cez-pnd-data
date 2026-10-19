"""Regression coverage for meter discovery without unselected data requests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from addon.src.auth import _wait_for_login_success
from addon.src.pnd_protocol import (
    PND_DEFINITION_URL,
    PndFetchError,
    ServiceMaintenanceError,
    SessionExpiredError,
    request_meter_ids,
)
from tests.test_functional_fixes import build_orchestrator


def context_with_response(data, status=200, content_type="application/json", text=""):
    response = SimpleNamespace(
        status=status,
        headers={"content-type": content_type},
        json=AsyncMock(return_value=data),
        text=AsyncMock(return_value=text),
    )
    return SimpleNamespace(
        request=SimpleNamespace(get=AsyncMock(return_value=response), post=AsyncMock())
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "meters, expected",
    [
        ([], []),
        ([{"value": "123"}], ["123"]),
        ([{"value": "456"}, {"value": "123"}, {"value": "123"}], ["123", "456"]),
    ],
)
async def test_definition_returns_meter_ids_without_fetching_readings(meters, expected):
    context = context_with_response({"electrometers": meters})
    assert await request_meter_ids(context) == expected
    context.request.get.assert_awaited_once_with(PND_DEFINITION_URL, max_redirects=0)
    context.request.post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {},
        {"electrometers": None},
        {"electrometers": [None]},
        {"electrometers": [{}]},
        {"electrometers": [{"value": " "}]},
        {"electrometers": [{"value": 123}]},
    ],
)
async def test_invalid_definition_is_rejected(data):
    with pytest.raises(PndFetchError):
        await request_meter_ids(context_with_response(data))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 500])
async def test_definition_http_errors(status):
    with pytest.raises(SessionExpiredError if status != 500 else PndFetchError):
        await request_meter_ids(context_with_response({}, status=status))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body, error",
    [
        ('input name="username"', SessionExpiredError),
        ("odstávka", ServiceMaintenanceError),
        ("request rejected", PndFetchError),
    ],
)
async def test_definition_html_is_never_login_proof(body, error):
    with pytest.raises(error):
        await request_meter_ids(
            context_with_response({}, content_type="text/html", text=body)
        )


@pytest.mark.asyncio
async def test_login_succeeds_without_readings_or_assigned_meters():
    page = AsyncMock()
    page.context = context_with_response({"electrometers": []})
    assert await _wait_for_login_success(page) == []
    page.context.request.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_discovery_uses_live_definition_for_reused_session():
    orch, auth, publisher = build_orchestrator(meters=[])
    session = auth.ensure_session.return_value
    session.meter_ids = None
    session.context = context_with_response({"electrometers": [{"value": "123"}]})
    await orch.run_once()
    session.context.request.get.assert_awaited_once()
    publisher.start.assert_called_once()


@pytest.mark.asyncio
async def test_discovery_failure_defers_cycle_until_definition_recovers():
    orch, auth, publisher = build_orchestrator(meters=[])
    auth.ensure_session.return_value.meter_ids = None
    with patch(
        "addon.src.orchestrator.request_meter_ids",
        new=AsyncMock(side_effect=[PndFetchError("HTTP 500", 500), ["123"]]),
    ):
        await orch.run_once()
        publisher.start.assert_not_called()
        await orch.run_once()
    publisher.start.assert_called_once()


@pytest.mark.asyncio
async def test_explicit_meter_does_not_require_auto_discovery():
    orch, auth, publisher = build_orchestrator()
    auth.ensure_session.return_value.meter_ids = ["123", "456"]
    with patch(
        "addon.src.orchestrator.request_meter_ids", new=AsyncMock()
    ) as discovery:
        await orch.run_once()
    discovery.assert_not_awaited()
    publisher.publish_state.assert_called_once()
