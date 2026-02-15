"""Tests for CEZ PND integration __init__.py (async_setup_entry / async_unload_entry)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aiohttp import ClientError

from custom_components.cez_pnd.api_client import (
    AuthenticationError,
    CezPndApiClient,
    PndMeterData,
    PndMeterReading,
)
from custom_components.cez_pnd.const import DOMAIN

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config_entry(
    username: str = "test@example.com",
    password: str = "secret",
    scan_interval: int = 15,
    electrometer_id: str = "784703",
) -> MagicMock:
    """Create a mock ConfigEntry."""
    entry = MagicMock()
    entry.data = {
        "username": username,
        "password": password,
        "scan_interval": scan_interval,
        "electrometer_id": electrometer_id,
    }
    entry.entry_id = "test-entry-id"
    return entry


def _make_profile_data() -> PndMeterData:
    return PndMeterData(
        has_data=True,
        size=1,
        readings=[
            PndMeterReading(
                timestamp=datetime(2025, 1, 15, 14, 30),
                consumption_kw=1.5,
                production_kw=0.3,
                reactive_kw=0.1,
                status=1,
                status_text="Platný",
            )
        ],
        columns=[],
    )


def _make_register_data() -> PndMeterData:
    return PndMeterData(
        has_data=True,
        size=1,
        readings=[
            PndMeterReading(
                timestamp=datetime(2025, 1, 15, 0, 0),
                consumption_kw=12345.678,
                production_kw=678.9,
                reactive_kw=42.0,
                status=1,
                status_text="Platný",
            )
        ],
        columns=[],
    )


def _make_client() -> AsyncMock:
    """Create a mock API client that authenticates successfully."""
    client = AsyncMock(spec=CezPndApiClient)
    client.authenticate = AsyncMock(return_value="test@example.com")

    profile = _make_profile_data()
    register = _make_register_data()

    async def _fetch(electrometer_id, assembly_id=-1003, **kw):
        if assembly_id == -1003:
            return profile
        return register

    client.fetch_meter_data = AsyncMock(side_effect=_fetch)
    return client


def _make_hass() -> MagicMock:
    """Create a mock HomeAssistant instance with data dict."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_setup_entry_authenticates_and_creates_coordinator():
    """Mock successful auth, assert coordinator created and stored in hass.data."""
    from custom_components.cez_pnd import async_setup_entry

    hass = _make_hass()
    entry = _make_config_entry()
    mock_client = _make_client()

    with patch(
        "custom_components.cez_pnd.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.cez_pnd.CezPndApiClient",
        return_value=mock_client,
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True
    mock_client.authenticate.assert_called_once()
    # Coordinator must be stored in hass.data[DOMAIN][entry.entry_id]
    assert DOMAIN in hass.data
    assert entry.entry_id in hass.data[DOMAIN]
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.client is mock_client


@pytest.mark.asyncio
async def test_async_setup_entry_auth_failed_raises_config_entry_auth_failed():
    """Mock AuthenticationError, assert ConfigEntryAuthFailed raised."""
    from homeassistant.exceptions import ConfigEntryAuthFailed
    from custom_components.cez_pnd import async_setup_entry

    hass = _make_hass()
    entry = _make_config_entry()
    mock_client = AsyncMock(spec=CezPndApiClient)
    mock_client.authenticate = AsyncMock(
        side_effect=AuthenticationError("bad credentials")
    )

    with patch(
        "custom_components.cez_pnd.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.cez_pnd.CezPndApiClient",
        return_value=mock_client,
    ):
        with pytest.raises(ConfigEntryAuthFailed):
            await async_setup_entry(hass, entry)


@pytest.mark.asyncio
async def test_async_setup_entry_network_error_raises_config_entry_not_ready():
    """Mock ClientError, assert ConfigEntryNotReady raised."""
    from homeassistant.exceptions import ConfigEntryNotReady
    from custom_components.cez_pnd import async_setup_entry

    hass = _make_hass()
    entry = _make_config_entry()
    mock_client = AsyncMock(spec=CezPndApiClient)
    mock_client.authenticate = AsyncMock(
        side_effect=ClientError("connection refused")
    )

    with patch(
        "custom_components.cez_pnd.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.cez_pnd.CezPndApiClient",
        return_value=mock_client,
    ):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)


@pytest.mark.asyncio
async def test_async_setup_entry_initial_refresh_succeeds():
    """Assert async_config_entry_first_refresh called during setup."""
    from custom_components.cez_pnd import async_setup_entry

    hass = _make_hass()
    entry = _make_config_entry()
    mock_client = _make_client()

    mock_coordinator = MagicMock()
    mock_coordinator.client = mock_client
    mock_coordinator.async_config_entry_first_refresh = AsyncMock()

    with patch(
        "custom_components.cez_pnd.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.cez_pnd.CezPndApiClient",
        return_value=mock_client,
    ), patch(
        "custom_components.cez_pnd.CezPndDataUpdateCoordinator",
        return_value=mock_coordinator,
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True
    mock_coordinator.async_config_entry_first_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_async_unload_entry_cleans_up():
    """Assert hass.data entry removed on unload."""
    from custom_components.cez_pnd import async_unload_entry

    hass = _make_hass()
    entry = _make_config_entry()

    # Pre-populate hass.data as if setup_entry ran
    hass.data[DOMAIN] = {entry.entry_id: MagicMock()}

    result = await async_unload_entry(hass, entry)

    assert result is True
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_config_flow_creates_entry_and_forward_platforms():
    """Mock successful config, assert platforms setup via forward_entry_setups."""
    from custom_components.cez_pnd import async_setup_entry

    hass = _make_hass()
    entry = _make_config_entry()
    mock_client = _make_client()

    with patch(
        "custom_components.cez_pnd.async_get_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.cez_pnd.CezPndApiClient",
        return_value=mock_client,
    ):
        result = await async_setup_entry(hass, entry)

    assert result is True
    # async_forward_entry_setups should have been called with the entry and PLATFORMS
    hass.config_entries.async_forward_entry_setups.assert_called_once()
    call_args = hass.config_entries.async_forward_entry_setups.call_args
    assert call_args[0][0] is entry
    # Second arg should be the platforms list containing Platform.SENSOR
    platforms = call_args[0][1]
    assert "sensor" in platforms
