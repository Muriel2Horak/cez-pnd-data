"""End-to-end smoke tests for the CEZ PND add-on pipeline.

Simulates the full add-on lifecycle without a real MQTT broker or CEZ backend:
  1. Auth session creation (mocked Playwright)
  2. CEZ data fetch & parse
  3. MQTT Discovery payload publication
  4. State value publication

Uses the retained sample payload from evidence/ for deterministic assertions.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from addon.src.mqtt_publisher import (
    AVAILABILITY_TOPIC_TEMPLATE,
    CONFIG_TOPIC_TEMPLATE,
    STATE_TOPIC_TEMPLATE,
    MqttPublisher,
    build_discovery_payload,
    get_sensor_definitions,
)
from addon.src.parser import CezDataParser, detect_electrometer_id
from addon.src.session_manager import (
    Credentials,
    CredentialsProvider,
    SessionStore,
)
from addon.src.auth import AuthSession, PlaywrightAuthClient


# ── Fixtures ──────────────────────────────────────────────────────────

EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "evidence"
SAMPLE_PAYLOAD_PATH = EVIDENCE_DIR / "pnd-playwright-data.json"


@pytest.fixture
def sample_payload() -> dict:
    with open(SAMPLE_PAYLOAD_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def mock_mqtt_client() -> MagicMock:
    client = MagicMock()
    client.publish = MagicMock()
    client.will_set = MagicMock()
    client.connect = MagicMock()
    client.disconnect = MagicMock()
    return client


class DummyCredentialsProvider(CredentialsProvider):
    def __init__(self, email: str = "user@example.com", password: str = "secret"):
        self._credentials = Credentials(email=email, password=password)

    def get_credentials(self) -> Credentials:
        return self._credentials


# ── Scenario 1: Full pipeline smoke test ──────────────────────────────


class TestFullPipelineSmoke:
    """Simulates the complete add-on→HA sensor pipeline:
    auth → fetch → parse → discover → publish states.
    """

    @pytest.mark.asyncio
    async def test_full_pipeline_discovery_and_state(
        self, sample_payload: dict, mock_mqtt_client: MagicMock, tmp_path: Path
    ) -> None:
        # ── Step 1: Auth ──────────────────────────────────────────
        session_path = tmp_path / "session.json"
        store = SessionStore(path=session_path, ttl=timedelta(hours=6))
        creds = DummyCredentialsProvider()

        fake_cookies = [
            {"name": "JSESSIONID", "value": "smoke-test-session", "expires": 0}
        ]

        async def fake_login(_: Credentials) -> list[dict[str, Any]]:
            return fake_cookies

        auth_client = PlaywrightAuthClient(creds, store, login_runner=fake_login)
        session = await auth_client.ensure_session()

        assert isinstance(session, AuthSession)
        assert session.cookies == fake_cookies
        assert session_path.exists(), "Session file must be persisted"

        # ── Step 2: Parse CEZ data ────────────────────────────────
        meter_id = detect_electrometer_id(sample_payload)
        assert meter_id is not None, "Meter ID must be auto-detected from sample payload"
        assert meter_id == "784703"

        parser = CezDataParser(sample_payload)
        records = parser.parse_records()
        assert len(records) == 96, f"Expected 96 records, got {len(records)}"

        latest = parser.get_latest_reading()
        assert latest is not None
        assert latest.consumption_kw is not None
        assert latest.production_kw is not None
        assert latest.reactive_kw is not None

        latest_dict = parser.get_latest_reading_dict()
        assert latest_dict is not None

        # ── Step 3: MQTT Discovery ────────────────────────────────
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=meter_id)
        publisher.start()

        # Verify LWT was set before connect
        mock_mqtt_client.will_set.assert_called_once()
        mock_mqtt_client.connect.assert_called_once()

        # Verify online availability published
        avail_topic = AVAILABILITY_TOPIC_TEMPLATE.format(meter_id=meter_id)
        online_calls = [
            c for c in mock_mqtt_client.publish.call_args_list
            if c[0][0] == avail_topic and c[1].get("payload") == "online"
        ]
        assert len(online_calls) >= 1, "Must publish 'online' after connect"

        # Publish discovery
        mock_mqtt_client.publish.reset_mock()
        publisher.publish_discovery()

        # Verify all 3 discovery topics published
        sensor_defs = get_sensor_definitions()
        assert len(sensor_defs) == 3
        for sensor in sensor_defs:
            config_topic = CONFIG_TOPIC_TEMPLATE.format(
                meter_id=meter_id, key=sensor.key
            )
            matching = [
                c for c in mock_mqtt_client.publish.call_args_list
                if c[0][0] == config_topic
            ]
            assert len(matching) == 1, f"Discovery missing for {sensor.key}"

            # Validate discovery payload JSON
            payload_str = matching[0][1].get("payload")
            payload_json = json.loads(payload_str)
            assert "unique_id" in payload_json
            assert "name" in payload_json
            assert "state_topic" in payload_json
            assert "unit_of_measurement" in payload_json
            assert "device_class" in payload_json
            assert "state_class" in payload_json
            assert "device" in payload_json
            assert "availability_topic" in payload_json

            # Retained
            assert matching[0][1].get("retain") is True

        # ── Step 4: Publish state values ──────────────────────────
        mock_mqtt_client.publish.reset_mock()

        readings = {
            "consumption": latest.consumption_kw,
            "production": latest.production_kw,
            "reactive": latest.reactive_kw,
        }
        publisher.publish_state(readings)

        # Assert at least one numeric state update per sensor
        for key in ("consumption", "production", "reactive"):
            state_topic = STATE_TOPIC_TEMPLATE.format(meter_id=meter_id, key=key)
            state_calls = [
                c for c in mock_mqtt_client.publish.call_args_list
                if c[0][0] == state_topic
            ]
            assert len(state_calls) == 1, f"State missing for {key}"
            published_value = state_calls[0][1].get("payload")
            assert published_value is not None
            # Must be a parseable numeric string
            float(published_value)  # raises ValueError if not numeric

        # ── Step 5: Graceful stop ─────────────────────────────────
        mock_mqtt_client.publish.reset_mock()
        publisher.stop()

        offline_calls = [
            c for c in mock_mqtt_client.publish.call_args_list
            if c[0][0] == avail_topic and c[1].get("payload") == "offline"
        ]
        assert len(offline_calls) >= 1, "Must publish 'offline' on stop"
        mock_mqtt_client.disconnect.assert_called_once()


# ── Scenario 2: Discovery payloads are HA-schema-valid JSON ───────────


class TestDiscoverySchemaValidity:
    """Verify all discovery payloads are valid JSON with required HA fields."""

    def test_all_sensors_produce_valid_discovery_json(self) -> None:
        meter_id = "784703"
        required_fields = {
            "unique_id",
            "name",
            "state_topic",
            "unit_of_measurement",
            "device_class",
            "state_class",
            "device",
            "availability_topic",
        }

        for sensor in get_sensor_definitions():
            payload = build_discovery_payload(sensor, meter_id)

            # JSON roundtrip
            serialized = json.dumps(payload)
            deserialized = json.loads(serialized)
            assert deserialized == payload

            # All required fields present
            missing = required_fields - set(payload.keys())
            assert not missing, f"Sensor {sensor.key} missing: {missing}"

            # Device block has identifiers
            assert isinstance(payload["device"]["identifiers"], list)
            assert len(payload["device"]["identifiers"]) > 0


# ── Scenario 3: State publish produces parseable numeric values ───────


class TestStateNumericValues:
    """Verify state values published are parseable as floats."""

    def test_state_values_are_numeric_strings(
        self, sample_payload: dict, mock_mqtt_client: MagicMock
    ) -> None:
        parser = CezDataParser(sample_payload)
        latest = parser.get_latest_reading()
        assert latest is not None

        meter_id = detect_electrometer_id(sample_payload) or "unknown"
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=meter_id)

        readings = {
            "consumption": latest.consumption_kw,
            "production": latest.production_kw,
            "reactive": latest.reactive_kw,
        }
        publisher.publish_state(readings)

        for c in mock_mqtt_client.publish.call_args_list:
            topic = c[0][0]
            if "/state" in topic:
                payload = c[1].get("payload")
                # Must be parseable as float
                parsed = float(payload)
                assert parsed >= 0, f"Negative power value on {topic}"


# ── Scenario 4: Session persistence across cycles ────────────────────


class TestSessionPersistence:
    """Verify session reuse avoids re-login."""

    @pytest.mark.asyncio
    async def test_second_cycle_reuses_session(self, tmp_path: Path) -> None:
        session_path = tmp_path / "session.json"
        store = SessionStore(path=session_path, ttl=timedelta(hours=6))
        creds = DummyCredentialsProvider()

        login_count = {"n": 0}

        async def counting_login(_: Credentials) -> list[dict[str, Any]]:
            login_count["n"] += 1
            return [{"name": "JSESSIONID", "value": "test", "expires": 0}]

        client = PlaywrightAuthClient(creds, store, login_runner=counting_login)

        # First cycle: should login
        s1 = await client.ensure_session()
        assert s1.reused is False
        assert login_count["n"] == 1

        # Second cycle: should reuse
        s2 = await client.ensure_session()
        assert s2.reused is True
        assert login_count["n"] == 1, "Login should NOT be called again"
