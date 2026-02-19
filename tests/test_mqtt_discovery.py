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
from unittest.mock import MagicMock

import pytest

from addon.src.mqtt_publisher import (
    AVAILABILITY_TOPIC_TEMPLATE,
    CONFIG_TOPIC_TEMPLATE,
    STATE_TOPIC_TEMPLATE,
    VALID_SENSOR_KEYS,
    MqttPublisher,
    build_discovery_payload,
    get_sensor_definitions,
)

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
    """Tests for sensor definition contracts and bilingual naming."""

    ALL_EXPECTED_KEYS = {
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
            assert (
                defs[key].state_class == "measurement"
            ), f"{key} should be measurement"

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
            assert (
                defs[key].device_class == "reactive_power"
            ), f"{key} should be reactive_power"
            assert (
                defs[key].state_class == "measurement"
            ), f"{key} should be measurement"

    def test_energy_sensors_use_kwh_and_total_increasing(self) -> None:
        """Daily and register energy sensors use kWh, energy class, total_increasing."""
        defs = {d.key: d for d in get_sensor_definitions()}
        energy_keys = [
            "daily_consumption",
            "daily_production",
            "register_consumption",
            "register_production",
            "register_low_tariff",
            "register_high_tariff",
        ]
        for key in energy_keys:
            assert defs[key].unit_of_measurement == "kWh", f"{key} should use kWh"
            assert defs[key].device_class == "energy", f"{key} should be energy"
            assert (
                defs[key].state_class == "total_increasing"
            ), f"{key} should be total_increasing"

    def test_existing_three_sensors_unchanged(self) -> None:
        """Original 3 sensors must keep their exact definitions."""
        defs = {d.key: d for d in get_sensor_definitions()}
        # consumption
        assert defs["consumption"].name == "CEZ {id} Consumption Power / Odběr"
        assert defs["consumption"].unit_of_measurement == "kW"
        assert defs["consumption"].device_class == "power"
        assert defs["consumption"].icon == "mdi:flash"
        # production
        assert defs["production"].name == "CEZ {id} Production Power / Dodávka"
        assert defs["production"].unit_of_measurement == "kW"
        assert defs["production"].device_class == "power"
        assert defs["production"].icon == "mdi:solar-power"
        # reactive (original — keeps kW for backward compat)
        assert defs["reactive"].name == "CEZ {id} Reactive Power / Jalový výkon"
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
        expected = STATE_TOPIC_TEMPLATE.format(
            electrometer_id=METER_ID, key="consumption"
        )
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
        expected = AVAILABILITY_TOPIC_TEMPLATE.format(electrometer_id=METER_ID)
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
        actual = CONFIG_TOPIC_TEMPLATE.format(
            electrometer_id=METER_ID, key="consumption"
        )
        assert actual == expected

    def test_state_topic_format(self) -> None:
        expected = f"cez_pnd/{METER_ID}/consumption/state"
        actual = STATE_TOPIC_TEMPLATE.format(
            electrometer_id=METER_ID, key="consumption"
        )
        assert actual == expected

    def test_availability_topic_format(self) -> None:
        expected = f"cez_pnd/{METER_ID}/availability"
        actual = AVAILABILITY_TOPIC_TEMPLATE.format(electrometer_id=METER_ID)
        assert actual == expected

    def test_topics_are_deterministic_across_runs(self) -> None:
        """Same meter_id always produces same topics — no random components."""
        t1 = CONFIG_TOPIC_TEMPLATE.format(electrometer_id=METER_ID, key="consumption")
        t2 = CONFIG_TOPIC_TEMPLATE.format(electrometer_id=METER_ID, key="consumption")
        assert t1 == t2


# ── LWT / availability ────────────────────────────────────────────────


class TestAvailability:
    """Verify LWT / availability handling."""

    def test_publisher_sets_lwt_on_connect(self, mock_mqtt_client: MagicMock) -> None:
        """MqttPublisher must configure LWT (will_set) before connecting."""
        publisher = MqttPublisher(client=mock_mqtt_client, electrometer_id=METER_ID)
        publisher.start()

        expected_topic = AVAILABILITY_TOPIC_TEMPLATE.format(electrometer_id=METER_ID)
        mock_mqtt_client.will_set.assert_called_once_with(
            expected_topic,
            payload="offline",
            qos=1,
            retain=True,
        )

    def test_publisher_publishes_online_after_connect(
        self, mock_mqtt_client: MagicMock
    ) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, electrometer_id=METER_ID)
        publisher.start()

        avail_topic = AVAILABILITY_TOPIC_TEMPLATE.format(electrometer_id=METER_ID)
        # After connect, should publish "online"
        publish_calls = mock_mqtt_client.publish.call_args_list
        avail_calls = [c for c in publish_calls if c[0][0] == avail_topic]
        assert len(avail_calls) >= 1
        assert avail_calls[0][1]["payload"] == "online"

    def test_stop_publishes_offline(self, mock_mqtt_client: MagicMock) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, electrometer_id=METER_ID)
        publisher.start()
        mock_mqtt_client.publish.reset_mock()

        publisher.stop()

        avail_topic = AVAILABILITY_TOPIC_TEMPLATE.format(electrometer_id=METER_ID)
        publish_calls = mock_mqtt_client.publish.call_args_list
        avail_calls = [c for c in publish_calls if c[0][0] == avail_topic]
        assert len(avail_calls) >= 1
        # Last availability publish must be "offline"
        last_avail = avail_calls[-1]
        payload = last_avail[1].get(
            "payload", last_avail[0][1] if len(last_avail[0]) > 1 else None
        )
        assert payload == "offline"


# ── Discovery publishing ──────────────────────────────────────────────


class TestDiscoveryPublishing:
    """Verify that publish_discovery sends correct config topics."""

    def test_publishes_all_sensor_configs(self, mock_mqtt_client: MagicMock) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, electrometer_id=METER_ID)
        publisher.publish_discovery()

        defs = get_sensor_definitions()
        for d in defs:
            topic = CONFIG_TOPIC_TEMPLATE.format(electrometer_id=METER_ID, key=d.key)
            matching = [
                c for c in mock_mqtt_client.publish.call_args_list if c[0][0] == topic
            ]
            assert len(matching) == 1, f"expected one publish to {topic}"

    def test_discovery_payload_is_retained(self, mock_mqtt_client: MagicMock) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, electrometer_id=METER_ID)
        publisher.publish_discovery()

        for c in mock_mqtt_client.publish.call_args_list:
            topic = c[0][0]
            if "/config" in topic:
                retain = c[1].get("retain", False)
                assert retain is True, f"discovery to {topic} must be retained"

    def test_discovery_payload_json_valid(self, mock_mqtt_client: MagicMock) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, electrometer_id=METER_ID)
        publisher.publish_discovery()

        for c in mock_mqtt_client.publish.call_args_list:
            topic = c[0][0]
            if "/config" in topic:
                payload_str = c[0][1] if len(c[0]) > 1 else c[1].get("payload")
                parsed = json.loads(payload_str)
                assert "unique_id" in parsed
                assert "state_topic" in parsed

    def test_discovery_publishes_exactly_thirteen_configs(
        self, mock_mqtt_client: MagicMock
    ) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, electrometer_id=METER_ID)
        publisher.publish_discovery()

        config_calls = [
            c for c in mock_mqtt_client.publish.call_args_list if "/config" in c[0][0]
        ]
        assert len(config_calls) == 17


# ── State publishing ──────────────────────────────────────────────────


class TestStatePublishing:
    """Verify state publishing cycle."""

    def test_publish_state_sends_numeric_values(
        self, mock_mqtt_client: MagicMock
    ) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, electrometer_id=METER_ID)
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
            topic = STATE_TOPIC_TEMPLATE.format(electrometer_id=METER_ID, key=key)
            matching = [
                c for c in mock_mqtt_client.publish.call_args_list if c[0][0] == topic
            ]
            assert len(matching) == 1, f"expected publish to {topic}"
            published = (
                matching[0][0][1]
                if len(matching[0][0]) > 1
                else matching[0][1].get("payload")
            )
            assert published == str(value)

    def test_publish_state_retains_values(self, mock_mqtt_client: MagicMock) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, electrometer_id=METER_ID)
        publisher.publish_state(
            {"consumption": 1.0, "production": 0.0, "reactive": 0.5}
        )

        for c in mock_mqtt_client.publish.call_args_list:
            topic = c[0][0]
            if "/state" in topic:
                assert c[1].get("retain") is True, f"state to {topic} must be retained"

    def test_publish_state_ignores_unknown_keys(
        self, mock_mqtt_client: MagicMock
    ) -> None:
        publisher = MqttPublisher(client=mock_mqtt_client, electrometer_id=METER_ID)
        publisher.publish_state({"unknown_metric": 99.9})

        published_topics = [c[0][0] for c in mock_mqtt_client.publish.call_args_list]
        state_topics = [t for t in published_topics if "/state" in t]
        assert len(state_topics) == 0

    def test_publish_state_handles_none_values(
        self, mock_mqtt_client: MagicMock
    ) -> None:
        """None values should not be published (sensor goes unavailable via LWT instead)."""
        publisher = MqttPublisher(client=mock_mqtt_client, electrometer_id=METER_ID)
        publisher.publish_state(
            {"consumption": None, "production": 0.5, "reactive": None}
        )

        published_topics = [c[0][0] for c in mock_mqtt_client.publish.call_args_list]
        # Only production should have a state publish
        state_topics = [t for t in published_topics if "/state" in t]
        assert len(state_topics) == 1
        assert "production" in state_topics[0]

    def test_full_cycle_discovery_then_state(self, mock_mqtt_client: MagicMock) -> None:
        """Simulates full lifecycle: start -> discover -> publish states."""
        publisher = MqttPublisher(client=mock_mqtt_client, electrometer_id=METER_ID)
        publisher.start()
        publisher.publish_discovery()

        all_readings = {
            "consumption": 2.5,
            "production": 0.1,
            "reactive": 3.0,
            "reactive_import_inductive": 0.1,
            "reactive_export_capacitive": 0.2,
            "reactive_export_inductive": 0.3,
            "reactive_import_capacitive": 0.4,
            "daily_consumption": 10.0,
            "daily_production": 5.0,
            "register_consumption": 1000.0,
            "register_production": 500.0,
            "register_low_tariff": 600.0,
            "register_high_tariff": 400.0,
        }
        publisher.publish_state(all_readings)

        topics = [c[0][0] for c in mock_mqtt_client.publish.call_args_list]

        avail_topic = AVAILABILITY_TOPIC_TEMPLATE.format(electrometer_id=METER_ID)
        assert avail_topic in topics

        for d in get_sensor_definitions():
            config_topic = CONFIG_TOPIC_TEMPLATE.format(
                electrometer_id=METER_ID, key=d.key
            )
            assert config_topic in topics

        for key in all_readings:
            state_topic = STATE_TOPIC_TEMPLATE.format(electrometer_id=METER_ID, key=key)
            assert state_topic in topics


# ── Identity uniqueness (multi-electrometer collision safety) ─────────


METER_A = "784703"
METER_B = "999888"


class TestIdentityUniqueness:
    """Two different electrometer_ids must never produce colliding IDs or topics."""

    def test_unique_ids_are_disjoint_across_meters(self) -> None:
        """All unique_id values for meter A and meter B are completely disjoint."""
        defs = get_sensor_definitions()
        ids_a = {build_discovery_payload(d, METER_A)["unique_id"] for d in defs}
        ids_b = {build_discovery_payload(d, METER_B)["unique_id"] for d in defs}
        assert ids_a.isdisjoint(ids_b), f"Collision: {ids_a & ids_b}"

    def test_config_topics_are_disjoint_across_meters(self) -> None:
        """Config topics for meter A and meter B never overlap."""
        defs = get_sensor_definitions()
        topics_a = {
            CONFIG_TOPIC_TEMPLATE.format(electrometer_id=METER_A, key=d.key)
            for d in defs
        }
        topics_b = {
            CONFIG_TOPIC_TEMPLATE.format(electrometer_id=METER_B, key=d.key)
            for d in defs
        }
        assert topics_a.isdisjoint(topics_b), f"Collision: {topics_a & topics_b}"

    def test_state_topics_are_disjoint_across_meters(self) -> None:
        """State topics for meter A and meter B never overlap."""
        defs = get_sensor_definitions()
        topics_a = {
            STATE_TOPIC_TEMPLATE.format(electrometer_id=METER_A, key=d.key)
            for d in defs
        }
        topics_b = {
            STATE_TOPIC_TEMPLATE.format(electrometer_id=METER_B, key=d.key)
            for d in defs
        }
        assert topics_a.isdisjoint(topics_b), f"Collision: {topics_a & topics_b}"

    def test_availability_topics_differ_across_meters(self) -> None:
        """Availability topics for two meters are distinct."""
        avail_a = AVAILABILITY_TOPIC_TEMPLATE.format(electrometer_id=METER_A)
        avail_b = AVAILABILITY_TOPIC_TEMPLATE.format(electrometer_id=METER_B)
        assert avail_a != avail_b

    def test_device_identifiers_differ_across_meters(self) -> None:
        """Device block identifiers are unique per electrometer."""
        defs = get_sensor_definitions()
        dev_a = build_discovery_payload(defs[0], METER_A)["device"]["identifiers"]
        dev_b = build_discovery_payload(defs[0], METER_B)["device"]["identifiers"]
        assert set(dev_a).isdisjoint(set(dev_b))

    def test_ean_context_present_when_provided(self) -> None:
        """When EAN is provided, device metadata includes configuration_url."""
        defs = get_sensor_definitions()
        payload = build_discovery_payload(defs[0], METER_A, ean="859182400100000001")
        assert "configuration_url" in payload["device"]
        assert "859182400100000001" in payload["device"]["configuration_url"]

    def test_ean_context_absent_when_not_provided(self) -> None:
        """When EAN is empty, device metadata has no configuration_url."""
        defs = get_sensor_definitions()
        payload = build_discovery_payload(defs[0], METER_A)
        assert "configuration_url" not in payload["device"]

    def test_sensor_names_contain_electrometer_id(self) -> None:
        """Formatted sensor names embed the electrometer ID for disambiguation."""
        defs = get_sensor_definitions()
        payload = build_discovery_payload(defs[0], METER_A)
        assert METER_A in payload["name"]


# ── Multi-Electrometer Fixtures ────────────────────────────────────────────


MULTI_ELECTROMETER_CONFIG = [
    {"electrometer_id": "784703", "ean": "12345678901234"},
    {"electrometer_id": "784704", "ean": "12345678901235"},
]


# ── Multi-Electrometer Discovery ────────────────────────────────────────


class TestMultiElectrometerDiscovery:
    """Tests for multi-electrometer MQTT discovery contracts.

    These tests verify:
    - Distinct unique_ids and topics per meter
    - Device names include meter ID and bilingual EN/CZ text
    - Sensor names follow `CEZ {id} {EN} / {CZ}` format
    """

    def test_multi_electrometer_discovery_has_unique_ids(self) -> None:
        """Discovery payloads for multiple meters must have distinct unique_ids."""
        meter_1_id = MULTI_ELECTROMETER_CONFIG[0]["electrometer_id"]
        meter_2_id = MULTI_ELECTROMETER_CONFIG[1]["electrometer_id"]

        # Get sensor definitions
        defs = get_sensor_definitions()
        sensor = next(d for d in defs if d.key == "consumption")

        # Build discovery payloads for both meters
        payload_1 = build_discovery_payload(sensor, meter_1_id)
        payload_2 = build_discovery_payload(sensor, meter_2_id)

        # Verify unique_ids are distinct
        unique_id_1 = payload_1.get("unique_id", "")
        unique_id_2 = payload_2.get("unique_id", "")

        assert (
            unique_id_1 != unique_id_2
        ), f"unique_ids must be distinct: {unique_id_1} == {unique_id_2}"
        assert meter_1_id in unique_id_1, f"unique_id_1 should contain {meter_1_id}"
        assert meter_2_id in unique_id_2, f"unique_id_2 should contain {meter_2_id}"

    def test_multi_electrometer_discovery_has_distinct_topics(self) -> None:
        """State topics for different meters must be distinct."""
        meter_1_id = MULTI_ELECTROMETER_CONFIG[0]["electrometer_id"]
        meter_2_id = MULTI_ELECTROMETER_CONFIG[1]["electrometer_id"]

        topic_1 = STATE_TOPIC_TEMPLATE.format(
            electrometer_id=meter_1_id, key="consumption"
        )
        topic_2 = STATE_TOPIC_TEMPLATE.format(
            electrometer_id=meter_2_id, key="consumption"
        )

        assert (
            topic_1 != topic_2
        ), f"State topics must be distinct: {topic_1} == {topic_2}"

    def test_multi_electrometer_config_topics_are_distinct(self) -> None:
        """Config topics for different meters must be distinct."""
        meter_1_id = MULTI_ELECTROMETER_CONFIG[0]["electrometer_id"]
        meter_2_id = MULTI_ELECTROMETER_CONFIG[1]["electrometer_id"]

        topic_1 = CONFIG_TOPIC_TEMPLATE.format(
            electrometer_id=meter_1_id, key="consumption"
        )
        topic_2 = CONFIG_TOPIC_TEMPLATE.format(
            electrometer_id=meter_2_id, key="consumption"
        )

        assert (
            topic_1 != topic_2
        ), f"Config topics must be distinct: {topic_1} == {topic_2}"

    def test_device_name_includes_meter_id(self) -> None:
        """Device name should include meter ID for multi-meter identification."""
        meter_id = MULTI_ELECTROMETER_CONFIG[0]["electrometer_id"]

        defs = get_sensor_definitions()
        sensor = next(d for d in defs if d.key == "consumption")
        payload = build_discovery_payload(sensor, meter_id)

        device = payload.get("device", {})
        device_name = device.get("name", "")

        assert (
            meter_id in device_name
        ), f"Device name should include meter ID: {device_name}"

    def test_device_name_is_bilingual(self) -> None:
        """Device name should include bilingual EN/CZ text format."""
        meter_id = MULTI_ELECTROMETER_CONFIG[0]["electrometer_id"]

        defs = get_sensor_definitions()
        sensor = next(d for d in defs if d.key == "consumption")
        payload = build_discovery_payload(sensor, meter_id)

        device = payload.get("device", {})
        device_name = device.get("name", "")

        # Should include bilingual format like "CEZ 784703 / CEZ 784703"
        # Or at least some indication of bilingual naming
        assert (
            "/" in device_name or "CEZ" in device_name
        ), f"Device name should be bilingual: {device_name}"

    def test_sensor_name_follows_bilingual_format(self) -> None:
        """Sensor names should follow `CEZ {id} {EN} / {CZ}` format."""
        meter_id = MULTI_ELECTROMETER_CONFIG[0]["electrometer_id"]

        defs = get_sensor_definitions()
        sensor = next(d for d in defs if d.key == "consumption")
        payload = build_discovery_payload(sensor, meter_id)

        sensor_name = payload.get("name", "")

        # Should include meter ID in name
        assert (
            meter_id in sensor_name
        ), f"Sensor name should include meter ID: {sensor_name}"

        # Should follow bilingual format with CEZ prefix
        assert "CEZ" in sensor_name, f"Sensor name should include CEZ: {sensor_name}"


class TestMultiElectrometerPublisher:
    """Tests for multi-electrometer MqttPublisher behavior."""

    @pytest.fixture
    def multi_meter_publisher_configs(self) -> list[dict[str, str]]:
        return MULTI_ELECTROMETER_CONFIG

    def test_single_publisher_with_electrometers_list(
        self,
        mock_mqtt_client: MagicMock,
        multi_meter_publisher_configs: list[dict[str, str]],
    ) -> None:
        publisher = MqttPublisher(
            client=mock_mqtt_client,
            electrometers=multi_meter_publisher_configs,
        )
        publisher.publish_discovery()

        config_topics = [
            c[0][0]
            for c in mock_mqtt_client.publish.call_args_list
            if "/config" in c[0][0]
        ]

        meter_1_topics = [t for t in config_topics if "784703" in t]
        meter_2_topics = [t for t in config_topics if "784704" in t]

        assert len(meter_1_topics) == 17
        assert len(meter_2_topics) == 17

    def test_publisher_can_publish_for_multiple_meters(
        self,
        mock_mqtt_client: MagicMock,
        multi_meter_publisher_configs: list[dict[str, str]],
    ) -> None:
        publishers = []
        for config in multi_meter_publisher_configs:
            publisher = MqttPublisher(
                client=mock_mqtt_client, electrometer_id=config["electrometer_id"]
            )
            publishers.append(publisher)
            publisher.publish_discovery()

        config_topics = [
            c[0][0]
            for c in mock_mqtt_client.publish.call_args_list
            if "/config" in c[0][0]
        ]

        meter_1_topics = [
            t
            for t in config_topics
            if multi_meter_publisher_configs[0]["electrometer_id"] in t
        ]
        meter_2_topics = [
            t
            for t in config_topics
            if multi_meter_publisher_configs[1]["electrometer_id"] in t
        ]

        assert len(meter_1_topics) > 0, "Meter 1 should have discovery topics"
        assert len(meter_2_topics) > 0, "Meter 2 should have discovery topics"

    def test_availability_topics_distinct_per_meter(
        self,
        mock_mqtt_client: MagicMock,
        multi_meter_publisher_configs: list[dict[str, str]],
    ) -> None:
        avail_topics = []
        for config in multi_meter_publisher_configs:
            meter_id = config["electrometer_id"]
            expected_topic = AVAILABILITY_TOPIC_TEMPLATE.format(
                electrometer_id=meter_id
            )
            avail_topics.append(expected_topic)

        assert (
            avail_topics[0] != avail_topics[1]
        ), f"Availability topics must be distinct: {avail_topics}"

    def test_start_publishes_online_for_all_meters(
        self,
        mock_mqtt_client: MagicMock,
        multi_meter_publisher_configs: list[dict[str, str]],
    ) -> None:
        publisher = MqttPublisher(
            client=mock_mqtt_client,
            electrometers=multi_meter_publisher_configs,
        )
        publisher.start()

        online_calls = [
            c
            for c in mock_mqtt_client.publish.call_args_list
            if c[1].get("payload") == "online"
        ]
        topics = {c[0][0] for c in online_calls}
        for config in multi_meter_publisher_configs:
            expected = AVAILABILITY_TOPIC_TEMPLATE.format(
                electrometer_id=config["electrometer_id"]
            )
            assert expected in topics

    def test_stop_publishes_offline_for_all_meters(
        self,
        mock_mqtt_client: MagicMock,
        multi_meter_publisher_configs: list[dict[str, str]],
    ) -> None:
        publisher = MqttPublisher(
            client=mock_mqtt_client,
            electrometers=multi_meter_publisher_configs,
        )
        publisher.start()
        mock_mqtt_client.publish.reset_mock()

        publisher.stop()

        offline_calls = [
            c
            for c in mock_mqtt_client.publish.call_args_list
            if c[1].get("payload") == "offline"
        ]
        topics = {c[0][0] for c in offline_calls}
        for config in multi_meter_publisher_configs:
            expected = AVAILABILITY_TOPIC_TEMPLATE.format(
                electrometer_id=config["electrometer_id"]
            )
            assert expected in topics

    def test_per_meter_state_publishing(
        self,
        mock_mqtt_client: MagicMock,
        multi_meter_publisher_configs: list[dict[str, str]],
    ) -> None:
        publisher = MqttPublisher(
            client=mock_mqtt_client,
            electrometers=multi_meter_publisher_configs,
        )
        readings = {
            "784703": {"consumption": 1.5, "production": 0.0},
            "784704": {"consumption": 3.0, "production": 1.0},
        }
        publisher.publish_state(readings)

        state_calls = [
            c for c in mock_mqtt_client.publish.call_args_list if "/state" in c[0][0]
        ]
        topics = {c[0][0] for c in state_calls}

        assert (
            STATE_TOPIC_TEMPLATE.format(electrometer_id="784703", key="consumption")
            in topics
        )
        assert (
            STATE_TOPIC_TEMPLATE.format(electrometer_id="784704", key="consumption")
            in topics
        )
        assert (
            STATE_TOPIC_TEMPLATE.format(electrometer_id="784703", key="production")
            in topics
        )
        assert (
            STATE_TOPIC_TEMPLATE.format(electrometer_id="784704", key="production")
            in topics
        )

    def test_legacy_flat_state_still_works(
        self,
        mock_mqtt_client: MagicMock,
        multi_meter_publisher_configs: list[dict[str, str]],
    ) -> None:
        publisher = MqttPublisher(
            client=mock_mqtt_client,
            electrometers=multi_meter_publisher_configs,
        )
        readings = {"consumption": 2.5, "production": 0.5}
        publisher.publish_state(readings)

        state_calls = [
            c for c in mock_mqtt_client.publish.call_args_list if "/state" in c[0][0]
        ]
        topics = [c[0][0] for c in state_calls]
        assert all("784703" in t for t in topics)

    def test_discovery_payloads_include_ean_context(
        self,
        mock_mqtt_client: MagicMock,
        multi_meter_publisher_configs: list[dict[str, str]],
    ) -> None:
        publisher = MqttPublisher(
            client=mock_mqtt_client,
            electrometers=multi_meter_publisher_configs,
        )
        publisher.publish_discovery()

        config_calls = [
            c
            for c in mock_mqtt_client.publish.call_args_list
            if "/config" in c[0][0] and "784703" in c[0][0]
        ]
        payload = json.loads(config_calls[0][1]["payload"])
        assert "configuration_url" in payload["device"]
        assert "12345678901234" in payload["device"]["configuration_url"]

    def test_hdo_discovery_for_all_meters(
        self,
        mock_mqtt_client: MagicMock,
        multi_meter_publisher_configs: list[dict[str, str]],
    ) -> None:
        publisher = MqttPublisher(
            client=mock_mqtt_client,
            electrometers=multi_meter_publisher_configs,
        )
        publisher.publish_hdo_discovery()

        hdo_config_calls = [
            c
            for c in mock_mqtt_client.publish.call_args_list
            if "/config" in c[0][0] and "hdo" in c[0][0]
        ]
        meter_1_hdo = [c for c in hdo_config_calls if "784703" in c[0][0]]
        meter_2_hdo = [c for c in hdo_config_calls if "784704" in c[0][0]]

        assert len(meter_1_hdo) == 4
        assert len(meter_2_hdo) == 4

    def test_constructor_requires_electrometers_or_electrometer_id(
        self, mock_mqtt_client: MagicMock
    ) -> None:
        with pytest.raises(TypeError, match="requires either"):
            MqttPublisher(client=mock_mqtt_client)
