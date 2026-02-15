"""Tests for CezPndDataUpdateCoordinator."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.cez_pnd.api_client import (
    AuthenticationError,
    CezPndApiClient,
    PndMeterData,
    PndMeterReading,
)


def _make_config_entry(
    scan_interval: int = 15,
    electrometer_id: str = "784703",
) -> MagicMock:
    """Create a mock ConfigEntry."""
    entry = MagicMock()
    entry.data = {
        "username": "test@example.com",
        "password": "secret",
        "scan_interval": scan_interval,
        "electrometer_id": electrometer_id,
    }
    entry.entry_id = "test-entry-id"
    return entry


def _make_profile_data(
    consumption: float = 1.5,
    production: float = 0.3,
    reactive: float = 0.1,
    status: int = 1,
    status_text: str = "Platný",
    timestamp: datetime | None = None,
) -> PndMeterData:
    """Create mock profile data (assembly -1003)."""
    if timestamp is None:
        timestamp = datetime(2025, 1, 15, 14, 30)
    return PndMeterData(
        has_data=True,
        size=1,
        readings=[
            PndMeterReading(
                timestamp=timestamp,
                consumption_kw=consumption,
                production_kw=production,
                reactive_kw=reactive,
                status=status,
                status_text=status_text,
            )
        ],
        columns=[],
    )


def _make_register_data(
    consumption_kwh: float = 12345.678,
    production_kwh: float = 678.9,
    reactive_kvarh: float = 42.0,
) -> PndMeterData:
    """Create mock register data (assembly -1027).

    Register data uses the same PndMeterData structure but values
    represent cumulative kWh readings rather than instantaneous kW.
    """
    return PndMeterData(
        has_data=True,
        size=1,
        readings=[
            PndMeterReading(
                timestamp=datetime(2025, 1, 15, 0, 0),
                consumption_kw=consumption_kwh,
                production_kw=production_kwh,
                reactive_kw=reactive_kvarh,
                status=1,
                status_text="Platný",
            )
        ],
        columns=[],
    )


def _make_empty_data() -> PndMeterData:
    """Create mock data with hasData=false and no readings."""
    return PndMeterData(
        has_data=False,
        size=0,
        readings=[],
        columns=[],
    )


def _make_client(
    profile_data: PndMeterData | None = None,
    register_data: PndMeterData | None = None,
) -> AsyncMock:
    """Create a mock API client with configurable responses."""
    client = AsyncMock(spec=CezPndApiClient)

    if profile_data is None:
        profile_data = _make_profile_data()
    if register_data is None:
        register_data = _make_register_data()

    async def _fetch_side_effect(electrometer_id, assembly_id=-1003, **kw):
        if assembly_id == -1003:
            return profile_data
        elif assembly_id == -1027:
            return register_data
        raise ValueError(f"Unexpected assembly_id: {assembly_id}")

    client.fetch_meter_data = AsyncMock(side_effect=_fetch_side_effect)
    client.authenticate = AsyncMock(return_value="test@example.com")
    return client


def _make_coordinator(hass, config_entry=None, client=None):
    """Instantiate the coordinator under test."""
    from custom_components.cez_pnd.coordinator import CezPndDataUpdateCoordinator

    if config_entry is None:
        config_entry = _make_config_entry()
    if client is None:
        client = _make_client()

    return CezPndDataUpdateCoordinator(hass, config_entry, client)


@pytest.mark.asyncio
async def test_coordinator_fetches_data_on_interval(hass):
    """_async_update_data calls client.fetch_meter_data for both assemblies."""
    client = _make_client()
    coordinator = _make_coordinator(hass, client=client)

    await coordinator._async_update_data()

    assert client.fetch_meter_data.call_count == 2

    calls = client.fetch_meter_data.call_args_list
    call_kwargs = [call.kwargs for call in calls]
    electrometer_ids = {kw.get("electrometer_id") for kw in call_kwargs}
    assert "784703" in electrometer_ids


@pytest.mark.asyncio
async def test_coordinator_returns_parsed_data(hass):
    """coordinator.data contains consumption, production, reactive values."""
    profile_data = _make_profile_data(
        consumption=2.5, production=0.8, reactive=0.15,
    )
    register_data = _make_register_data(
        consumption_kwh=12345.678, production_kwh=678.9, reactive_kvarh=42.0,
    )
    client = _make_client(profile_data=profile_data, register_data=register_data)
    coordinator = _make_coordinator(hass, client=client)

    result = await coordinator._async_update_data()

    assert result["consumption_power_kw"] == 2.5
    assert result["production_power_kw"] == 0.8
    assert result["reactive_power_kw"] == 0.15

    assert result["consumption_total_kwh"] == 12345.678
    assert result["production_total_kwh"] == 678.9
    assert result["reactive_total_kvarh"] == 42.0

    assert result["last_reading_time"] == datetime(2025, 1, 15, 14, 30)
    assert result["reading_status"] == "Platný"


@pytest.mark.asyncio
async def test_coordinator_handles_auth_error_with_reauth(hass):
    """AuthenticationError on first fetch → silent reauth → retry succeeds."""
    profile_data = _make_profile_data(consumption=1.0)
    register_data = _make_register_data()

    client = AsyncMock(spec=CezPndApiClient)
    client.authenticate = AsyncMock(return_value="test@example.com")

    call_count = {"value": 0}

    async def _fetch_with_auth_error(electrometer_id, assembly_id=-1003, **kw):
        call_count["value"] += 1
        if call_count["value"] <= 1:
            raise AuthenticationError("Session expired")
        if assembly_id == -1003:
            return profile_data
        return register_data

    client.fetch_meter_data = AsyncMock(side_effect=_fetch_with_auth_error)
    coordinator = _make_coordinator(hass, client=client)

    result = await coordinator._async_update_data()

    client.authenticate.assert_called_once()
    assert result["consumption_power_kw"] == 1.0


@pytest.mark.asyncio
async def test_coordinator_raises_config_entry_auth_failed_on_persistent_auth_error(hass):
    """Reauth also fails → ConfigEntryAuthFailed."""
    from homeassistant.exceptions import ConfigEntryAuthFailed

    client = AsyncMock(spec=CezPndApiClient)
    client.fetch_meter_data = AsyncMock(
        side_effect=AuthenticationError("Session expired")
    )
    client.authenticate = AsyncMock(
        side_effect=AuthenticationError("Bad credentials")
    )

    coordinator = _make_coordinator(hass, client=client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_coordinator_raises_update_failed_on_network_error(hass):
    """ClientError → UpdateFailed (not ConfigEntryAuthFailed)."""
    from aiohttp import ClientError
    from homeassistant.helpers.update_coordinator import UpdateFailed

    client = AsyncMock(spec=CezPndApiClient)
    client.fetch_meter_data = AsyncMock(
        side_effect=ClientError("Connection timeout")
    )

    coordinator = _make_coordinator(hass, client=client)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_coordinator_calculates_cumulative_kwh(hass):
    """Register data (-1027) provides cumulative kWh for Energy Dashboard."""
    register_data = _make_register_data(
        consumption_kwh=99999.123,
        production_kwh=5555.456,
        reactive_kvarh=111.789,
    )
    client = _make_client(register_data=register_data)
    coordinator = _make_coordinator(hass, client=client)

    result = await coordinator._async_update_data()

    assert result["consumption_total_kwh"] == 99999.123
    assert result["production_total_kwh"] == 5555.456
    assert result["reactive_total_kvarh"] == 111.789


@pytest.mark.asyncio
async def test_coordinator_handles_empty_data(hass):
    """hasData=false → coordinator.data has None/zero values."""
    empty_profile = _make_empty_data()
    empty_register = _make_empty_data()
    client = _make_client(profile_data=empty_profile, register_data=empty_register)
    coordinator = _make_coordinator(hass, client=client)

    result = await coordinator._async_update_data()

    assert result["consumption_power_kw"] is None
    assert result["production_power_kw"] is None
    assert result["reactive_power_kw"] is None
    assert result["consumption_total_kwh"] is None
    assert result["production_total_kwh"] is None
    assert result["reactive_total_kvarh"] is None
    assert result["last_reading_time"] is None
    assert result["reading_status"] == "unknown"


@pytest.mark.asyncio
async def test_coordinator_uses_configured_scan_interval(hass):
    """Update interval matches config entry's scan_interval."""
    config_entry = _make_config_entry(scan_interval=30)
    coordinator = _make_coordinator(hass, config_entry=config_entry)

    assert coordinator.update_interval == timedelta(minutes=30)


@pytest.mark.asyncio
async def test_coordinator_uses_default_scan_interval(hass):
    """When scan_interval not in config, default to 15 minutes."""
    config_entry = MagicMock()
    config_entry.data = {
        "username": "test@example.com",
        "password": "secret",
        "electrometer_id": "784703",
    }
    config_entry.entry_id = "test-entry-id"
    coordinator = _make_coordinator(hass, config_entry=config_entry)

    assert coordinator.update_interval == timedelta(minutes=15)