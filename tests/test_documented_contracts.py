"""Compatibility, documentation examples, and lifecycle logging contracts."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
import signal
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from addon.src import hdo_parser
from addon.src import main as app
from addon.src import pnd_protocol
from addon.src.mqtt_client import MQTTClientWrapper
from addon.src.mqtt_publisher import MqttPublisher


@pytest.mark.parametrize(
    "legacy_module,new_module,name",
    [
        ("main", "mqtt_client", "MQTTClientWrapper"),
        ("main", "pnd_protocol", "PndFetchError"),
        ("main", "pnd_protocol", "build_pnd_payload"),
        ("main", "pnd_protocol", "PND_DATA_URL"),
        ("main", "pnd_protocol", "SessionExpiredError"),
        ("auth", "pnd_protocol", "ServiceMaintenanceError"),
        ("orchestrator", "pnd_protocol", "SessionExpiredError"),
    ],
)
def test_moved_definitions_keep_legacy_imports(legacy_module, new_module, name):
    legacy = getattr(importlib.import_module(f"addon.src.{legacy_module}"), name)
    canonical = getattr(importlib.import_module(f"addon.src.{new_module}"), name)
    assert legacy is canonical


@pytest.mark.asyncio
async def test_protocol_errors_are_catchable_through_original_imports():
    context = SimpleNamespace(request=SimpleNamespace(post=AsyncMock()))
    context.request.post.return_value = SimpleNamespace(status=403)
    with pytest.raises(app.SessionExpiredError):
        await pnd_protocol.request_data(context, "123", -1003, "start", "end")
    context.request.post.return_value = SimpleNamespace(status=503)
    with pytest.raises(app.PndFetchError) as error:
        await pnd_protocol.request_data(context, "123", -1003, "start", "end")
    assert error.value.status_code == 503


def test_documented_hdo_response_example_is_valid_and_parseable():
    documentation = inspect.getdoc(hdo_parser)
    assert documentation is not None
    example = json.loads(
        documentation[documentation.index("{") : documentation.rindex("}") + 1]
    )
    result = hdo_parser.parse_hdo_signals(
        example,
        now=datetime(2026, 2, 15, 10, tzinfo=ZoneInfo("Europe/Prague")),
    )
    assert result.signal_name == "EVV2"
    assert result.is_low_tariff is True
    assert result.today_schedule == [
        ("00:00", "08:00"),
        ("09:00", "12:00"),
        ("13:00", "15:00"),
        ("16:00", "19:00"),
        ("20:00", "24:00"),
    ]
    assert result.next_switch == datetime(
        2026, 2, 15, 12, tzinfo=ZoneInfo("Europe/Prague")
    )


@pytest.mark.parametrize(
    "documented",
    [
        hdo_parser._parse_time_ranges,
        hdo_parser._time_from_str,
        hdo_parser._is_in_low_tariff,
        MqttPublisher.start,
        MqttPublisher.stop,
        MQTTClientWrapper,
        MQTTClientWrapper.will_set,
        MQTTClientWrapper.connect,
        MQTTClientWrapper.publish,
        MQTTClientWrapper.disconnect,
        pnd_protocol.PndFetchError,
    ],
)
def test_restored_api_documentation_is_present(documented):
    assert inspect.getdoc(documented)


@pytest.mark.asyncio
@pytest.mark.parametrize("automatic", [False, True])
async def test_application_logs_configuration_signal_and_shutdown(
    monkeypatch, caplog, automatic
):
    meters = (
        [] if automatic else [{"electrometer_id": "123", "ean": "859182400123456789"}]
    )
    config = {
        "cez": {
            "email": "user@example.invalid",
            "password": "cez-secret",
            "electrometer_id": None if automatic else "123",
            "electrometers": meters,
            "ean": "",
        },
        "mqtt": {"host": "core-mosquitto", "port": 1883},
    }
    auth = SimpleNamespace(close=AsyncMock())
    raw = MagicMock()
    publisher = MqttPublisher(raw, electrometer_id="123")
    handlers = {}
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        loop,
        "add_signal_handler",
        lambda sig, callback, *args: handlers.update({sig: (callback, args)}),
    )
    removed = MagicMock()
    monkeypatch.setattr(loop, "remove_signal_handler", removed)
    monkeypatch.setattr(app, "PlaywrightAuthClient", lambda *args: auth)
    monkeypatch.setattr(app, "resolve_mqtt_config", AsyncMock(return_value={}))
    monkeypatch.setattr(app, "create_config", lambda *args: config)
    monkeypatch.setattr(app, "MQTTClientWrapper", lambda **kwargs: raw)
    monkeypatch.setattr(app, "MqttPublisher", lambda *args, **kwargs: publisher)

    async def polling():
        publisher.start()
        callback, args = handlers[signal.SIGTERM]
        callback(*args)
        await asyncio.Event().wait()

    monkeypatch.setattr(
        app, "Orchestrator", lambda **kwargs: SimpleNamespace(run_loop=polling)
    )
    with caplog.at_level(logging.INFO):
        await app.main()

    messages = caplog.text
    assert "Starting CEZ PND add-on" in messages
    assert "Email: user@example.invalid" in messages
    assert "MQTT Host: core-mosquitto:1883" in messages
    if automatic:
        assert "Electrometer ID: auto-detect" in messages
        assert "automatic detection enabled" in messages
    else:
        assert "Configured electrometers: 1" in messages
        assert "electrometer_id: 123, ean: **************6789" in messages
    assert "Received signal" in messages
    assert "Orchestrator cancelled" in messages
    assert "Shutting down..." in messages
    assert "MQTT publisher stopped, availability=offline" in messages
    assert "cez-secret" not in messages
    assert "859182400123456789" not in messages
    auth.close.assert_awaited_once()
    raw.disconnect.assert_called_once()
    assert removed.call_count == 2


def test_failed_offline_publish_does_not_log_success(caplog):
    raw = MagicMock()
    publisher = MqttPublisher(raw, electrometer_id="123")
    publisher.start()
    raw.publish.side_effect = ConnectionError("broker unavailable")
    with caplog.at_level(logging.INFO), pytest.raises(ConnectionError):
        publisher.stop()
    raw.disconnect.assert_called_once()
    assert "MQTT publisher stopped, availability=offline" not in caplog.text
