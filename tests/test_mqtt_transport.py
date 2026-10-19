"""MQTT acknowledgement tests and opt-in real Mosquitto integration."""

from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import paho.mqtt.client as mqtt
import pytest

from addon.src.mqtt_client import MQTTClientWrapper
from addon.src.mqtt_publisher import MqttPublisher


def transport_mock():
    raw = MagicMock()
    raw.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
    raw.publish.return_value.is_published.return_value = True
    with patch("addon.src.mqtt_client.mqtt.Client", return_value=raw):
        client = MQTTClientWrapper(
            "broker",
            1883,
            "user",
            "password",
            timeout=0.01,
            startup_timeout=0.03,
            replay_retry_delay=0.01,
        )
    return client, raw


def test_connack_required_and_rejected_authentication_has_no_online_log(caplog):
    client, raw = transport_mock()

    def reject():
        raw.on_connect(raw, None, None, SimpleReason(True), None)

    raw.loop_start.side_effect = reject
    publisher = MqttPublisher(client, electrometer_id="123")
    with pytest.raises(ConnectionError, match="rejected"):
        publisher.start()
    raw.publish.assert_not_called()
    assert "online" not in caplog.text
    raw.loop_stop.assert_called_once()


class SimpleReason:
    def __init__(self, failure):
        self.is_failure = failure

    def __str__(self):
        return "not authorized" if self.is_failure else "success"


def test_publish_acknowledgement_and_failure_paths():
    client, raw = transport_mock()
    raw.loop_start.side_effect = lambda: raw.on_connect(
        raw, None, None, SimpleReason(False), None
    )
    client.connect()
    client.publish("topic", "value")
    raw.publish.return_value.wait_for_publish.assert_called_once_with(timeout=0.01)
    raw.publish.return_value.is_published.return_value = False
    with pytest.raises(TimeoutError, match="acknowledgement"):
        client.publish("topic", "next")
    raw.publish.return_value.rc = mqtt.MQTT_ERR_NO_CONN
    with pytest.raises(ConnectionError, match="publish failed"):
        client.publish("topic", "next")
    raw.on_disconnect(raw, None, None, None, None)
    with pytest.raises(ConnectionError, match="disconnected"):
        client.publish("topic", "next")
    client.disconnect()
    raw.loop_stop.assert_called_once()


def test_connection_timeout_and_tls():
    client, raw = transport_mock()
    with pytest.raises(ConnectionError, match="timed out"):
        client.connect()
    raw.loop_stop.assert_called_once()
    with patch("addon.src.mqtt_client.mqtt.Client", return_value=raw):
        MQTTClientWrapper("broker", 8883, "u", "p", ssl=True)
    raw.tls_set.assert_called_once()


def test_reconnect_replays_latest_retained_messages():
    client, raw = transport_mock()
    raw.loop_start.side_effect = lambda: raw.on_connect(
        raw, None, None, SimpleReason(False), None
    )
    client.connect()
    client.publish("state", "old")
    client.publish("state", "new")
    client.publish("config", "discovery")
    raw.publish.reset_mock()
    client._replay()
    assert raw.publish.call_args_list[0].args == ("state", "new", 1, True)
    assert raw.publish.call_args_list[1].args == ("config", "discovery", 1, True)
    client.disconnect()


@pytest.fixture
def broker(tmp_path):
    executable = os.getenv("MOSQUITTO_EXECUTABLE") or shutil.which("mosquitto")
    passwd = os.getenv("MOSQUITTO_PASSWD_EXECUTABLE") or shutil.which(
        "mosquitto_passwd"
    )
    if not executable or not passwd:
        if os.getenv("REQUIRE_MQTT_INTEGRATION"):
            pytest.fail("Mosquitto and mosquitto_passwd are required")
        pytest.skip("Install Mosquitto to run broker integration tests")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    password_file = tmp_path / "passwords"
    subprocess.run(
        [passwd, "-b", "-c", str(password_file), "test-user", "test-password"],
        check=True,
    )
    # A system Mosquitto may drop privileges when tests run as root.
    tmp_path.chmod(0o755)
    config = tmp_path / "mosquitto.conf"
    config.write_text(
        f"listener {port} 127.0.0.1\nallow_anonymous false\npassword_file {password_file}\n"
    )
    process = None

    def start():
        nonlocal process
        process = subprocess.Popen(
            [executable, "-c", str(config)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Mosquitto failed to start")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    return
            except OSError:
                time.sleep(0.02)
        raise TimeoutError("Mosquitto startup timed out")

    def stop():
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)

    start()
    try:
        yield port, stop, start
    finally:
        stop()


class Observer:
    def __init__(self, port):
        self.messages = queue.Queue()
        self.seen = {}
        self.ready = threading.Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.username_pw_set("test-user", "test-password")
        self.client.on_connect = self._connect
        self.client.on_subscribe = lambda *args: self.ready.set()
        self.client.on_message = lambda c, u, m: self.messages.put(
            (m.topic, m.payload.decode())
        )
        self.client.connect("127.0.0.1", port)
        self.client.loop_start()
        assert self.ready.wait(5)

    def _connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe("#", qos=1)

    def wait(self, topic, payload=None, timeout=8):
        if topic in self.seen and (payload is None or self.seen[topic] == payload):
            return self.seen[topic]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                found = self.messages.get(
                    timeout=max(0.01, deadline - time.monotonic())
                )
            except queue.Empty:
                break
            self.seen[found[0]] = found[1]
            if found[0] == topic and (payload is None or found[1] == payload):
                return found[1]
        raise AssertionError(f"Missing {topic}: {payload}")

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()


@pytest.mark.integration
def test_real_broker_auth_delivery_reconnect_and_graceful_stop(broker):
    port, stop, start = broker
    with pytest.raises(ConnectionError, match="rejected"):
        MQTTClientWrapper("127.0.0.1", port, "test-user", "wrong").connect()
    observer = Observer(port)
    publisher = MqttPublisher(
        MQTTClientWrapper("127.0.0.1", port, "test-user", "test-password"),
        electrometers=[{"electrometer_id": "123"}, {"electrometer_id": "456"}],
    )
    try:
        publisher.start()
        publisher.publish_discovery()
        publisher.publish_state(
            {"123": {"consumption": 1.5}, "456": {"consumption": 2.5}}
        )
        observer.wait("cez_pnd/456/consumption/state", "2.5")
        observer.close()
        stop()
        deadline = time.monotonic() + 2
        while publisher._client._connected.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not publisher._client._connected.is_set()
        with pytest.raises(ConnectionError):
            publisher.publish_state(
                {"123": {"consumption": 3.5}, "456": {"consumption": 4.5}}
            )
        start()
        observer = Observer(port)
        # Broker retention was lost. Replay must use readings obtained during
        # the outage, including meters after the first disconnected publish.
        observer.wait("cez_pnd/123/consumption/state", "3.5")
        observer.wait("cez_pnd/456/consumption/state", "4.5")
        discovery = json.loads(
            observer.wait(
                "homeassistant/binary_sensor/cez_pnd_456/hdo_low_tariff_active/config"
            )
        )
        assert discovery["availability_topic"] == "cez_pnd/availability"
        publisher.stop()
        observer.wait("cez_pnd/availability", "offline")
    finally:
        try:
            publisher.stop()
        finally:
            observer.close()


@pytest.mark.integration
def test_real_broker_crash_marks_all_meters_unavailable(broker):
    port, _, _ = broker
    observer = Observer(port)
    script = """
import sys,time
from addon.src.mqtt_client import MQTTClientWrapper
from addon.src.mqtt_publisher import MqttPublisher
p=MqttPublisher(MQTTClientWrapper("127.0.0.1",int(sys.argv[1]),"test-user","test-password"),electrometers=[{"electrometer_id":"123"},{"electrometer_id":"456"}])
p.start()
p.publish_discovery()
print("ready",flush=True)
time.sleep(900)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(port)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        observer.wait("cez_pnd/availability", "online")
        process.kill()
        process.wait(timeout=5)
        observer.wait("cez_pnd/availability", "offline")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        observer.close()


@pytest.mark.integration
def test_real_broker_initial_connection_recovers_when_listener_starts_later(broker):
    port, stop, start = broker
    stop()
    client = MQTTClientWrapper(
        "127.0.0.1",
        port,
        "test-user",
        "test-password",
        timeout=0.2,
        startup_timeout=5,
    )
    refused = threading.Event()
    client._client.on_connect_fail = lambda *args: refused.set()
    outcome = queue.Queue()

    def connect():
        try:
            client.connect()
            outcome.put(None)
        except Exception as exc:
            outcome.put(exc)

    worker = threading.Thread(target=connect, daemon=True)
    worker.start()
    try:
        assert refused.wait(2)
        start()
        error = outcome.get(timeout=5)
        assert error is None, str(error)
        assert client._connected.is_set()
    finally:
        client.disconnect()
        worker.join(timeout=1)
    assert not worker.is_alive()
