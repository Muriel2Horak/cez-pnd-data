"""MQTT Discovery and state publisher for CEZ PND sensors.

Publishes Home Assistant MQTT Discovery payloads and sensor state values
for consumption (+A), production (-A), reserved power (Rv), and reactive
quadrant readings (+Ri/-Ri and +Rc/-Rc).

Identity strategy (clean-break, multi-electrometer safe):
  unique_id   : cez_pnd_{electrometer_id}_{sensor_key}
  device_id   : cez_pnd_{electrometer_id}
  device_name : CEZ PND {electrometer_id}

Topic scheme (deterministic, no ad-hoc per run):
  Config : homeassistant/sensor/cez_pnd_{electrometer_id}/{key}/config
  State  : cez_pnd/{electrometer_id}/{key}/state
  Avail  : cez_pnd/availability (shared by all meters on this connection)

Each electrometer_id produces a distinct HA device with collision-free
entity IDs and topics.  EAN context is available via the ``configuration_url``
device metadata field when the caller supplies an ``ean`` value.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ── Topic templates ───────────────────────────────────────────────────

CONFIG_TOPIC_TEMPLATE = "homeassistant/sensor/cez_pnd_{electrometer_id}/{key}/config"
STATE_TOPIC_TEMPLATE = "cez_pnd/{electrometer_id}/{key}/state"
AVAILABILITY_TOPIC_TEMPLATE = "cez_pnd/availability"


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
        name="CEZ {id} Reserved Power / Rezervovaný výkon",
        unit_of_measurement="kW",
        # RV is reserved power; keep the historical key for MQTT compatibility.
        device_class="power",
        icon="mdi:sine-wave",
    ),
    # New reactive power sensors (from Tab 03/04, 15-min, kvar)
    SensorDefinition(
        key="reactive_import_inductive",
        name="CEZ {id} Reactive Import Ri+ / Import induktivní",
        unit_of_measurement="kvar",
        device_class="reactive_power",
        icon="mdi:sine-wave",
    ),
    SensorDefinition(
        key="reactive_export_capacitive",
        name="CEZ {id} Reactive Export Rc- / Export kapacitivní",
        unit_of_measurement="kvar",
        device_class="reactive_power",
        icon="mdi:sine-wave",
    ),
    SensorDefinition(
        key="reactive_export_inductive",
        name="CEZ {id} Reactive Export Ri- / Export induktivní",
        unit_of_measurement="kvar",
        device_class="reactive_power",
        icon="mdi:sine-wave",
    ),
    SensorDefinition(
        key="reactive_import_capacitive",
        name="CEZ {id} Reactive Import Rc+ / Import kapacitivní",
        unit_of_measurement="kvar",
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
        device_class=None,
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
        self._started = False
        self._stopping = threading.Event()
        self._lifecycle_lock = threading.Lock()

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

    def set_electrometers(self, electrometers: list[dict[str, str]]) -> None:
        if self._started:
            raise RuntimeError("Cannot replace meters after MQTT startup")
        self._electrometers = list(electrometers)

    def start(self) -> None:
        """Configure shared LWT, connect, and announce online for every meter."""
        with self._lifecycle_lock:
            if not self._electrometers:
                raise ValueError("Resolve at least one meter before MQTT startup")
            self._client.will_set(
                AVAILABILITY_TOPIC_TEMPLATE, payload="offline", qos=1, retain=True
            )
            self._client.connect()
            if self._stopping.is_set():
                raise ConnectionError("MQTT startup cancelled")
            self._started = True
            self._client.publish(
                AVAILABILITY_TOPIC_TEMPLATE, payload="online", qos=1, retain=True
            )
            logger.info(
                "MQTT publisher started, %d electrometer(s) online",
                len(self._electrometers),
            )
            logger.info(
                "MQTT availability topic: %s; manual consumers must migrate "
                "from cez_pnd/{meter_id}/availability (see README upgrade guide)",
                AVAILABILITY_TOPIC_TEMPLATE,
            )

    def begin_shutdown(self) -> None:
        self._stopping.set()
        stop = getattr(self._client, "begin_shutdown", None)
        if callable(stop):
            stop()

    def stop(self) -> None:
        """Publish shared offline availability for all meters and disconnect."""
        self.begin_shutdown()
        with self._lifecycle_lock:
            try:
                if self._started:
                    self._client.publish(
                        AVAILABILITY_TOPIC_TEMPLATE,
                        payload="offline",
                        qos=1,
                        retain=True,
                    )
            finally:
                self._started = False
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
                if self._stopping.is_set():
                    raise ConnectionError("MQTT discovery cancelled during shutdown")
                self._client.publish(
                    topic,
                    payload=json.dumps(payload),
                    qos=1,
                    retain=True,
                )
                logger.debug("Published discovery: %s", topic)

        self.publish_hdo_discovery()
        # Keep old availability intact until every replacement discovery
        # configuration has been acknowledged by the broker.
        for elec in self._electrometers:
            if self._stopping.is_set():
                raise ConnectionError("MQTT migration cancelled during shutdown")
            self._client.publish(
                f"cez_pnd/{elec['electrometer_id']}/availability",
                payload="",
                qos=1,
                retain=True,
            )

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

        messages = []
        if is_per_meter:
            for elec in self._electrometers:
                meter_id = elec["electrometer_id"]
                messages.extend(
                    self._readings_for_meter(meter_id, readings.get(meter_id, {}))
                )
        else:
            first_meter = self._electrometers[0]["electrometer_id"]
            messages.extend(self._readings_for_meter(first_meter, readings))
        self._publish_messages(messages)

    def _readings_for_meter(
        self, meter_id: str, readings: Mapping[str, float | None]
    ) -> list[tuple[str, str]]:
        messages = []
        for key, value in readings.items():
            if key not in VALID_SENSOR_KEYS:
                logger.warning("Ignoring unknown sensor key: %s", key)
                continue
            if value is not None:
                messages.append(
                    (
                        STATE_TOPIC_TEMPLATE.format(electrometer_id=meter_id, key=key),
                        str(value),
                    )
                )
        return messages

    def _publish_messages(self, messages: list[tuple[str, str]]) -> None:
        if self._stopping.is_set():
            raise ConnectionError("MQTT publisher is stopping")
        cache = getattr(self._client, "cache_retained", None)
        if callable(cache):
            cache(messages)
        for topic, payload in messages:
            if self._stopping.is_set():
                raise ConnectionError("MQTT publish cancelled during shutdown")
            self._client.publish(topic, payload=payload, qos=1, retain=True)
            logger.debug("Published state: %s = %s", topic, payload)

    def publish_hdo_state(
        self, hdo_data: Any, *, electrometer_id: str | None = None
    ) -> None:
        meter_id = electrometer_id or self._electrometers[0]["electrometer_id"]

        schedule_str = (
            "; ".join(f"{s}-{e}" for s, e in hdo_data.today_schedule)
            if hdo_data.today_schedule is not None
            else "None"
        )
        hdo_values: dict[str, str] = {
            "hdo_low_tariff_active": (
                "None"
                if hdo_data.is_low_tariff is None
                else "ON" if hdo_data.is_low_tariff else "OFF"
            ),
            "hdo_next_switch": (
                hdo_data.next_switch.isoformat() if hdo_data.next_switch else "None"
            ),
            "hdo_schedule_today": schedule_str,
            "hdo_signal": hdo_data.signal_name or "None",
        }

        self._publish_messages(
            [
                (STATE_TOPIC_TEMPLATE.format(electrometer_id=meter_id, key=key), value)
                for key, value in hdo_values.items()
                if key in VALID_HDO_KEYS
            ]
        )

    def publish_hdo_discovery(self) -> None:
        """Keep the four HDO sensors and add an optional binary tariff sensor."""
        for elec in self._electrometers:
            meter_id = elec["electrometer_id"]
            meter_ean = elec.get("ean", "")
            for sensor in _HDO_SENSOR_DEFINITIONS:
                topic = CONFIG_TOPIC_TEMPLATE.format(
                    electrometer_id=meter_id,
                    key=sensor.key,
                )
                payload = build_discovery_payload(sensor, meter_id, ean=meter_ean)
                if self._stopping.is_set():
                    raise ConnectionError("MQTT discovery cancelled during shutdown")
                self._client.publish(
                    topic,
                    payload=json.dumps(payload),
                    qos=1,
                    retain=True,
                )
                logger.debug("Published HDO discovery: %s", topic)
                if sensor.key == "hdo_low_tariff_active":
                    binary_topic = topic.replace(
                        "homeassistant/sensor/", "homeassistant/binary_sensor/", 1
                    )
                    binary_payload = dict(payload)
                    for field in ("unit_of_measurement", "device_class", "state_class"):
                        binary_payload.pop(field, None)
                    binary_payload.update(
                        unique_id=f"{payload['unique_id']}_binary",
                        payload_on="ON",
                        payload_off="OFF",
                        enabled_by_default=False,
                    )
                    if self._stopping.is_set():
                        raise ConnectionError(
                            "MQTT discovery cancelled during shutdown"
                        )
                    self._client.publish(
                        binary_topic,
                        payload=json.dumps(binary_payload),
                        qos=1,
                        retain=True,
                    )
                    logger.debug("Published HDO discovery: %s", binary_topic)
