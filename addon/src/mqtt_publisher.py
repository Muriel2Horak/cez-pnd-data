"""MQTT Discovery and state publisher for CEZ PND sensors.

Publishes Home Assistant MQTT Discovery payloads and sensor state values
for consumption (+A), production (-A), and reactive (Rv) power readings.

Topic scheme (deterministic, no ad-hoc per run):
  Config : homeassistant/sensor/cez_pnd_{meter_id}/{key}/config
  State  : cez_pnd/{meter_id}/{key}/state
  Avail  : cez_pnd/{meter_id}/availability
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ── Topic templates ───────────────────────────────────────────────────

CONFIG_TOPIC_TEMPLATE = "homeassistant/sensor/cez_pnd_{meter_id}/{key}/config"
STATE_TOPIC_TEMPLATE = "cez_pnd/{meter_id}/{key}/state"
AVAILABILITY_TOPIC_TEMPLATE = "cez_pnd/{meter_id}/availability"


# ── Sensor definitions ────────────────────────────────────────────────


@dataclass(frozen=True)
class SensorDefinition:
    """Describes one HA sensor entity."""

    key: str
    name: str
    unit_of_measurement: str | None
    device_class: str | None
    state_class: str | None = "measurement"
    icon: str | None = None


_SENSOR_DEFINITIONS: list[SensorDefinition] = [
    SensorDefinition(
        key="consumption",
        name="CEZ Consumption Power",
        unit_of_measurement="kW",
        device_class="power",
        icon="mdi:flash",
    ),
    SensorDefinition(
        key="production",
        name="CEZ Production Power",
        unit_of_measurement="kW",
        device_class="power",
        icon="mdi:solar-power",
    ),
    SensorDefinition(
        key="reactive",
        name="CEZ Reactive Power",
        unit_of_measurement="kW",
        device_class="reactive_power",
        icon="mdi:sine-wave",
    ),
    # New reactive power sensors (from Tab 03/04, 15-min, var)
    SensorDefinition(
        key="reactive_import_inductive",
        name="CEZ Reactive Import Ri+",
        unit_of_measurement="var",
        device_class="reactive_power",
        icon="mdi:sine-wave",
    ),
    SensorDefinition(
        key="reactive_export_capacitive",
        name="CEZ Reactive Export Rc-",
        unit_of_measurement="var",
        device_class="reactive_power",
        icon="mdi:sine-wave",
    ),
    SensorDefinition(
        key="reactive_export_inductive",
        name="CEZ Reactive Export Ri-",
        unit_of_measurement="var",
        device_class="reactive_power",
        icon="mdi:sine-wave",
    ),
    SensorDefinition(
        key="reactive_import_capacitive",
        name="CEZ Reactive Import Rc+",
        unit_of_measurement="var",
        device_class="reactive_power",
        icon="mdi:sine-wave",
    ),
    # Daily energy aggregates (from Tab 07/08, daily, kWh)
    SensorDefinition(
        key="daily_consumption",
        name="CEZ Daily Consumption",
        unit_of_measurement="kWh",
        device_class="energy",
        state_class="total_increasing",
        icon="mdi:flash",
    ),
    SensorDefinition(
        key="daily_production",
        name="CEZ Daily Production",
        unit_of_measurement="kWh",
        device_class="energy",
        state_class="total_increasing",
        icon="mdi:solar-power",
    ),
    # Register readings (from Tab 17, daily, kWh)
    SensorDefinition(
        key="register_consumption",
        name="CEZ Register Consumption (+E)",
        unit_of_measurement="kWh",
        device_class="energy",
        state_class="total_increasing",
        icon="mdi:counter",
    ),
    SensorDefinition(
        key="register_production",
        name="CEZ Register Production (-E)",
        unit_of_measurement="kWh",
        device_class="energy",
        state_class="total_increasing",
        icon="mdi:counter",
    ),
    SensorDefinition(
        key="register_low_tariff",
        name="CEZ Register Low Tariff (NT)",
        unit_of_measurement="kWh",
        device_class="energy",
        state_class="total_increasing",
        icon="mdi:cash-minus",
    ),
    SensorDefinition(
        key="register_high_tariff",
        name="CEZ Register High Tariff (VT)",
        unit_of_measurement="kWh",
        device_class="energy",
        state_class="total_increasing",
        icon="mdi:cash-plus",
    ),
]


def get_sensor_definitions() -> list[SensorDefinition]:
    """Return the canonical list of CEZ PND sensor definitions."""
    return list(_SENSOR_DEFINITIONS)


# ── Binary sensor / HDO definitions ──────────────────────────────────


@dataclass(frozen=True)
class BinarySensorDefinition:
    """Describes one HA binary_sensor entity (e.g. HDO tariff state)."""

    key: str
    name: str
    unit_of_measurement: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    payload_on: str = "ON"
    payload_off: str = "OFF"
    icon: str | None = None


_HDO_SENSOR_DEFINITIONS: list[SensorDefinition] = [
    SensorDefinition(
        key="hdo_low_tariff_active",
        name="CEZ HDO Low Tariff Active",
        unit_of_measurement=None,
        device_class="binary_sensor",
        state_class=None,
    ),
    SensorDefinition(
        key="hdo_next_switch",
        name="CEZ HDO Next Switch",
        unit_of_measurement=None,
        device_class="timestamp",
        state_class=None,
    ),
    SensorDefinition(
        key="hdo_schedule_today",
        name="CEZ HDO Schedule Today",
        unit_of_measurement=None,
        device_class=None,
        state_class=None,
    ),
    SensorDefinition(
        key="hdo_signal",
        name="CEZ HDO Signal",
        unit_of_measurement=None,
        device_class=None,
        state_class=None,
    ),
]


def get_hdo_sensor_definitions() -> list[SensorDefinition]:
    """Return the 4 HDO sensor definitions."""
    return list(_HDO_SENSOR_DEFINITIONS)


VALID_HDO_KEYS = frozenset(d.key for d in _HDO_SENSOR_DEFINITIONS)


# ── Discovery payload builder ────────────────────────────────────────


def build_discovery_payload(
    sensor: SensorDefinition,
    meter_id: str,
) -> dict[str, Any]:
    """Build an HA-compliant MQTT Discovery payload for a single sensor.

    Reference: https://www.home-assistant.io/integrations/sensor.mqtt/
    """
    device_id = f"cez_pnd_{meter_id}"

    payload: dict[str, Any] = {
        "unique_id": f"{device_id}_{sensor.key}",
        "name": sensor.name,
        "state_topic": STATE_TOPIC_TEMPLATE.format(meter_id=meter_id, key=sensor.key),
        "availability_topic": AVAILABILITY_TOPIC_TEMPLATE.format(meter_id=meter_id),
        "unit_of_measurement": sensor.unit_of_measurement,
        "device_class": sensor.device_class,
        "state_class": sensor.state_class,
        "device": {
            "identifiers": [device_id],
            "name": f"CEZ PND {meter_id}",
            "manufacturer": "CEZ Distribuce",
            "model": "PND Electrometer",
        },
    }

    if sensor.icon:
        payload["icon"] = sensor.icon

    return payload


# ── MQTT Publisher ────────────────────────────────────────────────────

VALID_SENSOR_KEYS = frozenset(d.key for d in _SENSOR_DEFINITIONS)


class MqttPublisher:
    """Manages MQTT lifecycle: LWT, discovery, and state publishing."""

    def __init__(self, client: Any, meter_id: str) -> None:
        self._client = client
        self._meter_id = meter_id
        self._availability_topic = AVAILABILITY_TOPIC_TEMPLATE.format(meter_id=meter_id)

    # ── Lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        """Configure LWT, connect, and announce online status."""
        # LWT must be set BEFORE connect
        self._client.will_set(
            self._availability_topic,
            payload="offline",
            qos=1,
            retain=True,
        )

        self._client.connect()

        # Announce online
        self._client.publish(
            self._availability_topic,
            payload="online",
            qos=1,
            retain=True,
        )
        logger.info("MQTT publisher started, availability=online")

    def stop(self) -> None:
        """Publish offline availability and disconnect."""
        self._client.publish(
            self._availability_topic,
            payload="offline",
            qos=1,
            retain=True,
        )
        self._client.disconnect()
        logger.info("MQTT publisher stopped, availability=offline")

    # ── Discovery ─────────────────────────────────────────────────

    def publish_discovery(self) -> None:
        """Publish MQTT Discovery config for all sensor entities."""
        for sensor in _SENSOR_DEFINITIONS:
            topic = CONFIG_TOPIC_TEMPLATE.format(
                meter_id=self._meter_id, key=sensor.key
            )
            payload = build_discovery_payload(sensor, self._meter_id)
            self._client.publish(
                topic,
                payload=json.dumps(payload),
                qos=1,
                retain=True,
            )
            logger.debug("Published discovery: %s", topic)

        self.publish_hdo_discovery()

    # ── State publishing ──────────────────────────────────────────

    def publish_state(self, readings: Mapping[str, float | None]) -> None:
        """Publish current sensor values to state topics.

        Args:
            readings: Mapping of sensor key -> numeric value.
                      Keys not in VALID_SENSOR_KEYS are silently ignored.
                      None values are skipped (sensor stays at last known state).
        """
        for key, value in readings.items():
            if key not in VALID_SENSOR_KEYS:
                logger.warning("Ignoring unknown sensor key: %s", key)
                continue
            if value is None:
                continue

            topic = STATE_TOPIC_TEMPLATE.format(meter_id=self._meter_id, key=key)
            self._client.publish(
                topic,
                payload=str(value),
                qos=1,
                retain=True,
            )
            logger.debug("Published state: %s = %s", topic, value)

    def publish_hdo_state(self, hdo_data: Any) -> None:
        """Publish HDO tariff data to 4 dedicated sensor state topics."""
        schedule_str = "; ".join(f"{s}-{e}" for s, e in hdo_data.today_schedule)
        hdo_values: dict[str, str] = {
            "hdo_low_tariff_active": "ON" if hdo_data.is_low_tariff else "OFF",
            "hdo_next_switch": hdo_data.next_switch.isoformat(),
            "hdo_schedule_today": schedule_str,
            "hdo_signal": hdo_data.signal_name,
        }

        for key, value in hdo_values.items():
            if key not in VALID_HDO_KEYS:
                continue
            topic = STATE_TOPIC_TEMPLATE.format(
                meter_id=self._meter_id,
                key=key,
            )
            self._client.publish(
                topic,
                payload=value,
                qos=1,
                retain=True,
            )
            logger.debug("Published HDO state: %s = %s", topic, value)

    def publish_hdo_discovery(self) -> None:
        """Publish MQTT Discovery config for all 4 HDO sensor entities."""
        for sensor in _HDO_SENSOR_DEFINITIONS:
            topic = CONFIG_TOPIC_TEMPLATE.format(
                meter_id=self._meter_id,
                key=sensor.key,
            )
            payload = build_discovery_payload(sensor, self._meter_id)
            self._client.publish(
                topic,
                payload=json.dumps(payload),
                qos=1,
                retain=True,
            )
            logger.debug("Published HDO discovery: %s", topic)
