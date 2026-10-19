"""Exercise upgrade behavior in a real Home Assistant instance and MQTT broker."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
from pathlib import Path

import pytest
import pytest_asyncio

pytest.importorskip("homeassistant")

from homeassistant import bootstrap, loader  # noqa: E402
from homeassistant.config_entries import (  # noqa: E402
    ConfigEntries,
    ConfigEntry,
    ConfigEntryState,
)
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.core_config import async_process_ha_core_config  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from homeassistant.setup import async_setup_component  # noqa: E402

from addon.src.blocking import run_blocking  # noqa: E402
from addon.src.hdo_parser import UNKNOWN_HDO, HdoData  # noqa: E402
from addon.src.mqtt_client import MQTTClientWrapper  # noqa: E402
from addon.src.mqtt_publisher import MqttPublisher  # noqa: E402
from tests.test_mqtt_transport import broker as broker  # noqa: E402

METERS = [{"electrometer_id": "123"}, {"electrometer_id": "456"}]


def manual_configuration(availability):
    return {
        "mqtt": {
            "sensor": [
                {
                    "name": "Manual consumption",
                    "unique_id": "manual_cez_consumption",
                    "state_topic": "cez_pnd/123/consumption/state",
                    "availability_topic": availability,
                }
            ]
        }
    }


async def eventually(predicate, timeout=15):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.05)


def transport(port):
    return MQTTClientWrapper("127.0.0.1", port, "test-user", "test-password")


@pytest_asyncio.fixture
async def homeassistant_broker(tmp_path, broker):
    port, _, _ = broker
    config_dir = tmp_path / "ha"
    config_dir.mkdir()
    (config_dir / "configuration.yaml").write_text(
        json.dumps(manual_configuration("cez_pnd/123/availability")), encoding="utf-8"
    )
    hass = HomeAssistant(str(config_dir))
    # Load the real MQTT integration and dependencies, without unrelated
    # default integrations or automatic package installation during tests.
    hass.config.skip_pip = True
    loader.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    try:
        assert await bootstrap.async_load_base_functionality(hass)
        await async_process_ha_core_config(
            hass, {"time_zone": "Europe/Prague", "auth_mfa_modules": []}
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            http_port = sock.getsockname()[1]
        assert await async_setup_component(
            hass,
            "mqtt",
            {"http": {"server_host": ["127.0.0.1"], "server_port": http_port}},
        )
        await hass.async_start()
        entry = ConfigEntry(
            domain="mqtt",
            title="Local test broker",
            source="user",
            version=2,
            minor_version=1,
            data={
                "broker": "127.0.0.1",
                "port": port,
                "username": "test-user",
                "password": "test-password",
                "protocol": "5",
            },
            options={},
            unique_id=None,
            discovery_keys={},
            subentries_data=[],
        )
        await hass.config_entries.async_add(entry)
        assert entry.state is ConfigEntryState.LOADED
        yield hass, entry, broker
    finally:
        await hass.async_stop()


def legacy_config(meter, key, invalid_hdo=False):
    # Explicit baseline wire contract; do not derive it from the new builder.
    payload = {
        "name": f"Original {meter} {key}",
        "unique_id": f"cez_pnd_{meter}_{key}",
        "state_topic": f"cez_pnd/{meter}/{key}/state",
        "availability_topic": f"cez_pnd/{meter}/availability",
        "device": {"identifiers": [f"cez_pnd_{meter}"], "name": f"CEZ PND {meter}"},
    }
    if key == "consumption":
        payload.update(
            unit_of_measurement="kW", device_class="power", state_class="measurement"
        )
    elif key == "reactive":
        # Original invalid discovery on one meter; an existing manually
        # repaired entity on the other exercises identity/custom-name survival.
        payload.update(
            name=f"CEZ {meter} Reactive Power / Jalový výkon",
            unit_of_measurement="kW",
            device_class="reactive_power" if meter == "123" else "power",
            state_class="measurement",
        )
    elif key == "hdo_low_tariff_active" and invalid_hdo:
        payload["device_class"] = "binary_sensor"
    return payload


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("invalid_hdo", [False, True])
async def test_existing_entities_survive_upgrade_and_recovery(
    homeassistant_broker, invalid_hdo
):
    hass, entry, (port, stop_broker, start_broker) = homeassistant_broker
    registry = er.async_get(hass)
    seed = transport(port)
    publisher = MqttPublisher(transport(port), electrometers=METERS)
    child = None

    def entity_id(meter, key, domain="sensor"):
        return registry.async_get_entity_id(domain, "mqtt", f"cez_pnd_{meter}_{key}")

    def state_is(target, value):
        return (state := hass.states.get(target)) is not None and state.state == value

    async def publish(topic, payload):
        await run_blocking(seed.publish, topic, payload)

    try:
        await run_blocking(seed.connect)
        for meter in ("123", "456"):
            await publish(f"cez_pnd/{meter}/availability", "online")
            for key in (
                "consumption",
                "reactive",
                "hdo_low_tariff_active",
                "hdo_signal",
            ):
                await publish(
                    f"homeassistant/sensor/cez_pnd_{meter}/{key}/config",
                    json.dumps(legacy_config(meter, key, invalid_hdo)),
                )
            await publish(f"cez_pnd/{meter}/consumption/state", "0.5")
            await publish(f"cez_pnd/{meter}/reactive/state", "4.0")
            await publish(f"cez_pnd/{meter}/hdo_low_tariff_active/state", "ON")
        await eventually(
            lambda: all(entity_id(m, "hdo_signal") for m in ("123", "456"))
        )
        await eventually(
            lambda: all(
                state_is(entity_id(m, "consumption"), "0.5") for m in ("123", "456")
            )
        )
        await eventually(lambda: state_is(entity_id("456", "reactive"), "4.0"))
        assert entity_id("123", "reactive") is None
        registry.async_update_entity(
            entity_id("456", "reactive"),
            new_entity_id="sensor.my_reserved_power",
            name="My RV limit",
        )
        customized_rv = registry.async_get("sensor.my_reserved_power")
        if invalid_hdo:
            assert entity_id("123", "hdo_low_tariff_active") is None
        else:
            await eventually(
                lambda: state_is(entity_id("123", "hdo_low_tariff_active"), "ON")
            )

        original_consumption = entity_id("123", "consumption")
        registry.async_update_entity(
            original_consumption,
            new_entity_id="sensor.my_cez_consumption",
            name="My consumption",
            icon="mdi:home-lightning-bolt",
        )
        customized = registry.async_get("sensor.my_cez_consumption")
        original_low_tariff = entity_id("123", "hdo_low_tariff_active")
        disabled = entity_id("456", "hdo_signal")
        registry.async_update_entity(
            disabled, disabled_by=er.RegistryEntryDisabler.USER
        )
        await hass.async_block_till_done()

        await run_blocking(publisher.start)
        await run_blocking(publisher.publish_discovery)
        await run_blocking(
            publisher.publish_state,
            {
                "123": {"consumption": 1.5, "reactive": 5.46},
                "456": {"consumption": 2.5, "reactive": 4.0},
            },
        )
        tariff = HdoData(True, None, [("00:00", "24:00")], "TEST")
        for meter in ("123", "456"):
            await run_blocking(
                publisher.publish_hdo_state, tariff, electrometer_id=meter
            )
        await eventually(lambda: state_is("sensor.my_cez_consumption", "1.5"))
        await eventually(
            lambda: state_is(entity_id("123", "reactive"), "5.46")
            and state_is(entity_id("456", "reactive"), "4.0")
        )
        assert (
            hass.states.get(entity_id("123", "reactive")).attributes[
                "unit_of_measurement"
            ]
            == "kW"
        )
        assert registry.async_get(entity_id("123", "reactive")).unique_id == (
            "cez_pnd_123_reactive"
        )
        assert (
            hass.states.get(entity_id("123", "reactive")).attributes["device_class"]
            == "power"
        )
        assert registry.async_get(entity_id("123", "reactive")).original_name == (
            "CEZ 123 Reserved Power / Rezervovaný výkon"
        )
        assert entity_id("456", "reactive") == "sensor.my_reserved_power"
        assert registry.async_get("sensor.my_reserved_power").id == customized_rv.id
        assert registry.async_get("sensor.my_reserved_power").name == "My RV limit"
        assert (
            registry.async_get("sensor.my_reserved_power").device_id
            == customized_rv.device_id
        )
        await eventually(
            lambda: all(
                state_is(entity_id(m, "hdo_low_tariff_active"), "ON")
                for m in ("123", "456")
            )
        )
        assert registry.async_get("sensor.my_cez_consumption").id == customized.id
        assert registry.async_get("sensor.my_cez_consumption").name == "My consumption"
        assert (
            registry.async_get("sensor.my_cez_consumption").icon
            == "mdi:home-lightning-bolt"
        )
        assert (
            registry.async_get("sensor.my_cez_consumption").device_id
            == customized.device_id
        )
        assert entity_id("123", "consumption") == "sensor.my_cez_consumption"
        if original_low_tariff:
            assert entity_id("123", "hdo_low_tariff_active") == original_low_tariff
        assert registry.async_get(disabled).disabled_by is er.RegistryEntryDisabler.USER
        await eventually(
            lambda: entity_id("123", "hdo_low_tariff_active_binary", "binary_sensor")
        )
        binary = entity_id("123", "hdo_low_tariff_active_binary", "binary_sensor")
        assert (
            registry.async_get(binary).disabled_by
            is er.RegistryEntryDisabler.INTEGRATION
        )
        assert hass.states.get(binary) is None

        registry.async_update_entity(binary, disabled_by=None)
        assert await hass.config_entries.async_reload(entry.entry_id)
        await eventually(lambda: state_is(binary, "on"))
        await run_blocking(
            publisher.publish_hdo_state, UNKNOWN_HDO, electrometer_id="123"
        )
        await eventually(
            lambda: state_is(binary, "unknown")
            and state_is(entity_id("123", "hdo_low_tariff_active"), "unknown")
        )
        await run_blocking(
            publisher.publish_hdo_state,
            HdoData(False, None, [("00:00", "08:00")], "TEST"),
            electrometer_id="123",
        )
        await eventually(
            lambda: state_is(binary, "off")
            and state_is(entity_id("123", "hdo_low_tariff_active"), "OFF")
        )

        before = {
            r.unique_id: r.id
            for r in er.async_entries_for_config_entry(registry, entry.entry_id)
        }
        await run_blocking(publisher.publish_discovery)
        assert await hass.config_entries.async_reload(entry.entry_id)
        await eventually(
            lambda: state_is(binary, "off")
            and state_is("sensor.my_cez_consumption", "1.5")
        )
        assert {
            r.unique_id: r.id
            for r in er.async_entries_for_config_entry(registry, entry.entry_id)
        } == before
        assert registry.async_get(binary).disabled_by is None
        assert registry.async_get(disabled).disabled_by is er.RegistryEntryDisabler.USER

        # Old availability no longer controls migrated entities.
        await publish("cez_pnd/123/availability", "offline")
        await run_blocking(publisher.publish_state, {"123": {"consumption": 3.5}})
        await eventually(lambda: state_is("sensor.my_cez_consumption", "3.5"))
        if invalid_hdo:
            return

        targets = ["sensor.my_cez_consumption", entity_id("456", "consumption"), binary]
        await run_blocking(seed.disconnect)
        await run_blocking(stop_broker)
        await eventually(
            lambda: all(state_is(target, "unavailable") for target in targets)
        )
        await eventually(lambda: not publisher._client._connected.is_set())
        with pytest.raises(ConnectionError):
            await run_blocking(
                publisher.publish_state,
                {"123": {"consumption": 5.5}, "456": {"consumption": 6.5}},
            )
        await run_blocking(start_broker)
        await eventually(
            lambda: state_is("sensor.my_cez_consumption", "5.5")
            and state_is(entity_id("456", "consumption"), "6.5")
        )
        await run_blocking(publisher.stop)
        await eventually(
            lambda: all(state_is(target, "unavailable") for target in targets)
        )

        # A new application process must restore existing entities, then its
        # abrupt death must make both meters unavailable through the shared LWT.
        script = """
import sys,time
from addon.src.mqtt_client import MQTTClientWrapper
from addon.src.mqtt_publisher import MqttPublisher
p=MqttPublisher(MQTTClientWrapper('127.0.0.1',int(sys.argv[1]),'test-user','test-password'),electrometers=[{'electrometer_id':'123'},{'electrometer_id':'456'}])
p.start()
p.publish_discovery()
p.publish_state({'123':{'consumption':7.5},'456':{'consumption':8.5}})
print('ready',flush=True)
time.sleep(900)
"""
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            str(port),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert await asyncio.wait_for(child.stdout.readline(), 10) == b"ready\n"
        await eventually(
            lambda: state_is("sensor.my_cez_consumption", "7.5")
            and state_is(entity_id("456", "consumption"), "8.5")
        )
        child.kill()
        await child.wait()
        await eventually(
            lambda: all(state_is(target, "unavailable") for target in targets)
        )
        assert registry.async_get("sensor.my_cez_consumption").id == customized.id
    finally:
        if child is not None and child.returncode is None:
            child.kill()
            await child.wait()
        await run_blocking(seed.disconnect)
        await run_blocking(publisher.stop)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_manual_yaml_migration_and_rollback(homeassistant_broker):
    hass, entry, (port, _, _) = homeassistant_broker
    registry = er.async_get(hass)
    seed = transport(port)
    publisher = MqttPublisher(transport(port), electrometers=METERS)

    def manual_state(value):
        return (
            state := hass.states.get(entity_id)
        ) is not None and state.state == value

    async def configuration(availability):
        await hass.async_add_executor_job(
            Path(hass.config.path("configuration.yaml")).write_text,
            json.dumps(manual_configuration(availability)),
        )
        assert await hass.config_entries.async_reload(entry.entry_id)

    try:
        await eventually(
            lambda: registry.async_get_entity_id(
                "sensor", "mqtt", "manual_cez_consumption"
            )
        )
        entity_id = registry.async_get_entity_id(
            "sensor", "mqtt", "manual_cez_consumption"
        )
        original = registry.async_get(entity_id)
        await run_blocking(seed.connect)
        await run_blocking(seed.publish, "cez_pnd/123/availability", "online")
        await run_blocking(seed.publish, "cez_pnd/123/consumption/state", "0.5")
        await eventually(lambda: manual_state("0.5"))

        # Follow the README: stop the old add-on, migrate YAML, reload, upgrade.
        await run_blocking(seed.publish, "cez_pnd/123/availability", "offline")
        await eventually(lambda: manual_state("unavailable"))
        await configuration("cez_pnd/availability")
        await run_blocking(publisher.start)
        await run_blocking(publisher.publish_discovery)
        await run_blocking(publisher.publish_state, {"123": {"consumption": 1.5}})
        await eventually(lambda: manual_state("1.5"))
        assert registry.async_get(entity_id).id == original.id

        # Stop before selective cleanup so replay cannot restore new configs.
        await run_blocking(publisher.stop)
        for meter in ("123", "456"):
            await run_blocking(
                seed.publish,
                f"homeassistant/binary_sensor/cez_pnd_{meter}/hdo_low_tariff_active/config",
                "",
            )
        await run_blocking(seed.publish, "cez_pnd/availability", "")
        await configuration("cez_pnd/123/availability")
        # A restored old release republishes its legacy discovery/availability.
        await run_blocking(
            seed.publish,
            "homeassistant/sensor/cez_pnd_123/consumption/config",
            json.dumps(legacy_config("123", "consumption")),
        )
        await run_blocking(seed.publish, "cez_pnd/123/availability", "online")
        await run_blocking(seed.publish, "cez_pnd/123/consumption/state", "2.5")
        await eventually(lambda: manual_state("2.5"))
        assert registry.async_get(entity_id).id == original.id
        assert (
            registry.async_get_entity_id(
                "sensor", "mqtt", "cez_pnd_123_hdo_low_tariff_active"
            )
            is not None
        )
        await eventually(
            lambda: registry.async_get_entity_id(
                "binary_sensor", "mqtt", "cez_pnd_123_hdo_low_tariff_active_binary"
            )
            is None
        )
    finally:
        await run_blocking(seed.disconnect)
        await run_blocking(publisher.stop)
