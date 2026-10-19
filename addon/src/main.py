"""Main entry point for CEZ PND Home Assistant Add-on.

Reads configuration from environment variables and starts the orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from .auth import (
    DEFAULT_USER_AGENT,
    PND_BASE_URL,
    PlaywrightAuthClient,
    ServiceMaintenanceError,
)
from .blocking import run_blocking
from .dip_client import DipClient
from .mqtt_client import MQTTClientWrapper
from .mqtt_config import resolve_mqtt_config
from .mqtt_publisher import MqttPublisher
from .orchestrator import Orchestrator, OrchestratorConfig, SessionExpiredError
from .pnd_protocol import PND_DATA_URL
from .pnd_protocol import PndFetchError as PndFetchError
from .pnd_protocol import build_pnd_payload, request_data
from .session_manager import CredentialsProvider, SessionStore

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _get_async_playwright():  # type: ignore[no-untyped-def]
    from playwright.async_api import async_playwright  # type: ignore[import-not-found]

    return async_playwright


class PndFetcher:
    def __init__(self, electrometer_id: Optional[str] = None) -> None:
        self._electrometer_id = electrometer_id

    @staticmethod
    async def _create_browser_context(browser: Any) -> Any:
        return await browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            locale="cs-CZ",
            timezone_id="Europe/Prague",
            viewport={"width": 1280, "height": 720},
        )

    async def fetch(
        self,
        cookies: list,
        *,
        assembly_id: int,
        date_from: str,
        date_to: str,
        electrometer_id: str | None = None,
    ) -> Dict[str, Any]:
        async_playwright = _get_async_playwright()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = None
            try:
                context = await self._create_browser_context(browser)
                await context.add_cookies(cookies)

                # Navigate to PND dashboard to establish WAF fingerprint (same as live_verify_flow.py)
                logger.debug("Navigating to PND dashboard for WAF fingerprint...")
                try:
                    page = await context.new_page()
                    await page.goto(
                        PND_BASE_URL,
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                    await page.close()
                    await asyncio.sleep(3)
                except Exception as e:
                    logger.debug("PND dashboard navigation failed (non-fatal): %s", e)

                effective_electrometer_id = electrometer_id or self._electrometer_id

                payload = build_pnd_payload(
                    assembly_id,
                    date_from,
                    date_to,
                    effective_electrometer_id,
                )
                form_payload = {k: ("" if v is None else v) for k, v in payload.items()}

                # WAF warmup: Send JSON request first (will fail with 400, but sets WAF cookies/state)
                logger.debug("WAF warmup (JSON request)...")
                try:
                    warmup_response = await context.request.post(
                        PND_DATA_URL,
                        data=json.dumps(form_payload),
                        headers={"Content-Type": "application/json"},
                    )
                    logger.debug(
                        "Warmup status: %d (expected 400)", warmup_response.status
                    )
                except Exception as e:
                    logger.debug("Warmup failed: %s (expected)", e)

                await asyncio.sleep(1)

                return await self._fetch_one_in_context(
                    context, effective_electrometer_id, assembly_id, date_from, date_to
                )
            finally:
                try:
                    if context is not None:
                        await context.close()
                finally:
                    await browser.close()

    async def fetch_all(
        self,
        cookies: list,
        meter_id: str,
        assembly_configs: list,
        *,
        request_runner: Any = None,
    ) -> Dict[str, Any]:
        """Fetch all assemblies in a single browser context per cycle.

        Creates ONE Playwright browser for all assemblies. Navigates to PND base
        URL first to establish WAF state, then does a single WAF warmup POST before
        iterating through all assembly fetches in the same context.

        Handles Tab 17 (daily_registers) yesterday-fallback internally.

        Returns a dict mapping assembly name → payload for assemblies with data.
        """
        today = datetime.now(ZoneInfo("Europe/Prague"))
        date_from = today.strftime("%d.%m.%Y 00:00")
        date_to = today.strftime("%d.%m.%Y 23:59")

        async_playwright = _get_async_playwright()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = None
            try:
                context = await self._create_browser_context(browser)
                await context.add_cookies(cookies)

                # Navigate to PND base URL to establish browser history / WAF fingerprint
                logger.debug("Navigating to PND base URL for WAF fingerprint...")
                try:
                    page = await context.new_page()
                    await page.goto(
                        PND_BASE_URL, wait_until="domcontentloaded", timeout=30_000
                    )
                    await page.close()
                except Exception as e:
                    logger.debug("PND navigation warmup failed (non-fatal): %s", e)

                # Single WAF warmup POST using the first assembly
                first_config = assembly_configs[0]
                warmup_payload = build_pnd_payload(
                    first_config["id"],
                    date_from,
                    date_to,
                    meter_id,
                )
                logger.debug("WAF warmup (JSON request for all assemblies)...")
                try:
                    warmup_response = await context.request.post(
                        PND_DATA_URL,
                        data=json.dumps(warmup_payload),
                        headers={"Content-Type": "application/json"},
                    )
                    logger.debug(
                        "Warmup status: %d (expected 400)", warmup_response.status
                    )
                except Exception as e:
                    logger.debug("Warmup POST failed: %s (expected)", e)

                await asyncio.sleep(1)

                context_cookies = cookies

                async def fetch_one(assembly_id, start, end):
                    async def operation(current_cookies):
                        nonlocal context_cookies
                        if current_cookies != context_cookies:
                            await context.clear_cookies()
                            await context.add_cookies(current_cookies)
                            context_cookies = current_cookies
                        return await self._fetch_one_in_context(
                            context, meter_id, assembly_id, start, end
                        )

                    if request_runner is not None:
                        return await request_runner(operation)
                    return await operation(cookies)

                results: Dict[str, Any] = {}

                for config in assembly_configs:
                    assembly_id: int = config["id"]
                    assembly_name: str = config["name"]

                    try:
                        payload = await fetch_one(assembly_id, date_from, date_to)
                    except (SessionExpiredError, ServiceMaintenanceError):
                        raise
                    except Exception as e:
                        logger.error(
                            "Assembly %s failed for meter %s: %s — continuing",
                            assembly_name,
                            meter_id,
                            e,
                        )
                        continue

                    if config.get("fallback_yesterday") and not payload.get(
                        "hasData", True
                    ):
                        logger.warning(
                            "Assembly %s has no data for today, retrying yesterday",
                            assembly_name,
                        )
                        date_obj = today - timedelta(days=1)
                        yesterday_from = date_obj.strftime("%d.%m.%Y 00:00")
                        try:
                            payload = await fetch_one(
                                assembly_id, yesterday_from, date_from
                            )
                        except (SessionExpiredError, ServiceMaintenanceError):
                            raise
                        except Exception as e:
                            logger.error(
                                "Assembly %s yesterday-fallback failed for meter %s: %s",
                                assembly_name,
                                meter_id,
                                e,
                            )
                            continue

                    if payload and payload.get("hasData"):
                        results[assembly_name] = payload
                    else:
                        logger.warning(
                            "Assembly %s has no data for meter %s",
                            assembly_name,
                            meter_id,
                        )

                return results

            finally:
                try:
                    if context is not None:
                        await context.close()
                finally:
                    await browser.close()

    async def _fetch_one_in_context(
        self,
        context: Any,
        meter_id: Optional[str],
        assembly_id: int,
        date_from: str,
        date_to: str,
    ) -> Dict[str, Any]:
        return await request_data(context, meter_id, assembly_id, date_from, date_to)


def validate_electrometers_config(
    electrometers_json: Optional[str],
) -> List[Dict[str, str]]:
    if not electrometers_json:
        return []

    try:
        electrometers = json.loads(electrometers_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in electrometers configuration: {e}")

    if not isinstance(electrometers, list):
        raise ValueError("Electrometers configuration must be a JSON array")

    seen_electrometer_ids = set()
    seen_eans = set()

    for i, electrometer in enumerate(electrometers):
        if not isinstance(electrometer, dict):
            raise ValueError(f"Electrometer {i} must be an object")

        if "electrometer_id" not in electrometer:
            raise ValueError(
                f"Electrometer {i} missing required field 'electrometer_id'"
            )
        if "ean" not in electrometer:
            raise ValueError(f"Electrometer {i} missing required field 'ean'")

        electrometer_id = electrometer["electrometer_id"]
        ean = electrometer["ean"]

        if not isinstance(electrometer_id, str) or not electrometer_id.strip():
            raise ValueError(f"Electrometer {i} has empty or invalid 'electrometer_id'")
        if not isinstance(ean, str) or not ean.strip():
            raise ValueError(f"Electrometer {i} has empty or invalid 'ean'")

        if electrometer_id in seen_electrometer_ids:
            raise ValueError(f"Duplicate electrometer_id: {electrometer_id}")
        if ean in seen_eans:
            raise ValueError(f"Duplicate ean: {ean}")

        seen_electrometer_ids.add(electrometer_id)
        seen_eans.add(ean)

    return electrometers


def read_env_var(name: str, required: bool = True) -> Optional[str]:
    """Read environment variable with validation."""
    value = os.getenv(name)
    if required and not value:
        logger.error(f"Required environment variable {name} is not set")
        sys.exit(1)
    return value


def create_config(mqtt_config: Optional[dict] = None) -> Dict[str, Dict[str, Any]]:
    """Create configuration dictionary from environment variables."""
    credentials = CredentialsProvider().get_credentials()
    config: Dict[str, Dict[str, Any]] = {
        "cez": {
            "email": credentials.email,
            "password": credentials.password,
            "electrometer_id": read_env_var("CEZ_ELECTROMETER_ID", required=False)
            or "auto",
            "ean": read_env_var("CEZ_EAN", required=False) or "",
        },
        "mqtt": (
            mqtt_config
            if mqtt_config is not None
            else {
                "host": read_env_var("MQTT_HOST"),
                "port": int(read_env_var("MQTT_PORT", required=False) or "1883"),
                "username": read_env_var("MQTT_USER", required=False) or "",
                "password": read_env_var("MQTT_PASSWORD", required=False) or "",
            }
        ),
    }

    electrometers_json = read_env_var("CEZ_ELECTROMETERS", required=False)
    try:
        electrometers = validate_electrometers_config(electrometers_json)

        # If CEZ_ELECTROMETERS is provided, use it as the canonical list
        if electrometers:
            config["cez"]["electrometers"] = electrometers
        else:
            # Fall back to single electrometer_id/ean pair for backward compatibility
            electrometer_id = read_env_var("CEZ_ELECTROMETER_ID", required=False)
            ean = read_env_var("CEZ_EAN", required=False)

            if electrometer_id == "auto":
                electrometer_id = None
            if electrometer_id and ean:
                config["cez"]["electrometers"] = [
                    {"electrometer_id": electrometer_id, "ean": ean}
                ]
            elif electrometer_id:
                # Only electrometer_id provided, ean will be empty
                config["cez"]["electrometers"] = [
                    {"electrometer_id": electrometer_id, "ean": ""}
                ]
            else:
                # No electrometers configured - this should fail validation elsewhere
                config["cez"]["electrometers"] = []

    except ValueError as e:
        logger.error(f"Invalid electrometers configuration: {e}")
        sys.exit(1)

    if config["cez"]["electrometer_id"] == "auto":
        config["cez"]["electrometer_id"] = None

    return config


async def run_until_shutdown(
    work, shutdown_event, cleanup, timeout=10, on_timeout=None
):
    """Cancel polling and start cleanup immediately within one grace period.

    Native worker threads cannot be killed by task cancellation. MQTT waits use
    cooperative stop signals and daemon workers; the application also supplies
    a final process-exit callback if a third-party cleanup ignores cancellation.
    """
    task = asyncio.create_task(work())
    stop = asyncio.create_task(shutdown_event.wait())

    def observe_completion(future):
        if not future.cancelled():
            error = future.exception()
            if error is not None:
                logger.error("Shutdown task failed: %s", error)

    try:
        done, _ = await asyncio.wait({task, stop}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
    finally:
        task.cancel()
        stop.cancel()
        # Cleanup gets its own task immediately, even when polling is still
        # unwinding a cancelled browser operation. Both share one deadline.
        closing = asyncio.create_task(cleanup())
        done, pending = await asyncio.wait({task, stop, closing}, timeout=timeout)
        for future in done:
            observe_completion(future)
        if pending:
            logger.error("Shutdown cleanup exceeded %.2f seconds", timeout)
            for future in pending:
                future.add_done_callback(observe_completion)
                future.cancel()
            if on_timeout is not None:
                on_timeout()


async def main():
    """Start through a signal-aware lifecycle, including configuration lookup."""
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def signal_handler(signum):
        """Log shutdown signals and notify the managed lifecycle."""
        logger.info("Received signal %s, shutting down...", signum)
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler, sig)
    auth_client = PlaywrightAuthClient(CredentialsProvider(), SessionStore())
    mqtt_publisher = None

    async def work():
        nonlocal mqtt_publisher
        config = create_config(await resolve_mqtt_config())
        logger.info("Starting CEZ PND add-on")
        logger.info("Email: %s", config["cez"]["email"])
        logger.info(
            "Electrometer ID: %s",
            config["cez"].get("electrometer_id") or "auto-detect",
        )
        electrometers = config["cez"]["electrometers"]
        if electrometers:
            logger.info("Configured electrometers: %d", len(electrometers))
            for i, electrometer in enumerate(electrometers, 1):
                raw_ean = electrometer.get("ean", "")
                if raw_ean and len(raw_ean) > 4:
                    ean_display = "*" * (len(raw_ean) - 4) + raw_ean[-4:]
                else:
                    ean_display = raw_ean or "empty"
                logger.info(
                    "  %d. electrometer_id: %s, ean: %s",
                    i,
                    electrometer["electrometer_id"],
                    ean_display,
                )
        else:
            logger.info("No electrometers configured — automatic detection enabled")
        logger.info("MQTT Host: %s:%s", config["mqtt"]["host"], config["mqtt"]["port"])
        mqtt_publisher = MqttPublisher(
            MQTTClientWrapper(**config["mqtt"]),
            electrometers=config["cez"]["electrometers"],
        )
        fetcher = PndFetcher()
        orchestrator = Orchestrator(
            config=OrchestratorConfig(
                electrometers=config["cez"]["electrometers"],
                email=config["cez"]["email"],
                auto_ean=config["cez"]["ean"],
            ),
            auth_client=auth_client,
            fetcher=fetcher.fetch,
            batch_fetcher=fetcher.fetch_all,
            mqtt_publisher=mqtt_publisher,
            hdo_fetcher=DipClient().fetch_hdo,
        )
        try:
            await orchestrator.run_loop()
        except asyncio.CancelledError:
            logger.info("Orchestrator cancelled")
            raise

    async def cleanup():
        logger.info("Shutting down...")
        if mqtt_publisher is not None:
            mqtt_publisher.begin_shutdown()
        try:
            await auth_client.close()
        finally:
            if mqtt_publisher is not None:
                await run_blocking(mqtt_publisher.stop)

    try:
        await run_until_shutdown(
            work, shutdown_event, cleanup, on_timeout=lambda: os._exit(1)
        )
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error("Fatal error: %s", e)
        sys.exit(1)
