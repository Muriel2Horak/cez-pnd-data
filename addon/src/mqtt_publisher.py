"""MQTT Discovery and state publisher for CEZ PND sensors.

Publishes Home Assistant MQTT Discovery payloads and sensor state values
for consumption (+A), production (-A), and reactive (Rv) power readings.

Identity strategy (clean-break, multi-electrometer safe):
  unique_id   : cez_pnd_{electrometer_id}_{sensor_key}
  device_id   : cez_pnd_{electrometer_id}
  device_name : CEZ PND {electrometer_id}

Topic scheme (deterministic, no ad-hoc per run):
  Config : homeassistant/sensor/cez_pnd_{electrometer_id}/{key}/config
  State  : cez_pnd/{electrometer_id}/{key}/state
  Avail  : cez_pnd/{electrometer_id}/availability

Each electrometer_id produces a distinct HA device with collision-free
entity IDs and topics.  EAN context is available via the ``configuration_url``
device metadata field when the caller supplies an ``ean`` value.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ── Topic templates ───────────────────────────────────────────────────

CONFIG_TOPIC_TEMPLATE = "homeassistant/sensor/cez_pnd_{electrometer_id}/{key}/config"
STATE_TOPIC_TEMPLATE = "cez_pnd/{electrometer_id}/{key}/state"
AVAILABILITY_TOPIC_TEMPLATE = "cez_pnd/{electrometer_id}/availability"


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
        name="CEZ {id} Consumption Power / Odběr",
        unit_of_measurement="kW",
        device_class="power",
        icon="mdi:flash",
    ),
    SensorDefinition(
        key="production",
        name="CEZ {id} Production Power / Dodávka",
        unit_of_measurement="kW",
        device_class="power",
        icon="mdi:solar-power",
    ),
    SensorDefinition(
        key="reactive",
        name="CEZ {id} Reactive Power / Jalový výkon",
        unit_of_measurement="kW",
        device_class="reactive_power",
        icon="mdi:sine-wave",
    ),
    # New reactive power sensors (from Tab 03/04, 15-min, var)
    SensorDefinition(
        key="reactive_import_inductive",
        name="CEZ {id} Reactive Import Ri+ / Import induktivní",
        unit_of_measurement="var",
        device_class="reactive_power",
        icon="mdi:sine-wave",
    ),
    SensorDefinition(
        key="reactive_export_capacitive",
        name="CEZ {id} Reactive Export Rc- / Export kapacitivní",
        unit_of_measurement="var",
        device_class="reactive_power",
        icon="mdi:sine-wave",
    ),
    SensorDefinition(
        key="reactive_export_inductive",
        name="CEZ {id} Reactive Export Ri- / Export induktivní",
        unit_of_measurement="var",
        device_class="reactive_power",
        icon="mdi:sine-wave",
    ),
    SensorDefinition(
        key="reactive_import_capacitive",
        name="CEZ {id} Reactive Import Rc+ / Import kapacitivní",
        unit_of_measurement="var",
        device_class="reactive_power",
        icon="mdi:sine-wave",
    ),
    # Daily energy aggregates (from Tab 07/08, daily, kWh)
    SensorDefinition(
        key="daily_consumption",
        name="CEZ {id} Daily Consumption / Denní odběr",
        unit_of_measurement="kWh",
        device_class="energy",
        state_class="total_increasing",
        icon="mdi:flash",
    ),
    SensorDefinition(
        key="daily_production",
        name="CEZ {id} Daily Production / Denní dodávka",
        unit_of_measurement="kWh",
        device_class="energy",
        state_class="total_increasing",
        icon="mdi:solar-power",
    ),
    # Register readings (from Tab 17, daily, kWh)
    SensorDefinition(
        key="register_consumption",
        name="CEZ {id} Register Consumption (+E) / Registr odběr",
        unit_of_measurement="kWh",
        device_class="energy",
        state_class="total_increasing",
        icon="mdi:counter",
    ),
    SensorDefinition(
        key="register_production",
        name="CEZ {id} Register Production (-E) / Registr dodávka",
        unit_of_measurement="kWh",
        device_class="energy",
        state_class="total_increasing",
        icon="mdi:counter",
    ),
    SensorDefinition(
        key="register_low_tariff",
        name="CEZ {id} Register Low Tariff (NT) / Registr nízký tarif",
        unit_of_measurement="kWh",
        device_class="energy",
        state_class="total_increasing",
        icon="mdi:cash-minus",
    ),
    SensorDefinition(
        key="register_high_tariff",
        name="CEZ {id} Register High Tariff (VT) / Registr vysoký tarif",
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
        name="CEZ {id} HDO Low Tariff Active / HDO Nízký tarif aktivní",
        unit_of_measurement=None,
        device_class="binary_sensor",
        state_class=None,
    ),
    SensorDefinition(
        key="hdo_next_switch",
        name="CEZ {id} HDO Next Switch / HDO Další přepnutí",
        unit_of_measurement=None,
        device_class="timestamp",
        state_class=None,
    ),
    SensorDefinition(
        key="hdo_schedule_today",
        name="CEZ {id} HDO Schedule Today / HDO Rozvrh dnes",
        unit_of_measurement=None,
        device_class=None,
        state_class=None,
    ),
    SensorDefinition(
        key="hdo_signal",
        name="CEZ {id} HDO Signal / HDO Signál",
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
    electrometer_id: str,
    *,
    ean: str = "",
) -> dict[str, Any]:
    """Build an HA-compliant MQTT Discovery payload for a single sensor.

    Args:
        sensor: Sensor definition to build the payload for.
        electrometer_id: Electrometer ID used in unique_id, device_id, and topics.
        ean: Optional EAN (supply-point number).  When provided, a
            ``configuration_url`` pointing to the CEZ PND portal is added
            to the device metadata so that the EAN context is accessible
            from the Home Assistant device page.

    Reference: https://www.home-assistant.io/integrations/sensor.mqtt/
    """
    device_id = f"cez_pnd_{electrometer_id}"

    device_meta: dict[str, Any] = {
        "identifiers": [device_id],
        "name": f"CEZ PND {electrometer_id}",
        "manufacturer": "CEZ Distribuce",
        "model": "PND Electrometer",
    }

    if ean:
        device_meta["configuration_url"] = (
            f"https://pnd.cezdistribuce.cz/cezpnd2/dashboard/?ean={ean}"
        )

    payload: dict[str, Any] = {
        "unique_id": f"{device_id}_{sensor.key}",
        "name": sensor.name.format(id=electrometer_id),
        "state_topic": STATE_TOPIC_TEMPLATE.format(
            electrometer_id=electrometer_id, key=sensor.key
        ),
        "availability_topic": AVAILABILITY_TOPIC_TEMPLATE.format(
            electrometer_id=electrometer_id
        ),
        "unit_of_measurement": sensor.unit_of_measurement,
        "device_class": sensor.device_class,
        "state_class": sensor.state_class,
        "device": device_meta,
    }

    if sensor.icon:
        payload["icon"] = sensor.icon

    return payload


# ── MQTT Publisher ────────────────────────────────────────────────────

VALID_SENSOR_KEYS = frozenset(d.key for d in _SENSOR_DEFINITIONS)


class MqttPublisher:
    """Multi-electrometer MQTT publisher for HA Discovery and state."""

    def __init__(
        self,
        client: Any,
        electrometers: list[dict[str, str]] | None = None,
        *,
        electrometer_id: str | None = None,
        ean: str = "",
    ) -> None:
        self._client = client

        if electrometers is not None:
            self._electrometers = list(electrometers)
        elif electrometer_id is not None:
            entry: dict[str, str] = {"electrometer_id": electrometer_id}
            if ean:
                entry["ean"] = ean
            self._electrometers = [entry]
        else:
            raise TypeError(
                "MqttPublisher requires either 'electrometers' list "
                "or legacy 'electrometer_id' keyword argument"
            )

    # ── helpers ───────────────────────────────────────────────────

    def _availability_topic(self, meter_id: str) -> str:
        return AVAILABILITY_TOPIC_TEMPLATE.format(electrometer_id=meter_id)

    # ── Lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        """Configure LWT (first meter only — MQTT limitation), connect,
        and announce online for every electrometer.
        """
        first_meter = self._electrometers[0]["electrometer_id"]
        self._client.will_set(
            self._availability_topic(first_meter),
            payload="offline",
            qos=1,
            retain=True,
        )

        self._client.connect()

        for elec in self._electrometers:
            meter_id = elec["electrometer_id"]
            self._client.publish(
                self._availability_topic(meter_id),
                payload="online",
                qos=1,
                retain=True,
            )
        logger.info(
            "MQTT publisher started, %d electrometer(s) online",
            len(self._electrometers),
        )

    def stop(self) -> None:
        """Publish offline availability for all meters and disconnect."""
        for elec in self._electrometers:
            meter_id = elec["electrometer_id"]
            self._client.publish(
                self._availability_topic(meter_id),
                payload="offline",
                qos=1,
                retain=True,
            )
        self._client.disconnect()
        logger.info("MQTT publisher stopped, availability=offline")

    # ── Discovery ─────────────────────────────────────────────────

    def publish_discovery(self) -> None:
        """Publish MQTT Discovery config for all sensor entities of every electrometer."""
        for elec in self._electrometers:
            meter_id = elec["electrometer_id"]
            meter_ean = elec.get("ean", "")
            for sensor in _SENSOR_DEFINITIONS:
                topic = CONFIG_TOPIC_TEMPLATE.format(
                    electrometer_id=meter_id, key=sensor.key
                )
                payload = build_discovery_payload(sensor, meter_id, ean=meter_ean)
                self._client.publish(
                    topic,
                    payload=json.dumps(payload),
                    qos=1,
                    retain=True,
                )
                logger.debug("Published discovery: %s", topic)

        self.publish_hdo_discovery()

    # ── State publishing ──────────────────────────────────────────

    def publish_state(
        self,
        readings: Mapping[str, Any],
    ) -> None:
        """Publish sensor values.  Accepts flat ``{key: val}`` (legacy) or
        per-meter ``{meter_id: {key: val}}`` format.
        """
        known_ids = {e["electrometer_id"] for e in self._electrometers}
        is_per_meter = any(k in known_ids for k in readings)

        if is_per_meter:
            for elec in self._electrometers:
                meter_id = elec["electrometer_id"]
                meter_readings = readings.get(meter_id, {})
                self._publish_readings_for_meter(meter_id, meter_readings)
        else:
            first_meter = self._electrometers[0]["electrometer_id"]
            self._publish_readings_for_meter(first_meter, readings)

    def _publish_readings_for_meter(
        self, meter_id: str, readings: Mapping[str, float | None]
    ) -> None:
        for key, value in readings.items():
            if key not in VALID_SENSOR_KEYS:
                logger.warning("Ignoring unknown sensor key: %s", key)
                continue
            if value is None:
                continue

            topic = STATE_TOPIC_TEMPLATE.format(electrometer_id=meter_id, key=key)
            self._client.publish(
                topic,
                payload=str(value),
                qos=1,
                retain=True,
            )
            logger.debug("Published state: %s = %s", topic, value)

    def publish_hdo_state(
        self, hdo_data: Any, *, electrometer_id: str | None = None
    ) -> None:
        meter_id = electrometer_id or self._electrometers[0]["electrometer_id"]

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
                electrometer_id=meter_id,
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
        """Publish MQTT Discovery config for all 4 HDO sensor entities of every electrometer."""
        for elec in self._electrometers:
            meter_id = elec["electrometer_id"]
            meter_ean = elec.get("ean", "")
            for sensor in _HDO_SENSOR_DEFINITIONS:
                topic = CONFIG_TOPIC_TEMPLATE.format(
                    electrometer_id=meter_id,
                    key=sensor.key,
                )
                payload = build_discovery_payload(sensor, meter_id, ean=meter_ean)
                self._client.publish(
                    topic,
                    payload=json.dumps(payload),
                    qos=1,
                    retain=True,
                )
                logger.debug("Published HDO discovery: %s", topic)
