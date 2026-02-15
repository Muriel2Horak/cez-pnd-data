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
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Awaitable, Callable

from .parser import CezDataParser

logger = logging.getLogger(__name__)

# ── Error type sentinels for structured logging ──────────────────────

CEZ_FETCH_ERROR = "CEZ_FETCH_ERROR"
MQTT_PUBLISH_ERROR = "MQTT_PUBLISH_ERROR"
SESSION_EXPIRED_ERROR = "SESSION_EXPIRED_ERROR"


# ── Custom exceptions ────────────────────────────────────────────────


class SessionExpiredError(Exception):
    """Raised when the CEZ session is expired (e.g. HTTP 401)."""


# ── Configuration ────────────────────────────────────────────────────


@dataclass(frozen=True)
class OrchestratorConfig:
    """Runtime configuration for the orchestrator loop."""

    meter_id: str
    poll_interval_seconds: int = 900  # 15 minutes
    max_retries: int = 3
    retry_base_delay_seconds: float = 5.0

    @property
    def poll_interval(self) -> timedelta:
        return timedelta(seconds=self.poll_interval_seconds)


# ── Orchestrator ─────────────────────────────────────────────────────

# Type alias for the async fetcher callable:
#   (cookies) -> dict  (raw CEZ API payload)
FetcherCallable = Callable[..., Awaitable[dict[str, Any]]]


class Orchestrator:
    """Coordinates fetch-parse-publish cycles on a polling schedule.

    Integrates:
    - PlaywrightAuthClient (Task 3) for session management
    - CezDataParser (Task 4) for data parsing
    - MqttPublisher (Task 5) for HA MQTT Discovery + state
    """

    def __init__(
        self,
        config: OrchestratorConfig,
        auth_client: Any,
        fetcher: FetcherCallable,
        mqtt_publisher: Any,
    ) -> None:
        self._config = config
        self._auth = auth_client
        self._fetcher = fetcher
        self._mqtt = mqtt_publisher

    # ── Public API ────────────────────────────────────────────────

    async def run_loop(self) -> None:
        """Start the polling loop. Runs until cancelled.

        On first iteration, publishes MQTT discovery.
        """
        logger.info(
            "Orchestrator starting — poll interval: %ds, meter: %s",
            self._config.poll_interval_seconds,
            self._config.meter_id,
        )

        # Startup: MQTT lifecycle
        self._mqtt.start()
        self._mqtt.publish_discovery()

        while True:
            await self.run_once()
            await asyncio.sleep(self._config.poll_interval_seconds)

    async def run_once(self) -> None:
        """Execute a single fetch-parse-publish cycle.

        Handles:
        - Auth failures (logs and aborts cycle)
        - Session expiry (re-auths once, retries fetch)
        - Transient fetch failures (bounded retry with backoff)
        - MQTT publish failures (logs, does not crash)
        """
        # 1. Authenticate
        try:
            session = await self._auth.ensure_session()
        except Exception:
            logger.error(
                "[%s] Auth failure — cannot obtain session, skipping cycle",
                SESSION_EXPIRED_ERROR,
            )
            return

        cookies = session.cookies

        # 2. Fetch data with retry logic
        payload = await self._fetch_with_retry(cookies)
        if payload is None:
            return  # Already logged

        # 3. Parse
        parser = CezDataParser(payload)
        reading = parser.get_latest_reading_dict()
        if reading is None:
            logger.info("No data available in CEZ response, skipping publish")
            return

        # 4. Publish to MQTT
        state = {
            "consumption": reading.get("consumption_kw"),
            "production": reading.get("production_kw"),
            "reactive": reading.get("reactive_kw"),
        }

        try:
            self._mqtt.publish_state(state)
            logger.debug("Published state for meter %s", self._config.meter_id)
        except Exception:
            logger.error(
                "[%s] MQTT publish failed — broker may be unavailable",
                MQTT_PUBLISH_ERROR,
            )

    # ── Internal helpers ──────────────────────────────────────────

    async def _fetch_with_retry(
        self,
        cookies: Any,
        *,
        _reauthed: bool = False,
    ) -> dict[str, Any] | None:
        """Fetch CEZ data with bounded retry and session-expiry re-auth.

        On SessionExpiredError:
          - Re-authenticate once, then retry the fetch.
          - If re-auth also fails, abort the cycle.

        On transient errors (ConnectionError, etc.):
          - Retry up to max_retries with exponential backoff.
        """
        last_error: Exception | None = None

        for attempt in range(1, self._config.max_retries + 1):
            try:
                payload = await self._fetcher(cookies)
                return payload

            except SessionExpiredError:
                if _reauthed:
                    logger.error(
                        "[%s] Session still expired after re-auth — aborting cycle",
                        SESSION_EXPIRED_ERROR,
                    )
                    return None

                logger.warning(
                    "[%s] Session expired — attempting re-authentication",
                    SESSION_EXPIRED_ERROR,
                )
                try:
                    session = await self._auth.ensure_session()
                    cookies = session.cookies
                except Exception:
                    logger.error(
                        "[%s] Re-authentication failed — aborting cycle",
                        SESSION_EXPIRED_ERROR,
                    )
                    return None

                # Retry fetch with new cookies (recursion with flag)
                return await self._fetch_with_retry(
                    cookies, _reauthed=True
                )

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
