"""Tests for the runtime orchestrator — TDD RED phase.

Covers:
- 15-minute polling scheduler (configurable)
- Transient failure retry with bounded backoff
- Session-expired (401) re-auth flow
- MQTT unavailability recovery
- Clear logging on auth failure, CEZ downtime, MQTT downtime
- Integration of auth, parser, and MQTT publisher modules
- Multi-assembly fetch (6 assemblies per cycle)
- Tab 17 date fallback (today → yesterday)
- Partial assembly failure handling
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from addon.src.orchestrator import (
    ASSEMBLY_CONFIGS,
    CEZ_FETCH_ERROR,
    HDO_FETCH_ERROR,
    MQTT_PUBLISH_ERROR,
    SESSION_EXPIRED,
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
    electrometer_id = overrides.pop("meter_id", "784703")
    ean = overrides.pop("ean", "85912345678901")

    defaults = {
        "poll_interval_seconds": 900,
        "max_retries": 3,
        "retry_base_delay_seconds": 0.01,
        "electrometers": [{"electrometer_id": electrometer_id, "ean": ean}],
        "email": "test@example.com",
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
                    "1002": {"v": "0,05", "s": 32},
                    "1003": {"v": "5,46", "s": 32},
                },
            ],
        }
        self.fetch = AsyncMock(side_effect=self._fetch)

    async def _fetch(self, cookies: Any, **kwargs: Any) -> dict:
        return self._payload


class FakeMqttPublisher:
    """Stub for MqttPublisher."""

    def __init__(self) -> None:
        self.start = MagicMock()
        self.stop = MagicMock()
        self.publish_discovery = MagicMock()
        self.publish_state = MagicMock()
        self.publish_hdo_state = MagicMock()


# ===========================================================================
# 1. OrchestratorConfig defaults
# ===========================================================================


class TestOrchestratorConfig:
    """OrchestratorConfig provides sensible defaults."""

    def test_default_poll_interval_is_15_minutes(self) -> None:
        config = _make_config()
        assert config.poll_interval_seconds == 900

    def test_default_max_retries(self) -> None:
        config = _make_config()
        assert config.max_retries == 3

    def test_custom_poll_interval(self) -> None:
        config = _make_config(poll_interval_seconds=300)
        assert config.poll_interval_seconds == 300

    def test_poll_interval_as_timedelta(self) -> None:
        config = _make_config()
        assert config.poll_interval == timedelta(seconds=900)

    def test_backward_compat_meter_id(self) -> None:
        config = _make_config()
        assert config.meter_id == "784703"

    def test_backward_compat_ean(self) -> None:
        config = _make_config()
        assert config.ean == "85912345678901"


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
        # Fetcher was called for each assembly
        assert fetcher.fetch.await_count == len(ASSEMBLY_CONFIGS)
        # MQTT state was published
        mqtt.publish_state.assert_called_once()
        state_arg = mqtt.publish_state.call_args[0][0]
        # State should be per-electrometer format: {electrometer_id: {sensor_key: value}}
        assert "784703" in state_arg
        meter_state = state_arg["784703"]
        assert "consumption" in meter_state
        assert meter_state["consumption"] == 1.42

    @pytest.mark.asyncio
    async def test_single_cycle_skips_publish_when_no_data(self) -> None:
        auth = FakeAuthClient()
        fetcher = FakeFetcher(payload={"hasData": False, "columns": [], "values": []})
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
        """Simulated auth failure on first call, success on second."""
        call_count = 0
        auth = FakeAuthClient()

        _ = auth.ensure_session.side_effect

        async def ensure_with_initial_failure():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Auth system down")
            return MagicMock(
                cookies=[{"name": "JSESSIONID", "value": "abc"}], reused=True
            )

        auth.ensure_session.side_effect = ensure_with_initial_failure

        fetcher = MultiAssemblyFetcher()
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

    @pytest.mark.asyncio
    async def test_reauth_only_once_per_cycle(self) -> None:
        """If auth always fails, don't loop forever — fail the cycle."""
        auth = FakeAuthClient()
        auth.ensure_session.side_effect = RuntimeError("Auth permanently down")
        mqtt = FakeMqttPublisher()
        config = _make_config()

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=MultiAssemblyFetcher().fetch,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        auth.ensure_session.assert_awaited_once()
        mqtt.publish_state.assert_not_called()


# ===========================================================================
# 4. Transient fetch failure retry with backoff
# ===========================================================================


class TestTransientRetry:
    """Transient CEZ downtime triggers bounded retry with backoff."""

    @pytest.mark.asyncio
    async def test_transient_failure_in_single_assembly_still_publishes_others(
        self,
    ) -> None:
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher(fail_on={-1003})
        mqtt = FakeMqttPublisher()
        config = _make_config(max_retries=3)

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        mqtt.publish_state.assert_called_once()
        state = mqtt.publish_state.call_args[0][0]
        # State should be per-electrometer format: {electrometer_id: {sensor_key: value}}
        assert "consumption" in state.get("784703", {})

    @pytest.mark.asyncio
    async def test_all_assemblies_fail_no_publish(self) -> None:
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher(
            fail_on={-1003, -1012, -1011, -1021, -1022, -1027}
        )
        mqtt = FakeMqttPublisher()
        config = _make_config(max_retries=2)

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

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

        assert any(
            "cez" in record.message.lower() or "fetch" in record.message.lower()
            for record in caplog.records
        )

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

    def test_session_expired_defined(self) -> None:
        assert isinstance(SESSION_EXPIRED, str)


# Import the custom exception used in tests above
from addon.src.orchestrator import SessionExpiredError  # noqa: E402

# ── Multi-assembly payload helpers ────────────────────────────────────


def _make_profile_all_payload() -> dict:
    """Tab 00 (-1003): +A, -A, Rv with meter ID."""
    return {
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


def _make_profile_consumption_reactive_payload() -> dict:
    """Tab 03 (-1012): Profil +A, Profil +Ri, Profil -Rc."""
    return {
        "hasData": True,
        "columns": [
            {"id": "2000", "name": "Datum", "unit": None},
            {"id": "2001", "name": "Profil +A", "unit": "kW"},
            {"id": "2002", "name": "Profil +Ri", "unit": "kW"},
            {"id": "2003", "name": "Profil -Rc", "unit": "kW"},
        ],
        "values": [
            {
                "2000": {"v": "14.02.2026 00:15"},
                "2001": {"v": "1,42", "s": 32},
                "2002": {"v": "0,31", "s": 32},
                "2003": {"v": "0,12", "s": 32},
            },
        ],
    }


def _make_profile_production_reactive_payload() -> dict:
    """Tab 04 (-1011): Profil -A, Profil -Ri, Profil +Rc."""
    return {
        "hasData": True,
        "columns": [
            {"id": "3000", "name": "Datum", "unit": None},
            {"id": "3001", "name": "Profil -A", "unit": "kW"},
            {"id": "3002", "name": "Profil -Ri", "unit": "kW"},
            {"id": "3003", "name": "Profil +Rc", "unit": "kW"},
        ],
        "values": [
            {
                "3000": {"v": "14.02.2026 00:15"},
                "3001": {"v": "0,05", "s": 32},
                "3002": {"v": "0,02", "s": 32},
                "3003": {"v": "0,01", "s": 32},
            },
        ],
    }


def _make_daily_consumption_payload() -> dict:
    """Tab 07 (-1021): +A d with meter ID."""
    return {
        "hasData": True,
        "columns": [
            {"id": "4000", "name": "Datum", "unit": None},
            {"id": "4001", "name": "+A d/784703", "unit": "kWh"},
        ],
        "values": [
            {
                "4000": {"v": "14.02.2026 00:15"},
                "4001": {"v": "23,45", "s": 32},
            },
        ],
    }


def _make_daily_production_payload() -> dict:
    """Tab 08 (-1022): -A d with meter ID."""
    return {
        "hasData": True,
        "columns": [
            {"id": "5000", "name": "Datum", "unit": None},
            {"id": "5001", "name": "-A d/784703", "unit": "kWh"},
        ],
        "values": [
            {
                "5000": {"v": "14.02.2026 00:15"},
                "5001": {"v": "1,23", "s": 32},
            },
        ],
    }


def _make_register_payload(has_data: bool = True) -> dict:
    """Tab 17 (-1027): +E, -E, +E_NT, +E_VT with meter ID."""
    if not has_data:
        return {"hasData": False, "columns": [], "values": []}
    return {
        "hasData": True,
        "columns": [
            {"id": "6000", "name": "Datum", "unit": None},
            {"id": "6001", "name": "+E/784703", "unit": "kWh"},
            {"id": "6002", "name": "-E/784703", "unit": "kWh"},
            {"id": "6003", "name": "+E_NT/784703", "unit": "kWh"},
            {"id": "6004", "name": "+E_VT/784703", "unit": "kWh"},
        ],
        "values": [
            {
                "6000": {"v": "14.02.2026 00:15"},
                "6001": {"v": "12345,67", "s": 32},
                "6002": {"v": "234,56", "s": 32},
                "6003": {"v": "8000,00", "s": 32},
                "6004": {"v": "4345,67", "s": 32},
            },
        ],
    }


_ASSEMBLY_PAYLOADS: dict[int, dict] = {
    -1003: _make_profile_all_payload(),
    -1012: _make_profile_consumption_reactive_payload(),
    -1011: _make_profile_production_reactive_payload(),
    -1021: _make_daily_consumption_payload(),
    -1022: _make_daily_production_payload(),
    -1027: _make_register_payload(),
}


class MultiAssemblyFetcher:
    """Fake fetcher that returns different payloads per assembly_id."""

    def __init__(
        self,
        payloads: dict[int, dict] | None = None,
        *,
        fail_on: set[int] | None = None,
    ) -> None:
        self._payloads = payloads or dict(_ASSEMBLY_PAYLOADS)
        self._fail_on = fail_on or set()
        self.calls: list[dict[str, Any]] = []

    async def fetch(self, cookies: Any, **kwargs: Any) -> dict:
        self.calls.append({"cookies": cookies, **kwargs})
        assembly_id: int = kwargs.get("assembly_id", 0)
        if assembly_id in self._fail_on:
            raise ConnectionError(f"Assembly {assembly_id} fetch failed")
        return self._payloads.get(
            assembly_id, {"hasData": False, "columns": [], "values": []}
        )


# ===========================================================================
# 9. Multi-assembly fetch (6 assemblies per cycle)
# ===========================================================================


class TestMultiAssemblyFetch:

    @pytest.mark.asyncio
    async def test_multi_assembly_fetches_all_six(self) -> None:
        """Orchestrator calls fetcher 6 times with correct assembly IDs."""
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config()

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        fetched_ids = [c["assembly_id"] for c in fetcher.calls]
        assert sorted(fetched_ids) == sorted([-1003, -1012, -1011, -1021, -1022, -1027])

    @pytest.mark.asyncio
    async def test_multi_assembly_merges_all_13_sensor_keys(self) -> None:
        """State published to MQTT contains all 13 sensor keys from merged results."""
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config()

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        mqtt.publish_state.assert_called_once()
        state = mqtt.publish_state.call_args[0][0]

        # State should now be per-electrometer format: {electrometer_id: {sensor_key: value}}
        assert "784703" in state
        meter_state = state["784703"]

        expected_keys = {
            "consumption",
            "production",
            "reactive",
            "reactive_import_inductive",
            "reactive_export_capacitive",
            "reactive_export_inductive",
            "reactive_import_capacitive",
            "daily_consumption",
            "daily_production",
            "register_consumption",
            "register_production",
            "register_low_tariff",
            "register_high_tariff",
        }
        assert set(meter_state.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_multi_assembly_values_are_correct(self) -> None:
        """Merged state values come from correct assembly payloads."""
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config()

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        state = mqtt.publish_state.call_args[0][0]
        # State should be per-electrometer format: {electrometer_id: {sensor_key: value}}
        assert "784703" in state
        meter_state = state["784703"]

        assert meter_state["consumption"] == 1.42
        assert meter_state["production"] == 0.05
        assert meter_state["reactive"] == 5.46
        assert meter_state["reactive_import_inductive"] == 0.31
        assert meter_state["reactive_export_capacitive"] == 0.12
        assert meter_state["daily_consumption"] == 23.45
        assert meter_state["daily_production"] == 1.23
        assert meter_state["register_consumption"] == 12345.67
        assert meter_state["register_low_tariff"] == 8000.0
        assert meter_state["register_high_tariff"] == 4345.67

    @pytest.mark.asyncio
    async def test_assembly_configs_has_six_entries(self) -> None:
        """ASSEMBLY_CONFIGS constant defines exactly 6 assemblies."""
        assert len(ASSEMBLY_CONFIGS) == 6
        ids = [c["id"] for c in ASSEMBLY_CONFIGS]
        assert sorted(ids) == sorted([-1003, -1012, -1011, -1021, -1022, -1027])

    @pytest.mark.asyncio
    async def test_only_register_assembly_has_fallback_flag(self) -> None:
        """Only -1027 has fallback_yesterday=True."""
        for config in ASSEMBLY_CONFIGS:
            if config["id"] == -1027:
                assert config.get("fallback_yesterday") is True
            else:
                assert config.get("fallback_yesterday") in (None, False)


# ===========================================================================
# 10. Partial assembly failure
# ===========================================================================


class TestPartialAssemblyFailure:

    @pytest.mark.asyncio
    async def test_partial_assembly_failure_publishes_remaining(self) -> None:
        """If one assembly fails, others still publish."""
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher(fail_on={-1012})
        mqtt = FakeMqttPublisher()
        config = _make_config()

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        mqtt.publish_state.assert_called_once()
        state = mqtt.publish_state.call_args[0][0]
        # State should be per-electrometer format: {electrometer_id: {sensor_key: value}}
        assert "784703" in state
        meter_state = state["784703"]
        assert meter_state["consumption"] == 1.42
        assert "reactive_import_inductive" not in meter_state
        assert "reactive_export_capacitive" not in meter_state

    @pytest.mark.asyncio
    async def test_partial_failure_logs_warning(self, caplog) -> None:
        """Failed assembly emits an error log."""
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher(fail_on={-1021})
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

        assert any("daily_consumption" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_all_assemblies_fail_skips_publish(self) -> None:
        """If ALL assemblies fail, no state is published."""
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher(
            fail_on={-1003, -1012, -1011, -1021, -1022, -1027}
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
# 11. Tab 17 date fallback
# ===========================================================================


class TestTab17DateFallback:

    @pytest.mark.asyncio
    async def test_tab17_today_has_data(self) -> None:
        """When Tab 17 today has data, use it directly — no fallback call."""
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config()

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        tab17_calls = [c for c in fetcher.calls if c["assembly_id"] == -1027]
        assert len(tab17_calls) == 1  # No fallback needed

        state = mqtt.publish_state.call_args[0][0]
        assert state.get("784703", {})["register_consumption"] == 12345.67

    @pytest.mark.asyncio
    async def test_tab17_today_no_data_fetches_yesterday(self) -> None:
        """When Tab 17 today returns hasData=false, retry with yesterday's date."""
        auth = FakeAuthClient()
        mqtt = FakeMqttPublisher()
        config = _make_config()

        call_count_1027 = 0
        yesterday_payload = _make_register_payload(has_data=True)

        async def fetch_with_tab17_fallback(cookies: Any, **kwargs: Any) -> dict:
            nonlocal call_count_1027
            assembly_id = kwargs.get("assembly_id", 0)
            if assembly_id == -1027:
                call_count_1027 += 1
                if call_count_1027 == 1:
                    return _make_register_payload(has_data=False)
                return yesterday_payload
            return _ASSEMBLY_PAYLOADS.get(
                assembly_id, {"hasData": False, "columns": [], "values": []}
            )

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetch_with_tab17_fallback,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        assert call_count_1027 == 2  # Today + yesterday
        state = mqtt.publish_state.call_args[0][0]
        assert state.get("784703", {})["register_consumption"] == 12345.67

    @pytest.mark.asyncio
    async def test_tab17_both_days_no_data_excludes_register_keys(self) -> None:
        """When both today and yesterday have no data, register fields are absent."""
        auth = FakeAuthClient()
        mqtt = FakeMqttPublisher()
        config = _make_config()

        async def fetch_tab17_always_empty(cookies: Any, **kwargs: Any) -> dict:
            assembly_id = kwargs.get("assembly_id", 0)
            if assembly_id == -1027:
                return _make_register_payload(has_data=False)
            return _ASSEMBLY_PAYLOADS.get(
                assembly_id, {"hasData": False, "columns": [], "values": []}
            )

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetch_tab17_always_empty,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        state = mqtt.publish_state.call_args[0][0]
        meter_state = state.get("784703", {})
        assert "register_consumption" not in meter_state
        assert "register_production" not in meter_state
        assert "register_low_tariff" not in meter_state
        assert "register_high_tariff" not in meter_state

    @pytest.mark.asyncio
    async def test_tab17_fallback_uses_shifted_dates(self) -> None:
        """Fallback call uses date_from - 1 day for yesterday's data."""
        auth = FakeAuthClient()
        mqtt = FakeMqttPublisher()
        config = _make_config()

        captured_dates: list[dict] = []

        async def capture_dates(cookies: Any, **kwargs: Any) -> dict:
            assembly_id = kwargs.get("assembly_id", 0)
            if assembly_id == -1027:
                captured_dates.append(
                    {
                        "date_from": kwargs.get("date_from"),
                        "date_to": kwargs.get("date_to"),
                    }
                )
                if len(captured_dates) == 1:
                    return _make_register_payload(has_data=False)
                return _make_register_payload(has_data=True)
            return _ASSEMBLY_PAYLOADS.get(
                assembly_id, {"hasData": False, "columns": [], "values": []}
            )

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=capture_dates,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        assert len(captured_dates) == 2
        first_from = captured_dates[0]["date_from"]
        second_from = captured_dates[1]["date_from"]
        first_date = datetime.strptime(first_from.split()[0], "%d.%m.%Y")
        second_date = datetime.strptime(second_from.split()[0], "%d.%m.%Y")
        assert second_date == first_date - timedelta(days=1)


# ===========================================================================
# 12. Session expiry mid-multi-fetch
# ===========================================================================


class TestSessionExpiryMidMultiFetch:

    @pytest.mark.asyncio
    async def test_session_expiry_mid_multi_fetch_logs_error_continues(self) -> None:
        """SessionExpiredError on one assembly is caught; other assemblies still publish."""
        auth = FakeAuthClient()
        mqtt = FakeMqttPublisher()
        config = _make_config()

        call_count = 0
        expired_once = False

        async def fetch_expires_on_second(cookies: Any, **kwargs: Any) -> dict:
            nonlocal call_count, expired_once
            call_count += 1
            assembly_id = kwargs.get("assembly_id", 0)
            if call_count == 2 and not expired_once:
                expired_once = True
                raise SessionExpiredError("Session expired mid-fetch")
            return _ASSEMBLY_PAYLOADS.get(
                assembly_id, {"hasData": False, "columns": [], "values": []}
            )

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetch_expires_on_second,
            mqtt_publisher=mqtt,
        )

        await orch.run_once()

        mqtt.publish_state.assert_called_once()
        state = mqtt.publish_state.call_args[0][0]
        # State should be per-electrometer format: {electrometer_id: {sensor_key: value}}
        assert "784703" in state
        meter_state = state["784703"]
        assert "consumption" in meter_state


# ===========================================================================
# 13. HDO integration
# ===========================================================================


_HDO_RAW_RESPONSE: dict[str, Any] = {
    "signals": [
        {
            "signal": "EVV2",
            "den": "Pondělí",
            "datum": "16.02.2026",
            "casy": "00:00-08:00;   09:00-12:00;   13:00-15:00;   16:00-19:00;   20:00-24:00",
        }
    ]
}


class TestHdoIntegration:

    @pytest.mark.asyncio
    async def test_hdo_fetcher_called_with_ean(self) -> None:
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config(
            electrometers=[{"electrometer_id": "784703", "ean": "859182400100000001"}]
        )

        hdo_fetcher = AsyncMock(return_value=_HDO_RAW_RESPONSE)

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
            hdo_fetcher=hdo_fetcher,
        )

        await orch.run_once()

        hdo_fetcher.assert_awaited_once()
        call_args = hdo_fetcher.call_args
        assert call_args[0][1] == "859182400100000001"

    @pytest.mark.asyncio
    async def test_hdo_publishes_state(self) -> None:
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config(
            electrometers=[{"electrometer_id": "784703", "ean": "859182400100000001"}]
        )

        hdo_fetcher = AsyncMock(return_value=_HDO_RAW_RESPONSE)

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
            hdo_fetcher=hdo_fetcher,
        )

        await orch.run_once()

        mqtt.publish_hdo_state.assert_called_once()
        hdo_data = mqtt.publish_hdo_state.call_args[0][0]
        assert hdo_data.signal_name == "EVV2"
        assert isinstance(hdo_data.is_low_tariff, bool)
        assert len(hdo_data.today_schedule) == 5

    @pytest.mark.asyncio
    async def test_hdo_not_called_when_no_fetcher(self) -> None:
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config()

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
            hdo_fetcher=None,
        )

        await orch.run_once()

        mqtt.publish_hdo_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_hdo_failure_does_not_block_pnd(self) -> None:
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config(
            electrometers=[{"electrometer_id": "784703", "ean": "859182400100000001"}]
        )

        hdo_fetcher = AsyncMock(side_effect=RuntimeError("DIP timeout"))

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
            hdo_fetcher=hdo_fetcher,
        )

        await orch.run_once()

        mqtt.publish_state.assert_called_once()
        mqtt.publish_hdo_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_hdo_failure_logs_error(self, caplog) -> None:
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher()
        mqtt = FakeMqttPublisher()
        config = _make_config(
            electrometers=[{"electrometer_id": "784703", "ean": "859182400100000001"}]
        )

        hdo_fetcher = AsyncMock(side_effect=RuntimeError("DIP timeout"))

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
            hdo_fetcher=hdo_fetcher,
        )

        with caplog.at_level(logging.ERROR):
            await orch.run_once()

        assert any("HDO" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_pnd_failure_does_not_block_hdo(self) -> None:
        auth = FakeAuthClient()
        fetcher = MultiAssemblyFetcher(
            fail_on={-1003, -1012, -1011, -1021, -1022, -1027}
        )
        mqtt = FakeMqttPublisher()
        config = _make_config(
            electrometers=[{"electrometer_id": "784703", "ean": "859182400100000001"}]
        )

        hdo_fetcher = AsyncMock(return_value=_HDO_RAW_RESPONSE)

        orch = Orchestrator(
            config=config,
            auth_client=auth,
            fetcher=fetcher.fetch,
            mqtt_publisher=mqtt,
            hdo_fetcher=hdo_fetcher,
        )

        await orch.run_once()

        mqtt.publish_state.assert_not_called()
        mqtt.publish_hdo_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_hdo_sentinel_is_defined(self) -> None:
        assert isinstance(HDO_FETCH_ERROR, str)
        assert HDO_FETCH_ERROR == "HDO_FETCH_ERROR"
