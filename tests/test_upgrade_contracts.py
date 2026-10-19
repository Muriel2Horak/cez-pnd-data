"""Public MQTT contracts and safe ordering during the 0.5.0 upgrade."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from addon.src.hdo_parser import UNKNOWN_HDO, HdoData
from addon.src.mqtt_publisher import MqttPublisher

METERS = [{"electrometer_id": "123"}, {"electrometer_id": "456"}]


def messages(client):
    return [
        (call.args[0], call.kwargs["payload"]) for call in client.publish.call_args_list
    ]


def test_legacy_availability_is_cleared_only_after_all_discovery_is_acknowledged(
    caplog,
):
    client = MagicMock()
    publisher = MqttPublisher(client, electrometers=METERS)
    with caplog.at_level("INFO"):
        publisher.start()
    assert messages(client) == [("cez_pnd/availability", "online")]
    assert "manual consumers must migrate" in caplog.text
    publisher.publish_discovery()
    sent = messages(client)
    configs = [(topic, payload) for topic, payload in sent if topic.endswith("/config")]
    assert len(configs) == 36
    assert all(payload for _, payload in configs)
    assert sent[-2:] == [
        ("cez_pnd/123/availability", ""),
        ("cez_pnd/456/availability", ""),
    ]


@pytest.mark.parametrize(
    "failed_topic",
    [
        "homeassistant/sensor/cez_pnd_123/consumption/config",
        "homeassistant/sensor/cez_pnd_456/hdo_signal/config",
        "homeassistant/binary_sensor/cez_pnd_456/hdo_low_tariff_active/config",
    ],
)
def test_discovery_failure_keeps_legacy_availability(failed_topic):
    client = MagicMock()
    publisher = MqttPublisher(client, electrometers=METERS)
    publisher.start()

    def publish(topic, **kwargs):
        if topic == failed_topic:
            raise TimeoutError("PUBACK timed out")

    client.publish.side_effect = publish
    with pytest.raises(TimeoutError):
        publisher.publish_discovery()
    assert not any(payload == "" for _, payload in messages(client))


def test_hdo_keeps_legacy_identity_and_adds_distinct_optional_binary():
    client = MagicMock()
    publisher = MqttPublisher(client, electrometers=METERS)
    publisher.publish_hdo_discovery()
    configs = {topic: json.loads(payload) for topic, payload in messages(client)}
    assert len(configs) == 10
    for meter in ("123", "456"):
        old = configs[
            f"homeassistant/sensor/cez_pnd_{meter}/hdo_low_tariff_active/config"
        ]
        binary = configs[
            f"homeassistant/binary_sensor/cez_pnd_{meter}/hdo_low_tariff_active/config"
        ]
        assert old["unique_id"] == f"cez_pnd_{meter}_hdo_low_tariff_active"
        assert old["device_class"] is None
        assert "payload_on" not in old
        assert binary["unique_id"] == f"{old['unique_id']}_binary"
        assert binary["enabled_by_default"] is False
        assert binary["payload_on"] == "ON"
        assert binary["payload_off"] == "OFF"
        assert (
            old["state_topic"]
            == binary["state_topic"]
            == f"cez_pnd/{meter}/hdo_low_tariff_active/state"
        )
        assert old["device"] == binary["device"]
        assert (
            old["availability_topic"]
            == binary["availability_topic"]
            == "cez_pnd/availability"
        )


@pytest.mark.parametrize(
    "data,expected",
    [
        (HdoData(True, None, [("00:00", "24:00")], "TEST"), "ON"),
        (HdoData(False, None, [("00:00", "08:00")], "TEST"), "OFF"),
        (UNKNOWN_HDO, "None"),
    ],
)
def test_both_hdo_variants_use_the_same_state_message(data, expected):
    client = MagicMock()
    publisher = MqttPublisher(client, electrometer_id="123")
    publisher.publish_hdo_state(data)
    assert dict(messages(client))["cez_pnd/123/hdo_low_tariff_active/state"] == expected


def test_repeated_discovery_keeps_same_topics_and_identities():
    client = MagicMock()
    publisher = MqttPublisher(client, electrometers=METERS)
    publisher.publish_discovery()
    first = messages(client)
    client.publish.reset_mock()
    publisher.publish_discovery()
    assert messages(client) == first
    unique_ids = [
        json.loads(payload)["unique_id"]
        for topic, payload in first
        if topic.endswith("/config")
    ]
    assert len(unique_ids) == len(set(unique_ids)) == 36
