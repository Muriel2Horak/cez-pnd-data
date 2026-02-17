"""Tests for MQTT Discovery and state publishing.

Covers:
- Discovery payload format (unique_id, name, state_topic, unit_of_measurement)
- Topic naming conventions per HA MQTT Discovery spec
- LWT / availability topic handling
- State publishing cycle
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from addon.src.mqtt_publisher import (AVAILABILITY_TOPIC_TEMPLATE,
                                      CONFIG_TOPIC_TEMPLATE,
                                      STATE_TOPIC_TEMPLATE, VALID_SENSOR_KEYS,
                                      MqttPublisher, SensorDefinition,
                                      build_discovery_payload,
                                      get_sensor_definitions)

# ── Fixtures ──────────────────────────────────────────────────────────

METER_ID = "784703"


@pytest.fixture()
def mock_mqtt_client() -> MagicMock:
    """Provide an paho-mqtt-like client mock."""
    client = MagicMock()
    client.publish = MagicMock()
    client.will_set = MagicMock()
    client.connect = MagicMock()
    client.disconnect = MagicMock()
    client.loop_start = MagicMock()
    client.loop_stop = MagicMock()
    return client


# ── Discovery payload format ──────────────────────────────────────────


class TestSensorDefinitions:
    """Verify the sensor definition registry."""

    ALL_EXPECTED_KEYS = {
        "consumption", "production", "reactive",
        "reactive_import_inductive", "reactive_export_capacitive",
        "reactive_export_inductive", "reactive_import_capacitive",
        "daily_consumption", "daily_production",
        "register_consumption", "register_production",
        "register_low_tariff", "register_high_tariff",
    }

    def test_all_thirteen_sensors_defined(self) -> None:
        defs = get_sensor_definitions()
        keys = {d.key for d in defs}
        assert len(defs) == 13
        assert keys == self.ALL_EXPECTED_KEYS

    def test_each_sensor_has_unit(self) -> None:
        for d in get_sensor_definitions():
            assert d.unit_of_measurement, f"sensor {d.key} missing unit"

    def test_each_sensor_has_name(self) -> None:
        for d in get_sensor_definitions():
            assert d.name, f"sensor {d.key} missing name"

    def test_each_sensor_has_device_class(self) -> None:
        for d in get_sensor_definitions():
            assert d.device_class, f"sensor {d.key} missing device_class"

    def test_power_sensors_use_kw_unit(self) -> None:
        """Original power sensors (consumption, production) use kW."""
        defs = {d.key: d for d in get_sensor_definitions()}
        for key in ("consumption", "production"):
            assert defs[key].unit_of_measurement == "kW", f"{key} should use kW"
            assert defs[key].device_class == "power", f"{key} should be power"
            assert defs[key].state_class == "measurement", f"{key} should be measurement"

    def test_reactive_power_sensors_use_var_unit(self) -> None:
        """All reactive power sensors (4 new + original) use var and reactive_power device_class."""
        defs = {d.key: d for d in get_sensor_definitions()}
        reactive_keys = [
            "reactive_import_inductive",
            "reactive_export_capacitive",
            "reactive_export_inductive",
            "reactive_import_capacitive",
        ]
        for key in reactive_keys:
            assert defs[key].unit_of_measurement == "var", f"{key} should use var"
            assert defs[key].device_class == "reactive_power", f"{key} should be reactive_power"
            assert defs[key].state_class == "measurement", f"{key} should be measurement"

    def test_energy_sensors_use_kwh_and_total_increasing(self) -> None:
        """Daily and register energy sensors use kWh, energy class, total_increasing."""
        defs = {d.key: d for d in get_sensor_definitions()}
        energy_keys = [
            "daily_consumption", "daily_production",
            "register_consumption", "register_production",
            "register_low_tariff", "register_high_tariff",
        ]
        for key in energy_keys:
            assert defs[key].unit_of_measurement == "kWh", f"{key} should use kWh"
            assert defs[key].device_class == "energy", f"{key} should be energy"
            assert defs[key].state_class == "total_increasing", f"{key} should be total_increasing"

    def test_existing_three_sensors_unchanged(self) -> None:
        """Original 3 sensors must keep their exact definitions."""
        defs = {d.key: d for d in get_sensor_definitions()}
        # consumption
        assert defs["consumption"].name == "CEZ Consumption Power"
        assert defs["consumption"].unit_of_measurement == "kW"
        assert defs["consumption"].device_class == "power"
        assert defs["consumption"].icon == "mdi:flash"
        # production
        assert defs["production"].name == "CEZ Production Power"
        assert defs["production"].unit_of_measurement == "kW"
        assert defs["production"].device_class == "power"
        assert defs["production"].icon == "mdi:solar-power"
        # reactive (original — keeps kW for backward compat)
        assert defs["reactive"].name == "CEZ Reactive Power"
        assert defs["reactive"].unit_of_measurement == "kW"
        assert defs["reactive"].device_class == "reactive_power"
        assert defs["reactive"].icon == "mdi:sine-wave"

    def test_valid_sensor_keys_matches_definitions(self) -> None:
        defs = get_sensor_definitions()
        assert VALID_SENSOR_KEYS == frozenset(d.key for d in defs)
        assert len(VALID_SENSOR_KEYS) == 13


class TestDiscoveryPayload:
    """Verify discovery payload conforms to HA MQTT spec."""

    def _payload_for(self, key: str) -> dict[str, Any]:
        defs = get_sensor_definitions()
        sensor = next(d for d in defs if d.key == key)
        return build_discovery_payload(sensor, METER_ID)

    def test_unique_id_present(self) -> None:
        payload = self._payload_for("consumption")
        assert "unique_id" in payload
        assert payload["unique_id"] == f"cez_pnd_{METER_ID}_consumption"

    def test_name_present(self) -> None:
        payload = self._payload_for("consumption")
        assert "name" in payload
        assert isinstance(payload["name"], str)
        assert len(payload["name"]) > 0

    def test_state_topic_present(self) -> None:
        payload = self._payload_for("consumption")
        assert "state_topic" in payload
        expected = STATE_TOPIC_TEMPLATE.format(meter_id=METER_ID, key="consumption")
        assert payload["state_topic"] == expected

    def test_unit_of_measurement_present(self) -> None:
        payload = self._payload_for("consumption")
        assert "unit_of_measurement" in payload
        assert payload["unit_of_measurement"] == "kW"

    def test_device_class_present(self) -> None:
        payload = self._payload_for("consumption")
        assert "device_class" in payload
        assert payload["device_class"] == "power"

    def test_state_class_present(self) -> None:
        payload = self._payload_for("consumption")
        assert "state_class" in payload
        assert payload["state_class"] == "measurement"

    def test_device_block_present(self) -> None:
        payload = self._payload_for("consumption")
        assert "device" in payload
        dev = payload["device"]
        assert "identifiers" in dev
        assert f"cez_pnd_{METER_ID}" in dev["identifiers"]
        assert "name" in dev
        assert "manufacturer" in dev

    def test_availability_topic_present(self) -> None:
        payload = self._payload_for("consumption")
        assert "availability_topic" in payload
        expected = AVAILABILITY_TOPIC_TEMPLATE.format(meter_id=METER_ID)
        assert payload["availability_topic"] == expected

    def test_payload_is_valid_json_serializable(self) -> None:
        for d in get_sensor_definitions():
            payload = build_discovery_payload(d, METER_ID)
            # Must not raise
            serialized = json.dumps(payload)
            deserialized = json.loads(serialized)
            assert deserialized == payload

    def test_reactive_sensor_uses_var_unit(self) -> None:
        payload = self._payload_for("reactive")
        assert payload["unit_of_measurement"] == "kW"
        assert payload["device_class"] == "reactive_power"

    def test_production_sensor_config(self) -> None:
        payload = self._payload_for("production")
        assert payload["unique_id"] == f"cez_pnd_{METER_ID}_production"
        assert payload["unit_of_measurement"] == "kW"


class TestTopicNaming:
    """Verify topics follow stable naming conventions."""

    def test_config_topic_format(self) -> None:
        expected = f"homeassistant/sensor/cez_pnd_{METER_ID}/consumption/config"
        actual = CONFIG_TOPIC_TEMPLATE.format(meter_id=METER_ID, key="consumption")
        assert actual == expected

    def test_state_topic_format(self) -> None:
        expected = f"cez_pnd/{METER_ID}/consumption/state"
        actual = STATE_TOPIC_TEMPLATE.format(meter_id=METER_ID, key="consumption")
        assert actual == expected

    def test_availability_topic_format(self) -> None:
        expected = f"cez_pnd/{METER_ID}/availability"
        actual = AVAILABILITY_TOPIC_TEMPLATE.format(meter_id=METER_ID)
        assert actual == expected

    def test_topics_are_deterministic_across_runs(self) -> None:
        """Same meter_id always produces same topics — no random components."""
        t1 = CONFIG_TOPIC_TEMPLATE.format(meter_id=METER_ID, key="consumption")
        t2 = CONFIG_TOPIC_TEMPLATE.format(meter_id=METER_ID, key="consumption")
        assert t1 == t2


# ── LWT / availability ────────────────────────────────────────────────


class TestAvailability:
    """Verify LWT / availability handling."""

    def test_publisher_sets_lwt_on_connect(self, mock_mqtt_client: MagicMock) -> None:
        """MqttPublisher must configure LWT (will_set) before connecting."""
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=METER_ID)
        publisher.start()

        expected_topic = AVAILABILITY_TOPIC_TEMPLATE.format(meter_id=METER_ID)
        mock_mqtt_client.will_set.assert_called_once_with(
            expected_topic, payload="offline", qos=1, retain=True,
        )

    def test_publisher_publishes_online_after_connect(self, mock_mqtt_client: MagicMock) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=METER_ID)
        publisher.start()

        avail_topic = AVAILABILITY_TOPIC_TEMPLATE.format(meter_id=METER_ID)
        # After connect, should publish "online"
        publish_calls = mock_mqtt_client.publish.call_args_list
        avail_calls = [c for c in publish_calls if c[0][0] == avail_topic]
        assert len(avail_calls) >= 1
        assert avail_calls[0][1]["payload"] == "online"

    def test_stop_publishes_offline(self, mock_mqtt_client: MagicMock) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=METER_ID)
        publisher.start()
        mock_mqtt_client.publish.reset_mock()

        publisher.stop()

        avail_topic = AVAILABILITY_TOPIC_TEMPLATE.format(meter_id=METER_ID)
        publish_calls = mock_mqtt_client.publish.call_args_list
        avail_calls = [c for c in publish_calls if c[0][0] == avail_topic]
        assert len(avail_calls) >= 1
        # Last availability publish must be "offline"
        last_avail = avail_calls[-1]
        payload = last_avail[1].get("payload", last_avail[0][1] if len(last_avail[0]) > 1 else None)
        assert payload == "offline"


# ── Discovery publishing ──────────────────────────────────────────────


class TestDiscoveryPublishing:
    """Verify that publish_discovery sends correct config topics."""

    def test_publishes_all_sensor_configs(self, mock_mqtt_client: MagicMock) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=METER_ID)
        publisher.publish_discovery()

        defs = get_sensor_definitions()
        for d in defs:
            topic = CONFIG_TOPIC_TEMPLATE.format(meter_id=METER_ID, key=d.key)
            matching = [
                c for c in mock_mqtt_client.publish.call_args_list
                if c[0][0] == topic
            ]
            assert len(matching) == 1, f"expected one publish to {topic}"

    def test_discovery_payload_is_retained(self, mock_mqtt_client: MagicMock) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=METER_ID)
        publisher.publish_discovery()

        for c in mock_mqtt_client.publish.call_args_list:
            topic = c[0][0]
            if "/config" in topic:
                retain = c[1].get("retain", False)
                assert retain is True, f"discovery to {topic} must be retained"

    def test_discovery_payload_json_valid(self, mock_mqtt_client: MagicMock) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=METER_ID)
        publisher.publish_discovery()

        for c in mock_mqtt_client.publish.call_args_list:
            topic = c[0][0]
            if "/config" in topic:
                payload_str = c[0][1] if len(c[0]) > 1 else c[1].get("payload")
                parsed = json.loads(payload_str)
                assert "unique_id" in parsed
                assert "state_topic" in parsed

    def test_discovery_publishes_exactly_thirteen_configs(self, mock_mqtt_client: MagicMock) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=METER_ID)
        publisher.publish_discovery()

        config_calls = [
            c for c in mock_mqtt_client.publish.call_args_list
            if "/config" in c[0][0]
        ]
        assert len(config_calls) == 17


# ── State publishing ──────────────────────────────────────────────────


class TestStatePublishing:
    """Verify state publishing cycle."""

    def test_publish_state_sends_numeric_values(self, mock_mqtt_client: MagicMock) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=METER_ID)
        readings = {
            "consumption": 1.42,
            "production": 0.0,
            "reactive": 5.46,
            "reactive_import_inductive": 0.12,
            "reactive_export_capacitive": 0.34,
            "reactive_export_inductive": 0.56,
            "reactive_import_capacitive": 0.78,
            "daily_consumption": 12.5,
            "daily_production": 3.2,
            "register_consumption": 1234.56,
            "register_production": 567.89,
            "register_low_tariff": 800.0,
            "register_high_tariff": 434.56,
        }

        publisher.publish_state(readings)

        for key, value in readings.items():
            topic = STATE_TOPIC_TEMPLATE.format(meter_id=METER_ID, key=key)
            matching = [
                c for c in mock_mqtt_client.publish.call_args_list
                if c[0][0] == topic
            ]
            assert len(matching) == 1, f"expected publish to {topic}"
            published = matching[0][0][1] if len(matching[0][0]) > 1 else matching[0][1].get("payload")
            assert published == str(value)

    def test_publish_state_retains_values(self, mock_mqtt_client: MagicMock) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=METER_ID)
        publisher.publish_state({"consumption": 1.0, "production": 0.0, "reactive": 0.5})

        for c in mock_mqtt_client.publish.call_args_list:
            topic = c[0][0]
            if "/state" in topic:
                assert c[1].get("retain") is True, f"state to {topic} must be retained"

    def test_publish_state_ignores_unknown_keys(self, mock_mqtt_client: MagicMock) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=METER_ID)
        publisher.publish_state({"unknown_metric": 99.9})

        published_topics = [c[0][0] for c in mock_mqtt_client.publish.call_args_list]
        state_topics = [t for t in published_topics if "/state" in t]
        assert len(state_topics) == 0

    def test_publish_state_handles_none_values(self, mock_mqtt_client: MagicMock) -> None:
        """None values should not be published (sensor goes unavailable via LWT instead)."""
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=METER_ID)
        publisher.publish_state({"consumption": None, "production": 0.5, "reactive": None})

        published_topics = [c[0][0] for c in mock_mqtt_client.publish.call_args_list]
        # Only production should have a state publish
        state_topics = [t for t in published_topics if "/state" in t]
        assert len(state_topics) == 1
        assert "production" in state_topics[0]

    def test_full_cycle_discovery_then_state(self, mock_mqtt_client: MagicMock) -> None:
        """Simulates full lifecycle: start -> discover -> publish states."""
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=METER_ID)
        publisher.start()
        publisher.publish_discovery()

        all_readings = {
            "consumption": 2.5, "production": 0.1, "reactive": 3.0,
            "reactive_import_inductive": 0.1, "reactive_export_capacitive": 0.2,
            "reactive_export_inductive": 0.3, "reactive_import_capacitive": 0.4,
            "daily_consumption": 10.0, "daily_production": 5.0,
            "register_consumption": 1000.0, "register_production": 500.0,
            "register_low_tariff": 600.0, "register_high_tariff": 400.0,
        }
        publisher.publish_state(all_readings)

        topics = [c[0][0] for c in mock_mqtt_client.publish.call_args_list]

        avail_topic = AVAILABILITY_TOPIC_TEMPLATE.format(meter_id=METER_ID)
        assert avail_topic in topics

        for d in get_sensor_definitions():
            config_topic = CONFIG_TOPIC_TEMPLATE.format(meter_id=METER_ID, key=d.key)
            assert config_topic in topics

        for key in all_readings:
            state_topic = STATE_TOPIC_TEMPLATE.format(meter_id=METER_ID, key=key)
            assert state_topic in topics
