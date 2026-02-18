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
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from addon.src.auth import AuthSession, PlaywrightAuthClient
from addon.src.mqtt_publisher import (
    AVAILABILITY_TOPIC_TEMPLATE,
    CONFIG_TOPIC_TEMPLATE,
    STATE_TOPIC_TEMPLATE,
    MqttPublisher,
    build_discovery_payload,
    get_hdo_sensor_definitions,
    get_sensor_definitions,
)
from addon.src.orchestrator import Orchestrator, OrchestratorConfig
from addon.src.parser import CezDataParser, detect_electrometer_id
from addon.src.session_manager import Credentials, CredentialsProvider, SessionStore

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
        assert (
            meter_id is not None
        ), "Meter ID must be auto-detected from sample payload"
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
            c
            for c in mock_mqtt_client.publish.call_args_list
            if c[0][0] == avail_topic and c[1].get("payload") == "online"
        ]
        assert len(online_calls) >= 1, "Must publish 'online' after connect"

        # Publish discovery
        mock_mqtt_client.publish.reset_mock()
        publisher.publish_discovery()

        # Verify all 17 discovery topics published (13 PND + 4 HDO)
        sensor_defs = get_sensor_definitions()
        hdo_defs = get_hdo_sensor_definitions()
        all_defs = sensor_defs + hdo_defs
        assert len(all_defs) == 17
        for sensor in all_defs:
            config_topic = CONFIG_TOPIC_TEMPLATE.format(
                meter_id=meter_id, key=sensor.key
            )
            matching = [
                c
                for c in mock_mqtt_client.publish.call_args_list
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
                c
                for c in mock_mqtt_client.publish.call_args_list
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
            c
            for c in mock_mqtt_client.publish.call_args_list
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

        for sensor in get_sensor_definitions() + get_hdo_sensor_definitions():
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


# ── Scenario 5: Full 17-sensor pipeline via Orchestrator ─────────────


_ASSEMBLY_PAYLOADS: dict[int, dict] = {
    -1003: {
        "hasData": True,
        "columns": [
            {"id": "1000", "name": "Datum", "unit": None},
            {"id": "1001", "name": "+A/784703", "unit": "kW"},
            {"id": "1002", "name": "-A/784703", "unit": "kW"},
            {"id": "1003", "name": "Rv/784703", "unit": "kW"},
        ],
        "values": [
            {
                "1000": {"v": "14.02.2026 00:15"},
                "1001": {"v": "1,42", "s": 32},
                "1002": {"v": "0,0", "s": 32},
                "1003": {"v": "5,46", "s": 32},
            },
        ],
    },
    -1012: {
        "hasData": True,
        "columns": [
            {"id": "2000", "name": "Datum", "unit": None},
            {"id": "2001", "name": "Profil +A", "unit": "kW"},
            {"id": "2002", "name": "Profil +Ri", "unit": "kW"},
            {"id": "2003", "name": "Profil -Rc", "unit": "kW"},
        ],
        "values": [
            {
                "2000": {"v": "14.02.2026 00:15"},
                "2001": {"v": "1,42", "s": 32},
                "2002": {"v": "0,31", "s": 32},
                "2003": {"v": "0,12", "s": 32},
            },
        ],
    },
    -1011: {
        "hasData": True,
        "columns": [
            {"id": "3000", "name": "Datum", "unit": None},
            {"id": "3001", "name": "Profil -A", "unit": "kW"},
            {"id": "3002", "name": "Profil -Ri", "unit": "kW"},
            {"id": "3003", "name": "Profil +Rc", "unit": "kW"},
        ],
        "values": [
            {
                "3000": {"v": "14.02.2026 00:15"},
                "3001": {"v": "0,05", "s": 32},
                "3002": {"v": "0,02", "s": 32},
                "3003": {"v": "0,01", "s": 32},
            },
        ],
    },
    -1021: {
        "hasData": True,
        "columns": [
            {"id": "4000", "name": "Datum", "unit": None},
            {"id": "4001", "name": "+A d/784703", "unit": "kWh"},
        ],
        "values": [
            {
                "4000": {"v": "14.02.2026 00:15"},
                "4001": {"v": "23,45", "s": 32},
            },
        ],
    },
    -1022: {
        "hasData": True,
        "columns": [
            {"id": "5000", "name": "Datum", "unit": None},
            {"id": "5001", "name": "-A d/784703", "unit": "kWh"},
        ],
        "values": [
            {
                "5000": {"v": "14.02.2026 00:15"},
                "5001": {"v": "1,23", "s": 32},
            },
        ],
    },
    -1027: {
        "hasData": True,
        "columns": [
            {"id": "6000", "name": "Datum", "unit": None},
            {"id": "6001", "name": "+E/784703", "unit": "kWh"},
            {"id": "6002", "name": "-E/784703", "unit": "kWh"},
            {"id": "6003", "name": "+E_NT/784703", "unit": "kWh"},
            {"id": "6004", "name": "+E_VT/784703", "unit": "kWh"},
        ],
        "values": [
            {
                "6000": {"v": "14.02.2026 00:15"},
                "6001": {"v": "12345,67", "s": 32},
                "6002": {"v": "234,56", "s": 32},
                "6003": {"v": "8000,00", "s": 32},
                "6004": {"v": "4345,67", "s": 32},
            },
        ],
    },
}

_HDO_RAW_RESPONSE: dict[str, Any] = {
    "signals": [
        {
            "signal": "EVV2",
            "den": "Sobota",
            "datum": "14.02.2026",
            "casy": "00:00-08:00;   09:00-12:00;   13:00-15:00;   16:00-19:00;   20:00-24:00",
        }
    ]
}


class TestFull17SensorPipeline:
    """Orchestrator → 6 assembly fetches → parser → MQTT: 13 PND + 4 HDO sensors."""

    @pytest.mark.asyncio
    async def test_orchestrator_publishes_all_13_pnd_sensors(
        self, tmp_path: Path, mock_mqtt_client: MagicMock
    ) -> None:
        session_path = tmp_path / "session.json"
        store = SessionStore(path=session_path, ttl=timedelta(hours=6))
        creds = DummyCredentialsProvider()

        fake_cookies = [{"name": "JSESSIONID", "value": "e2e-17", "expires": 0}]

        async def fake_login(_: Credentials) -> list[dict[str, Any]]:
            return fake_cookies

        auth_client = PlaywrightAuthClient(creds, store, login_runner=fake_login)

        async def mock_fetcher(cookies: Any, **kwargs: Any) -> dict:
            assembly_id = kwargs.get("assembly_id", 0)
            return _ASSEMBLY_PAYLOADS.get(
                assembly_id, {"hasData": False, "columns": [], "values": []}
            )

        meter_id = "784703"
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=meter_id)

        config = OrchestratorConfig(meter_id=meter_id, poll_interval_seconds=900)
        orch = Orchestrator(
            config=config,
            auth_client=auth_client,
            fetcher=mock_fetcher,
            mqtt_publisher=publisher,
        )

        publisher.start()
        publisher.publish_discovery()

        mock_mqtt_client.publish.reset_mock()
        await orch.run_once()

        expected_sensors = {
            "consumption": 1.42,
            "production": 0.05,
            "reactive": 5.46,
            "reactive_import_inductive": 0.31,
            "reactive_export_capacitive": 0.12,
            "reactive_export_inductive": 0.02,
            "reactive_import_capacitive": 0.01,
            "daily_consumption": 23.45,
            "daily_production": 1.23,
            "register_consumption": 12345.67,
            "register_production": 234.56,
            "register_low_tariff": 8000.0,
            "register_high_tariff": 4345.67,
        }

        for key, expected_value in expected_sensors.items():
            state_topic = STATE_TOPIC_TEMPLATE.format(meter_id=meter_id, key=key)
            state_calls = [
                c
                for c in mock_mqtt_client.publish.call_args_list
                if c[0][0] == state_topic
            ]
            assert len(state_calls) == 1, f"State missing for {key}"
            published_value = float(state_calls[0][1].get("payload"))
            assert published_value == pytest.approx(
                expected_value
            ), f"{key}: expected {expected_value}, got {published_value}"

    @pytest.mark.asyncio
    async def test_discovery_publishes_17_configs(
        self, mock_mqtt_client: MagicMock
    ) -> None:
        meter_id = "784703"
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=meter_id)
        publisher.start()

        mock_mqtt_client.publish.reset_mock()
        publisher.publish_discovery()

        all_defs = get_sensor_definitions() + get_hdo_sensor_definitions()
        assert len(all_defs) == 17

        for sensor in all_defs:
            config_topic = CONFIG_TOPIC_TEMPLATE.format(
                meter_id=meter_id, key=sensor.key
            )
            matching = [
                c
                for c in mock_mqtt_client.publish.call_args_list
                if c[0][0] == config_topic
            ]
            assert len(matching) == 1, f"Discovery missing for {sensor.key}"

    @pytest.mark.asyncio
    async def test_orchestrator_publishes_hdo_sensors(
        self, tmp_path: Path, mock_mqtt_client: MagicMock
    ) -> None:
        session_path = tmp_path / "session.json"
        store = SessionStore(path=session_path, ttl=timedelta(hours=6))
        creds = DummyCredentialsProvider()

        fake_cookies = [{"name": "JSESSIONID", "value": "e2e-hdo", "expires": 0}]

        async def fake_login(_: Credentials) -> list[dict[str, Any]]:
            return fake_cookies

        auth_client = PlaywrightAuthClient(creds, store, login_runner=fake_login)

        async def mock_fetcher(cookies: Any, **kwargs: Any) -> dict:
            assembly_id = kwargs.get("assembly_id", 0)
            return _ASSEMBLY_PAYLOADS.get(
                assembly_id, {"hasData": False, "columns": [], "values": []}
            )

        hdo_fetcher = AsyncMock(return_value=_HDO_RAW_RESPONSE)

        meter_id = "784703"
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=meter_id)

        config = OrchestratorConfig(
            meter_id=meter_id,
            ean="859182400100000001",
            poll_interval_seconds=900,
        )
        orch = Orchestrator(
            config=config,
            auth_client=auth_client,
            fetcher=mock_fetcher,
            mqtt_publisher=publisher,
            hdo_fetcher=hdo_fetcher,
        )

        publisher.start()
        publisher.publish_discovery()
        mock_mqtt_client.publish.reset_mock()

        await orch.run_once()

        hdo_keys = [
            "hdo_low_tariff_active",
            "hdo_next_switch",
            "hdo_schedule_today",
            "hdo_signal",
        ]
        for key in hdo_keys:
            state_topic = STATE_TOPIC_TEMPLATE.format(meter_id=meter_id, key=key)
            state_calls = [
                c
                for c in mock_mqtt_client.publish.call_args_list
                if c[0][0] == state_topic
            ]
            assert len(state_calls) == 1, f"HDO state missing for {key}"
            payload = state_calls[0][1].get("payload")
            assert payload is not None and len(payload) > 0

    @pytest.mark.asyncio
    async def test_full_pipeline_17_sensors_all_published(
        self, tmp_path: Path, mock_mqtt_client: MagicMock
    ) -> None:
        session_path = tmp_path / "session.json"
        store = SessionStore(path=session_path, ttl=timedelta(hours=6))
        creds = DummyCredentialsProvider()

        fake_cookies = [{"name": "JSESSIONID", "value": "e2e-full", "expires": 0}]

        async def fake_login(_: Credentials) -> list[dict[str, Any]]:
            return fake_cookies

        auth_client = PlaywrightAuthClient(creds, store, login_runner=fake_login)

        async def mock_fetcher(cookies: Any, **kwargs: Any) -> dict:
            assembly_id = kwargs.get("assembly_id", 0)
            return _ASSEMBLY_PAYLOADS.get(
                assembly_id, {"hasData": False, "columns": [], "values": []}
            )

        hdo_fetcher = AsyncMock(return_value=_HDO_RAW_RESPONSE)

        meter_id = "784703"
        publisher = MqttPublisher(client=mock_mqtt_client, meter_id=meter_id)

        config = OrchestratorConfig(
            meter_id=meter_id,
            ean="859182400100000001",
            poll_interval_seconds=900,
        )
        orch = Orchestrator(
            config=config,
            auth_client=auth_client,
            fetcher=mock_fetcher,
            mqtt_publisher=publisher,
            hdo_fetcher=hdo_fetcher,
        )

        publisher.start()
        publisher.publish_discovery()
        mock_mqtt_client.publish.reset_mock()

        await orch.run_once()

        all_expected_topics = set()
        pnd_keys = [s.key for s in get_sensor_definitions()]
        hdo_keys = [s.key for s in get_hdo_sensor_definitions()]
        for key in pnd_keys + hdo_keys:
            all_expected_topics.add(
                STATE_TOPIC_TEMPLATE.format(meter_id=meter_id, key=key)
            )

        published_topics = {c[0][0] for c in mock_mqtt_client.publish.call_args_list}
        assert all_expected_topics.issubset(
            published_topics
        ), f"Missing topics: {all_expected_topics - published_topics}"
