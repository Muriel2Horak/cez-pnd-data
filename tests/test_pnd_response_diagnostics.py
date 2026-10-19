"""Identify unexpected portal responses without disclosing their contents."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from addon.src.pnd_protocol import (
    PndFetchError,
    ServiceMaintenanceError,
    SessionExpiredError,
    request_data,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "html,category,error",
    [
        ("Právě probíhá odstávka systému", "maintenance", ServiceMaintenanceError),
        ('<input name="username">', "login", SessionExpiredError),
        ("The requested URL was rejected", "portal-protection", PndFetchError),
        ("<html>Unexpected portal page</html>", "unrecognized-html", PndFetchError),
    ],
)
async def test_html_response_logs_only_category_and_metadata(
    html, category, error, caplog
):
    private_content = "private-account@example.com session-secret-value"
    response = SimpleNamespace(
        status=200,
        headers={"content-type": "text/html; charset=utf-8"},
        text=AsyncMock(return_value=f"{html} {private_content}"),
    )
    context = SimpleNamespace(
        request=SimpleNamespace(post=AsyncMock(return_value=response))
    )
    with pytest.raises(error):
        await request_data(context, None, -1003, "today", "today")
    assert f"category: {category}" in caplog.text
    assert "HTTP 200" in caplog.text
    assert "assembly: -1003" in caplog.text
    assert private_content not in caplog.text
    assert html not in caplog.text
