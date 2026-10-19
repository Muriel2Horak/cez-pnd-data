"""Fault injection for implementation-review findings."""

from __future__ import annotations

import asyncio
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from addon.src.blocking import run_blocking
from addon.src.hdo_parser import UNKNOWN_HDO, parse_hdo_signals
from addon.src.main import run_until_shutdown
from addon.src.mqtt_publisher import MqttPublisher
from addon.src.orchestrator import Orchestrator, OrchestratorConfig
from addon.src.pnd_protocol import ServiceMaintenanceError, SessionExpiredError
from tests.test_functional_fixes import READING
from tests.test_mqtt_transport import SimpleReason, transport_mock


@pytest.mark.asyncio
async def test_hdo_publish_failure_preserves_valid_schedule_for_reconnect():
    client, raw = transport_mock()
    publisher = MqttPublisher(client, electrometer_id="123", ean="ean123")
    auth = SimpleNamespace(
        ensure_session=AsyncMock(
            return_value=SimpleNamespace(
                cookies=[], has_live_context=True, context=object()
            )
        )
    )
    hdo = AsyncMock(
        return_value={
            "signals": [
                {
                    "datum": datetime.now(ZoneInfo("Europe/Prague")).strftime(
                        "%d.%m.%Y"
                    ),
                    "signal": "TEST",
                    "casy": "00:00-24:00",
                }
            ]
        }
    )
    orch = Orchestrator(
        OrchestratorConfig([{"electrometer_id": "123", "ean": "ean123"}]),
        auth,
        AsyncMock(),
        publisher,
        batch_fetcher=AsyncMock(return_value={}),
        hdo_fetcher=hdo,
    )
    try:
        # The broker is offline while the cycle fetches a valid schedule.
        await orch.run_once()
        hdo.assert_awaited_once()
        raw.publish.assert_not_called()

        # Recovery must deliver the schedule without another CEZ poll.
        client._connected.set()
        client._replay()
        sent = {call.args[0]: call.args[1] for call in raw.publish.call_args_list}
        assert sent == {
            "cez_pnd/123/hdo_low_tariff_active/state": "ON",
            "cez_pnd/123/hdo_next_switch/state": "None",
            "cez_pnd/123/hdo_schedule_today/state": "00:00-24:00",
            "cez_pnd/123/hdo_signal/state": "TEST",
        }
    finally:
        client.disconnect()


@pytest.mark.asyncio
async def test_batch_setup_failure_keeps_hdo_and_next_cycle_working():
    auth = SimpleNamespace(
        ensure_session=AsyncMock(
            return_value=SimpleNamespace(
                cookies=[],
                has_live_context=True,
                context=object(),
            )
        )
    )
    batch = AsyncMock(
        side_effect=[
            ConnectionError("temporary browser setup failure"),
            {"profile_all": READING},
        ]
    )
    hdo = AsyncMock(
        return_value={
            "signals": [
                {
                    "datum": datetime.now(ZoneInfo("Europe/Prague")).strftime(
                        "%d.%m.%Y"
                    ),
                    "signal": "TEST",
                    "casy": "00:00-24:00",
                }
            ]
        }
    )
    publisher = MagicMock()
    orch = Orchestrator(
        OrchestratorConfig([{"electrometer_id": "123", "ean": "ean123"}]),
        auth,
        AsyncMock(),
        publisher,
        batch_fetcher=batch,
        hdo_fetcher=hdo,
    )
    await orch.run_once()
    publisher.publish_state.assert_not_called()
    assert hdo.await_count == 1
    await orch.run_once()
    publisher.publish_state.assert_called_once_with({"123": {"consumption": 1.5}})
    assert hdo.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [SessionExpiredError("expired"), ServiceMaintenanceError("maintenance")]
)
async def test_batch_setup_handler_does_not_swallow_authentication_or_maintenance(
    error,
):
    orch = Orchestrator(
        OrchestratorConfig([]),
        MagicMock(),
        AsyncMock(),
        MagicMock(),
        batch_fetcher=AsyncMock(side_effect=error),
    )
    with pytest.raises(type(error)):
        await orch._fetch_all_assemblies([], "123")


def test_initial_connection_waits_beyond_publish_timeout():
    client, raw = transport_mock()
    client._startup_timeout = 0.3
    accepted = threading.Event()

    def accept():
        raw.on_connect(raw, None, None, SimpleReason(False), None)
        accepted.set()

    timer = threading.Timer(0.06, accept)
    raw.loop_start.side_effect = timer.start
    try:
        client.connect()
        assert accepted.is_set()
        raw.loop_stop.assert_not_called()
    finally:
        client.disconnect()
        timer.join()


def test_transient_connack_is_retried_but_authentication_refusal_is_terminal():
    client, raw = transport_mock()
    unavailable = SimpleNamespace(is_failure=True, value=136)
    raw.on_connect(raw, None, None, unavailable, None)
    assert not client._ready.is_set()
    raw.on_connect(raw, None, None, SimpleReason(True), None)
    assert client._ready.is_set()
    assert "rejected" in client._error
    client.disconnect()


def test_shutdown_interrupts_initial_connection_wait():
    client, raw = transport_mock()
    client._startup_timeout = 60
    started = threading.Event()
    errors = []
    raw.loop_start.side_effect = started.set

    def connect():
        try:
            client.connect()
        except ConnectionError as exc:
            errors.append(str(exc))

    worker = threading.Thread(target=connect, daemon=True)
    worker.start()
    assert started.wait(1)
    client.begin_shutdown()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert errors == ["MQTT startup cancelled"]


@pytest.mark.parametrize("schedule", ["", "   ", "; ;"])
def test_empty_dated_hdo_schedule_is_unknown(schedule):
    result = parse_hdo_signals(
        {
            "signals": [
                {
                    "datum": "15.10.2026",
                    "signal": "EVV2",
                    "casy": schedule,
                }
            ]
        },
        now=datetime(2026, 10, 15, 12),
    )
    assert result.is_low_tariff is None
    assert result.today_schedule is None
    assert result.next_switch is None
    assert result.signal_name == "EVV2"


def test_empty_tomorrow_schedule_cannot_establish_midnight_transition():
    result = parse_hdo_signals(
        {
            "signals": [
                {"datum": "15.10.2026", "signal": "EVV2", "casy": "20:00-24:00"},
                {"datum": "16.10.2026", "signal": "EVV2", "casy": ""},
            ]
        },
        now=datetime(2026, 10, 15, 23),
    )
    assert result.is_low_tariff is True
    assert result.next_switch is None


@pytest.mark.asyncio
async def test_cleanup_runs_even_when_polling_cancellation_exhausts_budget():
    shutdown = asyncio.Event()
    unwinding = asyncio.Event()
    cleanup = AsyncMock()

    async def work():
        shutdown.set()
        try:
            await asyncio.Event().wait()
        finally:
            unwinding.set()
            await asyncio.sleep(10)

    start = time.monotonic()
    await run_until_shutdown(work, shutdown, cleanup, timeout=0.02)
    assert time.monotonic() - start < 0.3
    assert unwinding.is_set()
    cleanup.assert_awaited_once()
    await asyncio.sleep(0)  # Let the deadline's final cancellation settle.


def test_blocking_cleanup_cannot_keep_subprocess_alive_after_deadline():
    script = """
import asyncio,time
from addon.src.blocking import run_blocking
from addon.src.main import run_until_shutdown
async def main():
    stop=asyncio.Event(); stop.set()
    async def work(): await asyncio.Event().wait()
    async def cleanup(): await run_blocking(time.sleep, 10)
    await run_until_shutdown(work, stop, cleanup, timeout=0.02)
asyncio.run(main())
print("exited", flush=True)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=2
    )
    assert completed.returncode == 0, completed.stderr
    assert "exited" in completed.stdout


@pytest.mark.asyncio
async def test_blocking_worker_propagates_errors_and_ignores_late_completion():
    def fail():
        raise ValueError("worker failed")

    with pytest.raises(ValueError, match="worker failed"):
        await run_blocking(fail)
    release = threading.Event()
    finished = threading.Event()

    def delayed():
        release.wait(1)
        finished.set()

    task = asyncio.create_task(run_blocking(delayed))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    assert finished.wait(1)
    await asyncio.sleep(0)


def test_outage_caches_all_new_meter_and_hdo_values_before_first_send():
    client, raw = transport_mock()
    client._connected.set()
    publisher = MqttPublisher(
        client, electrometers=[{"electrometer_id": "123"}, {"electrometer_id": "456"}]
    )
    publisher.publish_state({"123": {"consumption": 1.0}, "456": {"consumption": 2.0}})
    client._connected.clear()
    with pytest.raises(ConnectionError):
        publisher.publish_state(
            {
                "123": {"consumption": 3.0, "production": 0.5},
                "456": {"consumption": 4.0},
            }
        )
    with pytest.raises(ConnectionError):
        publisher.publish_hdo_state(UNKNOWN_HDO, electrometer_id="456")
    assert client._retained["cez_pnd/123/consumption/state"] == ("3.0", 1)
    assert client._retained["cez_pnd/123/production/state"] == ("0.5", 1)
    assert client._retained["cez_pnd/456/consumption/state"] == ("4.0", 1)
    for key in (
        "hdo_low_tariff_active",
        "hdo_next_switch",
        "hdo_schedule_today",
        "hdo_signal",
    ):
        assert client._retained[f"cez_pnd/456/{key}/state"] == ("None", 1)
    raw.publish.reset_mock()
    client._connected.set()
    client._replay()
    sent = {call.args[0]: call.args[1] for call in raw.publish.call_args_list}
    assert sent["cez_pnd/456/consumption/state"] == "4.0"
    assert sent["cez_pnd/456/hdo_signal/state"] == "None"
    client.disconnect()


@pytest.mark.parametrize("failed_index", [0, 1, 2])
def test_replay_recovers_from_delayed_ack_without_repeating_acknowledged_topics(
    failed_index,
):
    client, raw = transport_mock()
    client._connected.set()
    topics = ["config/one", "config/two", "config/three"]
    client.cache_retained([(topic, topic) for topic in topics])
    acknowledgements = [None] * len(topics)
    acknowledgements.insert(failed_index, TimeoutError("slow ACK"))
    raw.publish.return_value.wait_for_publish.side_effect = acknowledgements
    client._replay()
    expected = topics.copy()
    expected.insert(failed_index, topics[failed_index])
    assert [call.args[0] for call in raw.publish.call_args_list] == expected
    client.disconnect()


def test_shutdown_interrupts_replay_backoff_and_ack_wait():
    client, raw = transport_mock()
    client._connected.set()
    client.cache_retained([("config", "payload")])
    attempted = threading.Event()

    def no_ack(timeout):
        attempted.set()
        time.sleep(timeout)

    raw.publish.return_value.wait_for_publish.side_effect = no_ack
    raw.publish.return_value.is_published.return_value = False
    client._timeout = 5
    client._replay_retry_delay = 10
    worker = threading.Thread(target=client._replay, daemon=True)
    worker.start()
    assert attempted.wait(1)
    client.begin_shutdown()
    worker.join(timeout=0.5)
    assert not worker.is_alive()
    client.disconnect()


def test_application_deadline_survives_cancellation_resistant_cleanup():
    script = """
import asyncio,signal,time
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
from addon.src import main as app
async def stubborn_close():
    try:
        await asyncio.sleep(900)
    finally:
        await asyncio.sleep(900)
async def polling():
    print("ready",flush=True)
    await asyncio.Event().wait()
auth=SimpleNamespace(close=stubborn_close)
publisher=MagicMock()
publisher.stop.side_effect=lambda:time.sleep(900)
app.PlaywrightAuthClient=lambda *a:auth
app.resolve_mqtt_config=AsyncMock(return_value={})
app.create_config=lambda *a:{"cez":{"electrometers":[],"email":"test","ean":""},"mqtt":{"host":"unused","port":1883}}
app.MQTTClientWrapper=lambda **kw:MagicMock()
app.MqttPublisher=lambda *a,**kw:publisher
app.Orchestrator=lambda **kw:SimpleNamespace(run_loop=polling)
original=app.run_until_shutdown
async def short_grace(*a,**kw):
    return await original(*a,**kw,timeout=0.05)
app.run_until_shutdown=short_grace
asyncio.run(app.main())
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        start = time.monotonic()
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=2) == 1  # Explicit failed graceful shutdown.
        assert time.monotonic() - start < 1
        assert "Shutdown cleanup exceeded" in process.stderr.read()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_shutdown_allows_only_the_registered_final_availability_message():
    client, raw = transport_mock()
    client._connected.set()
    client.will_set("availability", "offline")
    client.begin_shutdown()
    with pytest.raises(ConnectionError):
        client.publish("state", "new")
    with pytest.raises(ConnectionError):
        client.publish("availability", "online")
    client.publish("availability", "offline")
    raw.publish.assert_called_once_with("availability", "offline", 1, True)
    client.disconnect()
