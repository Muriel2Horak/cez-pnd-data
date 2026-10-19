"""RV reserved-power values and reactive quadrant values keep their source scale."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from addon.src.mqtt_publisher import MqttPublisher, get_sensor_definitions
from addon.src.orchestrator import Orchestrator, OrchestratorConfig
from addon.src.parser import CezDataParser


@pytest.mark.asyncio
async def test_captured_rv_value_reaches_legacy_mqtt_topic_without_conversion():
    payload = json.loads(
        (
            Path(__file__).resolve().parents[1] / "evidence/pnd-playwright-data.json"
        ).read_text()
    )
    rv = next(col for col in payload["columns"] if col["name"] == "Rv/784703")
    assert rv["unit"] == "kW"
    assert payload["values"][-1][rv["id"]]["v"] == "5,46"
    parser = CezDataParser(payload)
    assert parser.reactive_col_id == rv["id"]
    assert parser.get_latest_reading().reactive_kw == 5.46
    assert parser.get_latest_reading_dict()["reactive_kw"] == 5.46

    client = MagicMock()
    publisher = MqttPublisher(client, electrometer_id="784703")
    auth = SimpleNamespace(
        ensure_session=AsyncMock(return_value=SimpleNamespace(cookies=[]))
    )
    orchestrator = Orchestrator(
        OrchestratorConfig([{"electrometer_id": "784703", "ean": ""}]),
        auth,
        AsyncMock(),
        publisher,
        batch_fetcher=AsyncMock(return_value={"profile_all": payload}),
    )
    await orchestrator.run_once()
    sent = {
        call.args[0]: call.kwargs["payload"] for call in client.publish.call_args_list
    }
    assert sent["cez_pnd/784703/reactive/state"] == "5.46"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "profile,key",
    [
        ("Profil +Ri", "reactive_import_inductive"),
        ("Profil -Rc", "reactive_export_capacitive"),
        ("Profil -Ri", "reactive_export_inductive"),
        ("Profil +Rc", "reactive_import_capacitive"),
    ],
)
async def test_reactive_quadrants_keep_source_kvar_scale_and_mqtt_identity(
    profile, key
):
    payload = {
        "hasData": True,
        "columns": [
            {"id": "t", "name": "Datum"},
            {"id": "q", "name": profile, "unit": "kVAr"},
        ],
        "values": [{"t": {"v": "14.02.2026 00:15"}, "q": {"v": "0,31"}}],
    }
    client = MagicMock()
    orchestrator = Orchestrator(
        OrchestratorConfig([{"electrometer_id": "123", "ean": ""}]),
        SimpleNamespace(
            ensure_session=AsyncMock(return_value=SimpleNamespace(cookies=[]))
        ),
        AsyncMock(),
        MqttPublisher(client, electrometer_id="123"),
        batch_fetcher=AsyncMock(return_value={"quadrant": payload}),
    )
    await orchestrator.run_once()
    client.publish.assert_called_once_with(
        f"cez_pnd/123/{key}/state", payload="0.31", qos=1, retain=True
    )
    definition = next(d for d in get_sensor_definitions() if d.key == key)
    assert definition.device_class == "reactive_power"
    assert definition.unit_of_measurement == "kvar"
    client.reset_mock()
    MqttPublisher(client, electrometer_id="123").publish_discovery()
    topic = f"homeassistant/sensor/cez_pnd_123/{key}/config"
    configs = {
        call.args[0]: json.loads(call.kwargs["payload"])
        for call in client.publish.call_args_list
        if call.kwargs["payload"] and call.args[0].endswith("/config")
    }
    config = configs[topic]
    assert config["unit_of_measurement"] == "kvar"
    assert config["unique_id"] == f"cez_pnd_123_{key}"
    assert config["state_topic"] == f"cez_pnd/123/{key}/state"
