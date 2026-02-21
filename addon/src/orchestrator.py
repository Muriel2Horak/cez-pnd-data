"""Runtime orchestrator for CEZ PND data polling.

Coordinates:
- 15-minute (configurable) polling scheduler
- Auth session management with automatic re-auth on session expiry
- CEZ data fetching with bounded retry and exponential backoff
- Parsed data publishing to MQTT
- Clear logging for auth failure, CEZ downtime, MQTT downtime
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Union

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext  # type: ignore[import-not-found]

from .auth import ServiceMaintenanceError
from .dip_client import DipMaintenanceError, DipTokenError
from .hdo_parser import parse_hdo_signals
from .parser import CezDataParser

logger = logging.getLogger(__name__)

_PARSER_KEY_TO_SENSOR_KEY: dict[str, str] = {
    "consumption_kw": "consumption",
    "production_kw": "production",
    "reactive_kw": "reactive",
    "reactive_import_inductive_kw": "reactive_import_inductive",
    "reactive_export_capacitive_kw": "reactive_export_capacitive",
    "reactive_export_inductive_kw": "reactive_export_inductive",
    "reactive_import_capacitive_kw": "reactive_import_capacitive",
    "daily_consumption_kwh": "daily_consumption",
    "daily_production_kwh": "daily_production",
    "register_consumption_kwh": "register_consumption",
    "register_production_kwh": "register_production",
    "register_low_tariff_kwh": "register_low_tariff",
    "register_high_tariff_kwh": "register_high_tariff",
}

CEZ_FETCH_ERROR = "CEZ_FETCH_ERROR"
MQTT_PUBLISH_ERROR = "MQTT_PUBLISH_ERROR"
SESSION_EXPIRED = "SESSION_EXPIRED"
NO_DATA_WARNING = "NO_DATA_AVAILABLE"
FETCH_ERROR = "ASSEMBLY_FETCH_ERROR"
HDO_FETCH_ERROR = "HDO_FETCH_ERROR"
HDO_TOKEN_ERROR = "HDO_TOKEN_ERROR"
DIP_MAINTENANCE = "DIP_MAINTENANCE"
PORTAL_MAINTENANCE = "PORTAL_MAINTENANCE"


class SessionExpiredError(Exception):
    """Raised when the CEZ session is expired (e.g. HTTP 401)."""


@dataclass(frozen=True)
class OrchestratorConfig:
    """Runtime configuration for the orchestrator loop."""

    electrometers: list[dict[str, str]]
    poll_interval_seconds: int = 900
    max_retries: int = 3
    retry_base_delay_seconds: float = 5.0
    email: str = ""

    @property
    def poll_interval(self) -> timedelta:
        return timedelta(seconds=self.poll_interval_seconds)

    @property
    def meter_id(self) -> str:
        """Backward compatibility: return first meter_id."""
        if self.electrometers:
            return self.electrometers[0].get("electrometer_id", "unknown")
        return "unknown"

    @property
    def ean(self) -> str:
        """Backward compatibility: return first ean."""
        if self.electrometers:
            return self.electrometers[0].get("ean", "")
        return ""


FetcherCallable = Callable[..., Awaitable[dict[str, Any]]]
HdoFetcherCallable = Callable[..., Awaitable[dict[str, Any]]]

FetcherType = Union[FetcherCallable, Any]

ASSEMBLY_CONFIGS: list[dict[str, Any]] = [
    {"id": -1003, "name": "profile_all"},
    {"id": -1012, "name": "profile_consumption_reactive"},
    {"id": -1011, "name": "profile_production_reactive"},
    {"id": -1021, "name": "daily_consumption"},
    {"id": -1022, "name": "daily_production"},
    {"id": -1027, "name": "daily_registers", "fallback_yesterday": True},
]


class Orchestrator:
    """Coordinates fetch-parse-publish cycles on a polling schedule."""

    def __init__(
        self,
        config: OrchestratorConfig,
        auth_client: Any,
        fetcher: FetcherType,
        mqtt_publisher: Any,
        hdo_fetcher: HdoFetcherCallable | None = None,
    ) -> None:
        self._config = config
        self._auth = auth_client
        self._fetcher: FetcherType = fetcher
        self._hdo_fetcher = hdo_fetcher
        self._mqtt = mqtt_publisher

    async def run_loop(self) -> None:
        """Starts polling loop. Runs until cancelled."""
        logger.info(
            "Orchestrator starting — poll interval: %ds, meter: %s",
            self._config.poll_interval_seconds,
            self._config.meter_id,
        )

        self._mqtt.start()
        self._mqtt.publish_discovery()

        while True:
            await self.run_once()
            await asyncio.sleep(self._config.poll_interval_seconds)

    async def run_once(self) -> None:
        """Execute a single fetch-parse-publish cycle."""
        cycle_start = datetime.now()
        num_electrometers = len(self._config.electrometers)

        try:
            session = await self._auth.ensure_session()
        except ServiceMaintenanceError as e:
            logger.warning("[%s] %s — skipping cycle", PORTAL_MAINTENANCE, e)
            return
        except Exception as e:
            logger.error(
                "[%s] Auth failure — cannot obtain session: %s — skipping cycle",
                SESSION_EXPIRED,
                e,
            )
            logger.debug("Auth failure details:", exc_info=True)
            return

        cookies = session.cookies

        state: dict[str, dict[str, Any]] = {}
        for electrometer in self._config.electrometers:
            meter_id = electrometer.get("electrometer_id", "unknown")
            all_assembly_data = await self._fetch_all_assemblies(cookies, meter_id)
            if not all_assembly_data:
                continue
            for _, assembly_payload in all_assembly_data.items():
                parser = CezDataParser(assembly_payload)
                reading = parser.get_latest_reading_dict()
                if not reading:
                    continue
                reading_meter_id = reading.get("electrometer_id") or meter_id
                if reading_meter_id not in state:
                    state[reading_meter_id] = {}
                for parser_key, value in reading.items():
                    if parser_key == "electrometer_id":
                        continue
                    sensor_key = _PARSER_KEY_TO_SENSOR_KEY.get(parser_key)
                    if sensor_key is not None and value is not None:
                        state[reading_meter_id][sensor_key] = value

        if state:
            try:
                self._mqtt.publish_state(state)
                logger.debug("Published state for %d meter(s)", len(state))
            except Exception:
                logger.error(
                    "[%s] MQTT publish failed — broker may be unavailable",
                    MQTT_PUBLISH_ERROR,
                )
        else:
            logger.info("No data available in CEZ response, skipping PND publish")

        if self._hdo_fetcher:
            if not session.has_live_context:
                logger.warning("Context dead, forcing reauth for HDO fetch")
                try:
                    session = await self._auth.ensure_session()
                except Exception as e:
                    logger.error(
                        "[%s] Re-auth for HDO failed: %s — skipping HDO this cycle",
                        HDO_FETCH_ERROR,
                        e,
                    )
                    session = None  # type: ignore[assignment]

            if session is not None and session.has_live_context:
                context = session.context
                for electrometer in self._config.electrometers:
                    meter_id = electrometer.get("electrometer_id", "unknown")
                    ean = electrometer.get("ean", "")
                    if not ean:
                        continue
                    try:
                        hdo_raw = await self._hdo_fetcher(context, ean)
                        hdo_data = parse_hdo_signals(hdo_raw)
                        self._mqtt.publish_hdo_state(hdo_data, electrometer_id=meter_id)
                    except DipMaintenanceError as e:
                        logger.warning(
                            "[%s] %s for meter %s — skipping HDO this cycle",
                            DIP_MAINTENANCE,
                            e,
                            meter_id,
                        )
                    except DipTokenError as e:
                        logger.error(
                            "[%s] Token acquisition failed for meter %s: %s — PND unaffected",
                            HDO_TOKEN_ERROR,
                            meter_id,
                            e,
                        )
                    except Exception as e:
                        logger.error(
                            "[%s] HDO fetch/parse/publish failed for meter %s: %s — PND unaffected",
                            HDO_FETCH_ERROR,
                            meter_id,
                            e,
                        )
            else:
                logger.warning(
                    "[%s] No live browser context available for HDO — skipping HDO this cycle",
                    HDO_FETCH_ERROR,
                )

        cycle_duration = (datetime.now() - cycle_start).total_seconds()
        logger.info(
            "Poll cycle completed in %.2fs for %d electrometer(s)",
            cycle_duration,
            num_electrometers,
        )

    async def _fetch_assembly(
        self,
        cookies: list[dict[str, Any]],
        meter_id: str,
        assembly_id: int,
        date_from: str,
        date_to: str,
    ) -> dict[str, Any] | None:
        """Fetch a single assembly from PND API."""
        payload = await self._fetcher(
            cookies,
            electrometer_id=meter_id,
            assembly_id=assembly_id,
            date_from=date_from,
            date_to=date_to,
        )
        return payload

    async def _fetch_assembly_with_fallback(
        self,
        cookies: list[dict[str, Any]],
        meter_id: str,
        config: dict[str, Any],
        date_from: str,
        date_to: str,
    ) -> dict[str, Any] | None:
        """Fetch assembly with Tab 17 yesterday fallback."""
        payload = await self._fetch_assembly(
            cookies,
            meter_id,
            config["id"],
            date_from,
            date_to,
        )
        if payload is None:
            return None
        if config.get("fallback_yesterday") and not payload.get("hasData", True):
            logger.warning(
                "[%s] Assembly %s has no data for today, retrying yesterday",
                NO_DATA_WARNING,
                config["name"],
            )
            date_obj = datetime.strptime(date_from.split()[0], "%d.%m.%Y")
            yesterday = date_obj - timedelta(days=1)
            yesterday_from = yesterday.strftime("%d.%m.%Y")
            yesterday_to = date_from
            payload = await self._fetch_assembly(
                cookies, meter_id, config["id"], yesterday_from, yesterday_to
            )
        return payload

    async def _fetch_all_assemblies(
        self,
        cookies: list[dict[str, Any]],
        meter_id: str = "unknown",
    ) -> dict[str, Any]:
        """Fetch all 6 PND assemblies and return merged data."""
        fetcher_obj = getattr(self._fetcher, "__self__", None)
        if fetcher_obj is not None and hasattr(fetcher_obj, "fetch_all"):
            try:
                return await fetcher_obj.fetch_all(cookies, meter_id, ASSEMBLY_CONFIGS)
            except Exception as e:
                logger.error(
                    "[%s] Batch fetch_all failed for meter %s: %s",
                    FETCH_ERROR,
                    meter_id,
                    e,
                )
                return {}

        results = {}
        today = datetime.now()
        date_from = today.strftime("%d.%m.%Y 00:00")
        date_to = today.strftime("%d.%m.%Y 23:59")

        for config in ASSEMBLY_CONFIGS:
            try:
                payload = await self._fetch_assembly_with_fallback(
                    cookies,
                    meter_id,
                    config,
                    date_from,
                    date_to,
                )
                if payload and payload.get("hasData"):
                    results[config["name"]] = payload
                else:
                    logger.warning(
                        "[%s] Assembly %s fetch failed or has no data for meter %s",
                        FETCH_ERROR,
                        config["name"],
                        meter_id,
                    )
            except Exception as e:
                logger.error(
                    "[%s] Assembly %s failed for meter %s: %s — continuing with others",
                    FETCH_ERROR,
                    config["name"],
                    meter_id,
                    e,
                )
        return results

    async def _fetch_with_retry(
        self,
        cookies: Any,
        *,
        _reauthed: bool = False,
    ) -> dict[str, Any] | None:
        """Fetch CEZ data with bounded retry and session-expiry re-auth."""
        last_error: Exception | None = None

        for attempt in range(1, self._config.max_retries + 1):
            try:
                payload = await self._fetcher(cookies)
                return payload

            except SessionExpiredError:
                if _reauthed:
                    logger.error(
                        "[%s] Session still expired after re-auth — aborting cycle",
                        SESSION_EXPIRED,
                    )
                    return None

                logger.warning(
                    "[%s] Session expired — attempting re-authentication",
                    SESSION_EXPIRED,
                )
                try:
                    session = await self._auth.ensure_session()
                    cookies = session.cookies
                except Exception:
                    logger.error(
                        "[%s] Re-authentication failed — aborting cycle",
                        SESSION_EXPIRED,
                    )
                    return None

                return await self._fetch_with_retry(cookies, _reauthed=True)

            except Exception as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    delay = self._config.retry_base_delay_seconds * (2 ** (attempt - 1))
                    logger.warning(
                        "[%s] CEZ fetch failed (attempt %d/%d): %s — retrying in %.1fs",
                        CEZ_FETCH_ERROR,
                        attempt,
                        self._config.max_retries,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)

        logger.error(
            "[%s] CEZ fetch failed after %d attempts: %s — aborting cycle",
            CEZ_FETCH_ERROR,
            self._config.max_retries,
            last_error,
        )
        return None
