"""Test config flow for CEZ PND integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from tests.conftest import (
    AbortFlow,
    FlowResultType,
)

from custom_components.cez_pnd.api_client import AuthenticationError

# The config_flow module will be imported dynamically because it relies
# on mock HA modules registered in conftest.
DOMAIN = "cez_pnd"


def _get_flow(hass):
    """Instantiate the config flow under test."""
    from custom_components.cez_pnd.config_flow import CezPndConfigFlow

    flow = CezPndConfigFlow()
    flow.hass = hass
    return flow


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_flow_user_step_shows_form(hass):
    """First call with no input → show form with username, password, scan_interval."""
    flow = _get_flow(hass)

    result = await flow.async_step_user(user_input=None)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    # Inspect schema keys
    schema = result["data_schema"]
    assert schema is not None
    schema_keys = {str(k) for k in schema.schema}
    assert "username" in schema_keys
    assert "password" in schema_keys
    assert "scan_interval" in schema_keys


@pytest.mark.asyncio
async def test_config_flow_valid_credentials_creates_entry(hass):
    """Successful authenticate → config entry created."""
    flow = _get_flow(hass)

    mock_client = AsyncMock()
    mock_client.authenticate = AsyncMock(return_value="user-123")

    with patch(
        "custom_components.cez_pnd.config_flow.CezPndApiClient",
        return_value=mock_client,
    ), patch(
        "custom_components.cez_pnd.config_flow.async_get_clientsession",
        return_value=MagicMock(),
    ):
        result = await flow.async_step_user(
            user_input={
                "username": "test@example.com",
                "password": "secret",
                "scan_interval": 15,
            }
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "test@example.com"
    assert result["data"]["username"] == "test@example.com"
    assert result["data"]["password"] == "secret"
    assert result["data"]["scan_interval"] == 15


@pytest.mark.asyncio
async def test_config_flow_invalid_credentials_shows_error(hass):
    """AuthenticationError → form re-shown with 'invalid_auth' error."""
    flow = _get_flow(hass)

    mock_client = AsyncMock()
    mock_client.authenticate = AsyncMock(side_effect=AuthenticationError("bad creds"))

    with patch(
        "custom_components.cez_pnd.config_flow.CezPndApiClient",
        return_value=mock_client,
    ), patch(
        "custom_components.cez_pnd.config_flow.async_get_clientsession",
        return_value=MagicMock(),
    ):
        result = await flow.async_step_user(
            user_input={
                "username": "test@example.com",
                "password": "wrong",
                "scan_interval": 15,
            }
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_auth"


@pytest.mark.asyncio
async def test_config_flow_connection_error_shows_error(hass):
    """ClientError (aiohttp) → form re-shown with 'cannot_connect' error."""
    from aiohttp import ClientError

    flow = _get_flow(hass)

    mock_client = AsyncMock()
    mock_client.authenticate = AsyncMock(side_effect=ClientError("timeout"))

    with patch(
        "custom_components.cez_pnd.config_flow.CezPndApiClient",
        return_value=mock_client,
    ), patch(
        "custom_components.cez_pnd.config_flow.async_get_clientsession",
        return_value=MagicMock(),
    ):
        result = await flow.async_step_user(
            user_input={
                "username": "test@example.com",
                "password": "secret",
                "scan_interval": 15,
            }
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"


@pytest.mark.asyncio
async def test_config_flow_duplicate_entry_aborted(hass):
    """Same unique_id already configured → flow aborted."""
    flow = _get_flow(hass)
    # Simulate an existing entry with same unique_id
    flow._existing_unique_ids = {"user-123"}

    mock_client = AsyncMock()
    mock_client.authenticate = AsyncMock(return_value="user-123")

    with patch(
        "custom_components.cez_pnd.config_flow.CezPndApiClient",
        return_value=mock_client,
    ), patch(
        "custom_components.cez_pnd.config_flow.async_get_clientsession",
        return_value=MagicMock(),
    ):
        with pytest.raises(AbortFlow, match="already_configured"):
            await flow.async_step_user(
                user_input={
                    "username": "test@example.com",
                    "password": "secret",
                    "scan_interval": 15,
                }
            )


@pytest.mark.asyncio
async def test_config_flow_scan_interval_default(hass):
    """Form schema default for scan_interval should be 15 minutes."""
    flow = _get_flow(hass)

    result = await flow.async_step_user(user_input=None)

    schema = result["data_schema"]
    # Find the scan_interval key and check its default
    for key in schema.schema:
        if str(key) == "scan_interval":
            assert key.default() == 15
            break
    else:
        pytest.fail("scan_interval not found in schema")


@pytest.mark.asyncio
async def test_config_flow_scan_interval_minimum(hass):
    """Scan interval below 5 minutes should be rejected by voluptuous."""
    flow = _get_flow(hass)

    result = await flow.async_step_user(user_input=None)
    schema = result["data_schema"]

    # Validate that the schema rejects scan_interval < 5
    with pytest.raises(vol.Invalid):
        schema({"username": "a", "password": "b", "scan_interval": 3})

    # Validate that scan_interval = 5 is accepted
    valid = schema({"username": "a", "password": "b", "scan_interval": 5})
    assert valid["scan_interval"] == 5