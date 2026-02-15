"""Tests for the runtime orchestrator — TDD RED phase.

Covers:
- 15-minute polling scheduler (configurable)
- Transient failure retry with bounded backoff
- Session-expired (401) re-auth flow
- MQTT unavailability recovery
- Clear logging on auth failure, CEZ downtime, MQTT downtime
- Integration of auth, parser, and MQTT publisher modules
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from addon.src.orchestrator import (
    CEZ_FETCH_ERROR,
    MQTT_PUBLISH_ERROR,
    SESSION_EXPIRED_ERROR,
    Orchestrator,
    OrchestratorConfig,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _make_reading_dict(consumption: float = 1.42) -> dict[str, Any]:
    """Build a parser-compatible latest reading dict."""
    return {
        "timestamp": "2026-02-14T00:15:00",
        "consumption_kw": consumption,
        "production_kw": 0.0,
        "reactive_kw": 5.46,
        "electrometer_id": "784703",
    }


def _make_config(**overrides: Any) -> OrchestratorConfig:
    """Build an OrchestratorConfig with sensible test defaults."""
    defaults = {
        "poll_interval_seconds": 900,  # 15 min
        "max_retries": 3,
        "retry_base_delay_seconds": 0.01,  # Fast for tests
        "meter_id": "784703",
    }
    defaults.update(overrides)
    return OrchestratorConfig(**defaults)


class FakeAuthClient:
    """Stub for PlaywrightAuthClient."""

    def __init__(self, cookies: list[dict[str, Any]] | None = None) -> None:
        self._cookies = cookies or [{"name": "JSESSIONID", "value": "abc"}]
        self.ensure_session = AsyncMock(
            return_value=MagicMock(cookies=self._cookies, reused=True)
        )


class FakeFetcher:
    """Stub for the CEZ data fetcher callable."""

    def __init__(self, payload: dict | None = None) -> None:
        self._payload = payload or {
            "hasData": True,
            "columns": [
                {"id": "1000", "name": "Datum", "unit": None},
                {"id": "1001", "name": "+A/784703", "unit": "kW"},
                {"id": "1002", "name": "-A/784703", "unit": "kW"},
                {"id": "1003", "name": "Rv/784703", "unit": "kW"},
            ],
            "values": [
                {
                    "1000": {"v": "14.02.2026 00:15"},
                    "1001": {"v": "1,42", "s": 32},
                    "1002": {"v": "0,0", "s": 32},
                    "1003": {"v": "5,46", "s": 32},
                },
            ],
        }
        self.fetch = AsyncMock(return_value=self._payload)


class FakeMqttPublisher:
    """Stub for MqttPublisher."""

    def __init__(self) -> None:
        self.start = MagicMock()
        self.stop = MagicMock()
        self.publish_discovery = MagicMock()
        self.publish_state = MagicMock()


# ===========================================================================
# 1. OrchestratorConfig defaults
# ===========================================================================


class TestOrchestratorConfig:
    """OrchestratorConfig provides sensible defaults."""

    def test_default_poll_interval_is_15_minutes(self) -> None:
        config = OrchestratorConfig(meter_id="123")
        assert config.poll_interval_seconds == 900

    def test_default_max_retries(self) -> None:
        config = OrchestratorConfig(meter_id="123")
        assert config.max_retries == 3

    def test_custom_poll_interval(self) -> None:
        config = OrchestratorConfig(meter_id="123", poll_interval_seconds=300)
        assert config.poll_interval_seconds == 300

    def test_poll_interval_as_timedelta(self) -> None:
        config = OrchestratorConfig(meter_id="123")
        assert config.poll_interval == timedelta(seconds=900)


# ===========================================================================
# 2. Single fetch cycle (happy path)
# ===========================================================================


class TestSingleCycle:
    """Orchestrator executes one fetch-parse-publish cycle."""

    @pytest.mark.asyncio
    async def test_single_cycle_fetches_parses_publishes(self) -> None:
        auth = FakeAuthClient()
        fetcher = FakeFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config()

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        # Auth was consulted
        auth.ensure_session.assert_awaited_once()
        # Fetcher was called with cookies
        fetcher.fetch.assert_awaited_once()
        # MQTT state was published
        mqtt.publish_state.assert_called_once()
        state_arg = mqtt.publish_state.call_args[0][0]
        assert "consumption" in state_arg
        assert state_arg["consumption"] == 1.42

    @pytest.mark.asyncio
    async def test_single_cycle_skips_publish_when_no_data(self) -> None:
        auth = FakeAuthClient()
        fetcher = FakeFetcher(
            payload={"hasData": False, "columns": [], "values": []}
        )
        mqtt = FakeMqttPublisher()
        config = _make_config()

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        mqtt.publish_state.assert_not_called()


# ===========================================================================
# 3. Session expiry triggers re-auth
# ===========================================================================


class TestSessionExpiry:
    """On 401/session-expired, orchestrator re-authenticates and retries."""

    @pytest.mark.asyncio
    async def test_session_expired_triggers_reauth_and_retry(self) -> None:
        """Simulated 401 triggers re-auth once, then second fetch succeeds."""
        auth = FakeAuthClient()
        fetcher = FakeFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config()

        call_count = 0

        async def fetch_with_expiry(cookies: Any) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SessionExpiredError("Session expired (401)")
            return fetcher._payload

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetch_with_expiry,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        # Auth called twice: initial + re-auth after expiry
        assert auth.ensure_session.await_count == 2
        # Publish succeeded on retry
        mqtt.publish_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_reauth_only_once_per_cycle(self) -> None:
        """If re-auth also fails, don't loop forever — fail the cycle."""
        auth = FakeAuthClient()
        mqtt = FakeMqttPublisher()
        config = _make_config()

        async def always_expired(cookies: Any) -> dict:
            raise SessionExpiredError("Session still expired")

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=always_expired,
            mqtt_publisher=mqtt,
        )

        # Should not raise — logs error and moves on
        await orch.run_once()

        # Auth called at most twice (initial + one re-auth attempt)
        assert auth.ensure_session.await_count <= 2
        mqtt.publish_state.assert_not_called()


# ===========================================================================
# 4. Transient fetch failure retry with backoff
# ===========================================================================


class TestTransientRetry:
    """Transient CEZ downtime triggers bounded retry with backoff."""

    @pytest.mark.asyncio
    async def test_transient_failure_retries_up_to_max(self) -> None:
        auth = FakeAuthClient()
        fetcher = FakeFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config(max_retries=3)

        call_count = 0

        async def flaky_fetch(cookies: Any) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ConnectionError("CEZ API unreachable")
            return fetcher._payload

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=flaky_fetch,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        assert call_count == 3  # failed 2x, succeeded on 3rd
        mqtt.publish_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_exceeds_max_retries_logs_and_gives_up(self) -> None:
        auth = FakeAuthClient()
        mqtt = FakeMqttPublisher()
        config = _make_config(max_retries=2)

        async def always_fail(cookies: Any) -> dict:
            raise ConnectionError("CEZ API unreachable")

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=always_fail,
            mqtt_publisher=mqtt,
        )

        # Should not raise — logs error and moves on
        await orch.run_once()

        mqtt.publish_state.assert_not_called()


# ===========================================================================
# 5. MQTT publish failure handling
# ===========================================================================


class TestMqttFailure:
    """MQTT unavailability is logged and retried."""

    @pytest.mark.asyncio
    async def test_mqtt_publish_failure_logged(self, caplog) -> None:
        auth = FakeAuthClient()
        fetcher = FakeFetcher()
        mqtt = FakeMqttPublisher()
        mqtt.publish_state.side_effect = ConnectionError("MQTT broker unavailable")
        config = _make_config()

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        with caplog.at_level(logging.ERROR):
            await orch.run_once()

        assert any("MQTT" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_mqtt_failure_does_not_crash_orchestrator(self) -> None:
        auth = FakeAuthClient()
        fetcher = FakeFetcher()
        mqtt = FakeMqttPublisher()
        mqtt.publish_state.side_effect = ConnectionError("MQTT broker unavailable")
        config = _make_config()

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        # Should not raise — orchestrator absorbs and logs
        await orch.run_once()

    @pytest.mark.asyncio
    async def test_mqtt_recovers_after_broker_returns(self) -> None:
        """After MQTT failure, next cycle succeeds when broker is back."""
        auth = FakeAuthClient()
        fetcher = FakeFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config()

        call_count = 0
        original_publish = MagicMock()

        def publish_with_failure(readings: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("MQTT broker unavailable")
            original_publish(readings)

        mqtt.publish_state.side_effect = publish_with_failure

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        # First cycle — MQTT fails
        await orch.run_once()
        # Second cycle — MQTT recovers
        auth.ensure_session.reset_mock()
        await orch.run_once()

        # Second call succeeded
        assert call_count == 2
        original_publish.assert_called_once()


# ===========================================================================
# 6. Logging verification
# ===========================================================================


class TestLogging:
    """Orchestrator emits clear logs for failure modes."""

    @pytest.mark.asyncio
    async def test_logs_auth_failure(self, caplog) -> None:
        auth = FakeAuthClient()
        auth.ensure_session.side_effect = RuntimeError("Auth system down")
        fetcher = FakeFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config()

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        with caplog.at_level(logging.ERROR):
            await orch.run_once()

        assert any("auth" in record.message.lower() for record in caplog.records)

    @pytest.mark.asyncio
    async def test_logs_cez_downtime(self, caplog) -> None:
        auth = FakeAuthClient()
        mqtt = FakeMqttPublisher()
        config = _make_config(max_retries=1)

        async def cez_down(cookies: Any) -> dict:
            raise ConnectionError("CEZ API unreachable")

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=cez_down,
            mqtt_publisher=mqtt,
        )

        with caplog.at_level(logging.ERROR):
            await orch.run_once()

        assert any("cez" in record.message.lower() or "fetch" in record.message.lower()
                    for record in caplog.records)

    @pytest.mark.asyncio
    async def test_logs_mqtt_downtime(self, caplog) -> None:
        auth = FakeAuthClient()
        fetcher = FakeFetcher()
        mqtt = FakeMqttPublisher()
        mqtt.publish_state.side_effect = ConnectionError("MQTT down")
        config = _make_config()

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        with caplog.at_level(logging.ERROR):
            await orch.run_once()

        assert any("mqtt" in record.message.lower() for record in caplog.records)


# ===========================================================================
# 7. Scheduler loop
# ===========================================================================


class TestSchedulerLoop:
    """Orchestrator runs on a configurable polling interval."""

    @pytest.mark.asyncio
    async def test_run_loop_executes_cycles(self) -> None:
        """Loop runs multiple cycles until cancelled."""
        auth = FakeAuthClient()
        fetcher = FakeFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config(poll_interval_seconds=0.05)

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        task = asyncio.create_task(orch.run_loop())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have executed multiple cycles
        assert fetcher.fetch.await_count >= 2

    @pytest.mark.asyncio
    async def test_run_loop_uses_configured_interval(self) -> None:
        """Verify the loop waits approximately poll_interval between cycles."""
        auth = FakeAuthClient()
        fetcher = FakeFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config(poll_interval_seconds=0.1)

        timestamps: list[float] = []
        original_run_once = None

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        original_run_once = orch.run_once

        async def tracked_run_once() -> None:
            timestamps.append(asyncio.get_event_loop().time())
            await original_run_once()

        orch.run_once = tracked_run_once  # type: ignore[method-assign]

        task = asyncio.create_task(orch.run_loop())
        await asyncio.sleep(0.35)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # At least 2 timestamps
        assert len(timestamps) >= 2
        # Intervals should be approximately 0.1s (with tolerance)
        for i in range(1, len(timestamps)):
            gap = timestamps[i] - timestamps[i - 1]
            assert gap >= 0.05, f"gap too short: {gap:.3f}s"

    @pytest.mark.asyncio
    async def test_startup_publishes_discovery(self) -> None:
        """On first run, orchestrator publishes MQTT discovery."""
        auth = FakeAuthClient()
        fetcher = FakeFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config(poll_interval_seconds=0.05)

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        task = asyncio.create_task(orch.run_loop())
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        mqtt.start.assert_called_once()
        mqtt.publish_discovery.assert_called_once()


# ===========================================================================
# 8. Error sentinel constants exist
# ===========================================================================


class TestErrorSentinels:
    """Error type sentinels are defined for structured logging."""

    def test_cez_fetch_error_defined(self) -> None:
        assert isinstance(CEZ_FETCH_ERROR, str)

    def test_mqtt_publish_error_defined(self) -> None:
        assert isinstance(MQTT_PUBLISH_ERROR, str)

    def test_session_expired_error_defined(self) -> None:
        assert isinstance(SESSION_EXPIRED_ERROR, str)


# Import the custom exception used in tests above
from addon.src.orchestrator import SessionExpiredError  # noqa: E402
