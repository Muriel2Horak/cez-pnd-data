"""Data update coordinator for CEZ PND integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from aiohttp import ClientError

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_client import AuthenticationError, CezPndApiClient, PndMeterData
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 15


class CezPndDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):

    def __init__(
        self,
        hass,
        config_entry,
        client: CezPndApiClient,
    ) -> None:
        self.client = client
        scan_interval = config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        electrometer_id = self.config_entry.data.get("electrometer_id")
        try:
            profile_data = await self.client.fetch_meter_data(
                electrometer_id=electrometer_id,
                assembly_id=-1003,
            )
            register_data = await self.client.fetch_meter_data(
                electrometer_id=electrometer_id,
                assembly_id=-1027,
            )
            return self._process_data(profile_data, register_data)
        except AuthenticationError:
            try:
                await self.client.authenticate()
                profile_data = await self.client.fetch_meter_data(
                    electrometer_id=electrometer_id,
                    assembly_id=-1003,
                )
                register_data = await self.client.fetch_meter_data(
                    electrometer_id=electrometer_id,
                    assembly_id=-1027,
                )
                return self._process_data(profile_data, register_data)
            except AuthenticationError as err:
                raise ConfigEntryAuthFailed from err
        except ClientError as err:
            raise UpdateFailed(f"Network error: {err}") from err

    @staticmethod
    def _process_data(
        profile_data: PndMeterData,
        register_data: PndMeterData,
    ) -> dict[str, Any]:
        latest_profile = profile_data.readings[-1] if profile_data.readings else None
        latest_register = register_data.readings[-1] if register_data.readings else None
        return {
            "consumption_power_kw": latest_profile.consumption_kw if latest_profile else None,
            "production_power_kw": latest_profile.production_kw if latest_profile else None,
            "reactive_power_kw": latest_profile.reactive_kw if latest_profile else None,
            "consumption_total_kwh": latest_register.consumption_kw if latest_register else None,
            "production_total_kwh": latest_register.production_kw if latest_register else None,
            "reactive_total_kvarh": latest_register.reactive_kw if latest_register else None,
            "last_reading_time": latest_profile.timestamp if latest_profile else None,
            "reading_status": latest_profile.status_text if latest_profile else "unknown",
        }