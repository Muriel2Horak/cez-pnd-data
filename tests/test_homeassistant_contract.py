"""Run separately with Home Assistant installed; use its real discovery schemas."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

mqtt_sensor = pytest.importorskip("homeassistant.components.mqtt.sensor")
mqtt_binary = pytest.importorskip("homeassistant.components.mqtt.binary_sensor")

from addon.src.hdo_parser import UNKNOWN_HDO  # noqa: E402
from addon.src.mqtt_publisher import MqttPublisher  # noqa: E402


def discovery_cases():
    client = MagicMock()
    publisher = MqttPublisher(
        client,
        electrometers=[
            {"electrometer_id": "123", "ean": "859182400123456789"},
            {"electrometer_id": "456", "ean": ""},
        ],
    )
    publisher.publish_discovery()
    return [
        pytest.param(call.args[0], json.loads(call.kwargs["payload"]), id=call.args[0])
        for call in client.publish.call_args_list
        if call.args[0].endswith("/config") and call.kwargs["payload"]
    ]


@pytest.mark.parametrize("topic,payload", discovery_cases())
def test_homeassistant_accepts_every_discovery_payload(topic, payload):
    schema = (
        mqtt_binary.DISCOVERY_SCHEMA
        if "/binary_sensor/" in topic
        else mqtt_sensor.DISCOVERY_SCHEMA
    )
    schema(payload)


def test_homeassistant_accepts_hdo_discovery_and_unknown_payloads():
    client = MagicMock()
    publisher = MqttPublisher(client, electrometer_id="123")
    publisher.publish_hdo_discovery()
    configs = [
        (call.args[0], json.loads(call.kwargs["payload"]))
        for call in client.publish.call_args_list
        if call.kwargs["payload"]
    ]
    assert len(configs) == 5
    binary_config = None
    for topic, payload in configs:
        if "/binary_sensor/" in topic:
            binary_config = mqtt_binary.DISCOVERY_SCHEMA(payload)
        else:
            mqtt_sensor.DISCOVERY_SCHEMA(payload)
    assert binary_config is not None
    client.publish.reset_mock()
    publisher.publish_hdo_state(UNKNOWN_HDO)
    for call in client.publish.call_args_list:
        payload = call.kwargs["payload"]
        assert payload == "None"
        message = SimpleNamespace(payload=payload, topic=call.args[0])
        if "low_tariff" in message.topic:
            entity = SimpleNamespace(
                _expire_after=None,
                _value_template=lambda value: value,
                _config=binary_config,
                _attr_is_on=True,
                _delay_listener=None,
            )
            mqtt_binary.MqttBinarySensor._state_message_received(entity, message)
            assert entity._attr_is_on is None
        else:
            entity = SimpleNamespace(
                _expire_after=None, _template=None, _attr_native_value="old"
            )
            mqtt_sensor.MqttSensor._update_state(entity, message)
            assert entity._attr_native_value is None
