"""Synchronous acknowledged MQTT transport; call it outside the asyncio thread."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MQTTClientWrapper:
    """Wrapper for paho.mqtt.client with acknowledged delivery and recovery."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        ssl: bool = False,
        timeout: float = 5,
        startup_timeout: float = 60,
        replay_retry_delay: float = 1,
    ) -> None:
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        if username:
            self._client.username_pw_set(username, password)
        if ssl:
            self._client.tls_set()
        self._client.connect_timeout = timeout
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._host, self._port, self._timeout = host, port, timeout
        self._ready = threading.Event()
        self._connected = threading.Event()
        self._lock = threading.Lock()
        self._disconnect_lock = threading.Lock()
        self._shutdown = threading.Event()
        self._replay_requested = threading.Event()
        self._replay_thread: threading.Thread | None = None
        self._startup_timeout = startup_timeout
        self._replay_retry_delay = replay_retry_delay
        self._retained: dict[str, tuple[str, int]] = {}
        self._will: tuple[str, str, int, bool] | None = None
        self._ever_connected = False
        self._error: str | None = None

    def _on_connect(
        self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any
    ) -> None:
        if reason_code.is_failure:
            self._connected.clear()
            if getattr(reason_code, "value", None) in (136, 137):
                # Server unavailable/busy: let Paho retry until startup deadline.
                return
            self._error = f"MQTT authentication/connection rejected: {reason_code}"
        else:
            self._connected.set()
            if self._ever_connected and not self._shutdown.is_set():
                # Never wait for PUBACK from the Paho network thread itself.
                self._replay_requested.set()
            self._ever_connected = True
            self._error = None
        self._ready.set()

    def _on_disconnect(
        self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any
    ) -> None:
        self._connected.clear()

    def _replay_worker(self) -> None:
        while True:
            self._replay_requested.wait()
            self._replay_requested.clear()
            if self._shutdown.is_set():
                return
            self._replay()

    def _replay(self) -> None:
        # Only the replay worker calls this in production.
        with self._lock:
            topics = list(self._retained)
        for topic in topics:
            while not self._shutdown.is_set() and self._connected.is_set():
                try:
                    with self._lock:
                        payload, qos = self._retained[topic]
                        self._send(topic, payload, qos, True)
                    break
                except (ConnectionError, TimeoutError, RuntimeError):
                    logger.warning("MQTT reconnect replay interrupted; retrying")
                    # A delayed PUBACK need not cause another on_connect callback.
                    # Retry this topic without repeating acknowledged topics.
                    if self._shutdown.wait(self._replay_retry_delay):
                        return
            else:
                return

    def will_set(
        self, topic: str, payload: str, qos: int = 1, retain: bool = True
    ) -> None:
        """Set Last Will and Testament."""
        self._client.will_set(topic, payload, qos, retain)
        self._will = (topic, payload, qos, retain)

    def connect(self) -> None:
        """Start the network loop and wait for the broker to accept connection."""
        if self._shutdown.is_set():
            raise ConnectionError("MQTT startup cancelled")
        self._ready.clear()
        if self._replay_thread is None or not self._replay_thread.is_alive():
            self._replay_thread = threading.Thread(
                target=self._replay_worker, daemon=True
            )
            self._replay_thread.start()
        self._client.connect_async(self._host, self._port, 60)
        self._client.loop_start()
        # Keep the loop running through refused TCP connections. Paho retries
        # with backoff; authentication refusal wakes this wait immediately.
        ready = self._ready.wait(self._startup_timeout)
        if not ready or not self._connected.is_set() or self._shutdown.is_set():
            error = self._error or (
                "MQTT startup cancelled"
                if self._shutdown.is_set()
                else "MQTT connection timed out"
            )
            self.disconnect()
            raise ConnectionError(error)

    def _send(
        self,
        topic: str,
        payload: str,
        qos: int,
        retain: bool,
        *,
        shutdown: bool = False,
    ) -> None:
        if not self._connected.is_set() or (self._shutdown.is_set() and not shutdown):
            raise ConnectionError("MQTT broker is disconnected or stopping")
        info = self._client.publish(topic, payload, qos, retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"MQTT publish failed: {mqtt.error_string(info.rc)}")
        remaining = min(self._timeout, 1) if shutdown else self._timeout
        deadline = time.monotonic() + remaining
        while True:
            if self._shutdown.is_set() and not shutdown:
                raise ConnectionError("MQTT publish cancelled during shutdown")
            info.wait_for_publish(timeout=min(0.1, remaining))
            if info.is_published():
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("MQTT publish acknowledgement timed out")

    def cache_retained(self, messages: list[tuple[str, str]]) -> None:
        """Stage an entire state update before any network operation can fail."""
        with self._lock:
            if self._shutdown.is_set():
                raise ConnectionError("MQTT publisher is stopping")
            self._retained.update({topic: (payload, 1) for topic, payload in messages})

    def publish(
        self,
        topic: str,
        payload: str,
        qos: int = 1,
        retain: bool = True,
    ) -> None:
        """Publish a message, wait for acknowledgement, and cache retained data."""
        # After cooperative stop, permit only the registered final availability
        # message. Keep the ordinary Paho-compatible publish interface.
        shutdown = (
            self._shutdown.is_set() and (topic, payload, qos, retain) == self._will
        )
        with self._lock:
            if self._shutdown.is_set() and not shutdown:
                raise ConnectionError("MQTT broker is disconnected or stopping")
            if retain:
                self._retained[topic] = (payload, qos)
            try:
                self._send(topic, payload, qos, retain, shutdown=shutdown)
            except (ConnectionError, TimeoutError, RuntimeError):
                if retain and not self._shutdown.is_set():
                    self._replay_requested.set()
                raise

    def begin_shutdown(self) -> None:
        """Interrupt connection/replay/ack waits without blocking the event loop."""
        self._shutdown.set()
        self._ready.set()
        self._replay_requested.set()

    def disconnect(self) -> None:
        """Disconnect from MQTT broker and stop the network loop."""
        self.begin_shutdown()
        with self._disconnect_lock:
            try:
                self._client.disconnect()
            finally:
                self._client.loop_stop()
                self._connected.clear()
