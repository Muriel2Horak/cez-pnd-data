"""Tests for CEZ PND data parser — RED phase first, then GREEN.

Tests cover:
- Czech decimal format parsing (comma as separator)
- Czech timestamp normalization (DD.MM.YYYY HH:MM, 24:00 edge case)
- Column discovery (dynamic, not fixed order)
- Electrometer ID auto-detection from column headers
- Manual fallback when auto-detection fails
- Latest reading extraction
- Full record parsing (96 quarter-hour intervals)
- Edge cases: missing values, empty payload, partial data
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

# Module under test — will fail until implemented (RED phase)
from addon.src.parser import (
    CezDataParser,
    ParsedReading,
    detect_electrometer_id,
    parse_czech_decimal,
    parse_czech_timestamp,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "evidence"
SAMPLE_PAYLOAD_PATH = EVIDENCE_DIR / "pnd-playwright-data.json"


@pytest.fixture
def sample_payload() -> dict:
    """Load the canonical CEZ PND sample payload."""
    with open(SAMPLE_PAYLOAD_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def parser(sample_payload: dict) -> CezDataParser:
    """Create a parser loaded with the sample payload."""
    return CezDataParser(sample_payload)


@pytest.fixture
def minimal_payload() -> dict:
    """A minimal valid payload with 2 records."""
    return {
        "hasData": True,
        "size": 2,
        "columns": [
            {"id": "1000", "name": "Datum", "unit": None},
            {"id": "1001", "name": "+A/999999", "unit": "kW"},
            {"id": "1002", "name": "-A/999999", "unit": "kW"},
            {"id": "1003", "name": "Rv/999999", "unit": "kW"},
        ],
        "values": [
            {
                "1000": {"v": "01.01.2026 00:15"},
                "1001": {"v": "1,5", "s": 32},
                "1002": {"v": "0,0", "s": 32},
                "1003": {"v": "3,14", "s": 32},
            },
            {
                "1000": {"v": "01.01.2026 00:30"},
                "1001": {"v": "2,0", "s": 32},
                "1002": {"v": "0,1", "s": 32},
                "1003": {"v": "4,0", "s": 32},
            },
        ],
        "statuses": {"32": {"n": "naměřená data OK", "c": "#222222", "m": 32}},
    }


@pytest.fixture
def payload_no_meter_columns() -> dict:
    """Payload with columns that have no meter ID in the name."""
    return {
        "hasData": True,
        "size": 1,
        "columns": [
            {"id": "1000", "name": "Datum", "unit": None},
            {"id": "1001", "name": "Consumption", "unit": "kW"},
            {"id": "1002", "name": "Production", "unit": "kW"},
        ],
        "values": [
            {
                "1000": {"v": "01.01.2026 00:15"},
                "1001": {"v": "1,0", "s": 32},
                "1002": {"v": "0,5", "s": 32},
            },
        ],
        "statuses": {},
    }


# ===========================================================================
# 1. Czech decimal format parsing
# ===========================================================================


class TestParseCzechDecimal:
    """parse_czech_decimal converts '1,42' -> 1.42 etc."""

    def test_simple_comma(self):
        assert parse_czech_decimal("1,42") == 1.42

    def test_zero(self):
        assert parse_czech_decimal("0,0") == 0.0

    def test_large_number(self):
        assert parse_czech_decimal("11,652") == 11.652

    def test_sub_one(self):
        assert parse_czech_decimal("0,759") == 0.759

    def test_already_dot_format(self):
        """Should handle '1.42' if API ever switches to dot format."""
        assert parse_czech_decimal("1.42") == 1.42

    def test_integer_string(self):
        assert parse_czech_decimal("5") == 5.0

    def test_none_returns_none(self):
        assert parse_czech_decimal(None) is None

    def test_empty_string_returns_none(self):
        assert parse_czech_decimal("") is None

    def test_non_numeric_returns_none(self):
        assert parse_czech_decimal("N/A") is None


# ===========================================================================
# 2. Czech timestamp normalization
# ===========================================================================


class TestParseCzechTimestamp:
    """parse_czech_timestamp converts 'DD.MM.YYYY HH:MM' -> datetime."""

    def test_standard_timestamp(self):
        result = parse_czech_timestamp("14.02.2026 00:15")
        assert result == datetime(2026, 2, 14, 0, 15)

    def test_midnight_24_edge_case(self):
        """CEZ uses '24:00' to mean midnight of the next day."""
        result = parse_czech_timestamp("14.02.2026 24:00")
        assert result == datetime(2026, 2, 15, 0, 0)

    def test_noon(self):
        result = parse_czech_timestamp("01.06.2025 12:00")
        assert result == datetime(2025, 6, 1, 12, 0)

    def test_none_returns_none(self):
        assert parse_czech_timestamp(None) is None

    def test_empty_returns_none(self):
        assert parse_czech_timestamp("") is None

    def test_invalid_format_returns_none(self):
        assert parse_czech_timestamp("2026-02-14 00:15") is None


# ===========================================================================
# 3. Electrometer ID auto-detection
# ===========================================================================


class TestDetectElectrometerId:
    """detect_electrometer_id extracts meter ID from column headers."""

    def test_detects_from_plus_a_column(self, sample_payload):
        meter_id = detect_electrometer_id(sample_payload)
        assert meter_id == "784703"

    def test_detects_from_minimal(self, minimal_payload):
        meter_id = detect_electrometer_id(minimal_payload)
        assert meter_id == "999999"

    def test_returns_none_when_no_meter_columns(self, payload_no_meter_columns):
        meter_id = detect_electrometer_id(payload_no_meter_columns)
        assert meter_id is None

    def test_returns_none_for_empty_payload(self):
        meter_id = detect_electrometer_id({})
        assert meter_id is None

    def test_returns_none_for_no_columns(self):
        meter_id = detect_electrometer_id({"columns": []})
        assert meter_id is None

    def test_fallback_parameter(self, payload_no_meter_columns):
        """When auto-detect fails, configured fallback is used."""
        meter_id = detect_electrometer_id(
            payload_no_meter_columns, fallback_id="MANUAL123"
        )
        assert meter_id == "MANUAL123"

    def test_fallback_not_used_when_detected(self, sample_payload):
        """Fallback is ignored when auto-detect succeeds."""
        meter_id = detect_electrometer_id(sample_payload, fallback_id="SHOULD_NOT_USE")
        assert meter_id == "784703"


# ===========================================================================
# 4. Column discovery (dynamic, not fixed order)
# ===========================================================================


class TestColumnDiscovery:
    """Parser must discover column IDs dynamically from headers."""

    def test_discovers_timestamp_column(self, parser):
        assert parser.timestamp_col_id == "1000"

    def test_discovers_consumption_column(self, parser):
        assert parser.consumption_col_id == "1001"

    def test_discovers_production_column(self, parser):
        assert parser.production_col_id == "1002"

    def test_discovers_reactive_column(self, parser):
        assert parser.reactive_col_id == "1003"

    def test_reordered_columns(self):
        """Columns in different order should still be discovered."""
        payload = {
            "hasData": True,
            "size": 1,
            "columns": [
                {"id": "2000", "name": "Rv/111", "unit": "kW"},
                {"id": "2001", "name": "Datum", "unit": None},
                {"id": "2002", "name": "-A/111", "unit": "kW"},
                {"id": "2003", "name": "+A/111", "unit": "kW"},
            ],
            "values": [
                {
                    "2001": {"v": "01.01.2026 00:15"},
                    "2003": {"v": "1,0", "s": 32},
                    "2002": {"v": "0,5", "s": 32},
                    "2000": {"v": "3,0", "s": 32},
                },
            ],
            "statuses": {},
        }
        p = CezDataParser(payload)
        assert p.timestamp_col_id == "2001"
        assert p.consumption_col_id == "2003"
        assert p.production_col_id == "2002"
        assert p.reactive_col_id == "2000"


# ===========================================================================
# 5. Full record parsing
# ===========================================================================


class TestParseRecords:
    """parse_records returns list of ParsedReading for all values."""

    def test_record_count(self, parser):
        records = parser.parse_records()
        assert len(records) == 96

    def test_first_record_values(self, parser):
        records = parser.parse_records()
        first = records[0]
        assert first.timestamp == datetime(2026, 2, 14, 0, 15)
        assert first.consumption_kw == 1.42
        assert first.production_kw == 0.0
        assert first.reactive_kw == 5.46

    def test_last_record_values(self, parser):
        records = parser.parse_records()
        last = records[-1]
        # "14.02.2026 24:00" -> 15.02.2026 00:00
        assert last.timestamp == datetime(2026, 2, 15, 0, 0)
        assert last.consumption_kw == 11.652
        assert last.production_kw == 0.0
        assert last.reactive_kw == 5.46

    def test_record_with_nonzero_production(self, parser):
        """Record at 09:45 has production 0,001 kW."""
        records = parser.parse_records()
        # 09:45 is the 39th 15-min interval (0:15 is index 0 → 09:45 is index 38)
        rec_0945 = [r for r in records if r.timestamp == datetime(2026, 2, 14, 9, 45)]
        assert len(rec_0945) == 1
        assert rec_0945[0].production_kw == 0.001

    def test_record_is_dataclass_or_namedtuple(self, parser):
        records = parser.parse_records()
        first = records[0]
        assert hasattr(first, "timestamp")
        assert hasattr(first, "consumption_kw")
        assert hasattr(first, "production_kw")
        assert hasattr(first, "reactive_kw")

    def test_minimal_payload_records(self, minimal_payload):
        p = CezDataParser(minimal_payload)
        records = p.parse_records()
        assert len(records) == 2
        assert records[0].consumption_kw == 1.5
        assert records[1].production_kw == 0.1


# ===========================================================================
# 6. Latest reading extraction
# ===========================================================================


class TestLatestReading:
    """get_latest_reading returns the most recent parsed record."""

    def test_latest_is_last_record(self, parser):
        latest = parser.get_latest_reading()
        assert latest is not None
        assert latest.timestamp == datetime(2026, 2, 15, 0, 0)
        assert latest.consumption_kw == 11.652

    def test_latest_has_all_fields(self, parser):
        latest = parser.get_latest_reading()
        assert latest.consumption_kw is not None
        assert latest.production_kw is not None
        assert latest.reactive_kw is not None

    def test_latest_from_minimal(self, minimal_payload):
        p = CezDataParser(minimal_payload)
        latest = p.get_latest_reading()
        assert latest.timestamp == datetime(2026, 1, 1, 0, 30)
        assert latest.consumption_kw == 2.0
        assert latest.production_kw == 0.1
        assert latest.reactive_kw == 4.0


# ===========================================================================
# 7. Edge cases: missing/partial data
# ===========================================================================


class TestEdgeCases:
    """Parser must not crash on partial or missing data."""

    def test_empty_values_list(self):
        payload = {
            "hasData": False,
            "size": 0,
            "columns": [
                {"id": "1000", "name": "Datum", "unit": None},
                {"id": "1001", "name": "+A/123", "unit": "kW"},
            ],
            "values": [],
            "statuses": {},
        }
        p = CezDataParser(payload)
        records = p.parse_records()
        assert records == []

    def test_latest_reading_empty_returns_none(self):
        payload = {
            "hasData": False,
            "size": 0,
            "columns": [
                {"id": "1000", "name": "Datum", "unit": None},
            ],
            "values": [],
            "statuses": {},
        }
        p = CezDataParser(payload)
        assert p.get_latest_reading() is None

    def test_missing_value_key_in_record(self, minimal_payload):
        """A record missing a metric column should use None for that value."""
        payload = copy.deepcopy(minimal_payload)
        del payload["values"][0]["1003"]  # Remove Rv column value
        p = CezDataParser(payload)
        records = p.parse_records()
        assert records[0].reactive_kw is None
        # Second record should still be fine
        assert records[1].reactive_kw == 4.0

    def test_missing_v_key_in_cell(self, minimal_payload):
        """A cell without 'v' key should yield None."""
        payload = copy.deepcopy(minimal_payload)
        payload["values"][0]["1001"] = {"s": 32}  # No 'v' key
        p = CezDataParser(payload)
        records = p.parse_records()
        assert records[0].consumption_kw is None

    def test_has_data_false_still_parses_if_values_present(self):
        """Even if hasData is False, parse whatever values exist."""
        payload = {
            "hasData": False,
            "size": 1,
            "columns": [
                {"id": "1000", "name": "Datum", "unit": None},
                {"id": "1001", "name": "+A/555", "unit": "kW"},
                {"id": "1002", "name": "-A/555", "unit": "kW"},
                {"id": "1003", "name": "Rv/555", "unit": "kW"},
            ],
            "values": [
                {
                    "1000": {"v": "01.01.2026 00:15"},
                    "1001": {"v": "1,0", "s": 32},
                    "1002": {"v": "0,0", "s": 32},
                    "1003": {"v": "2,0", "s": 32},
                },
            ],
            "statuses": {},
        }
        p = CezDataParser(payload)
        records = p.parse_records()
        assert len(records) == 1

    def test_no_columns_key(self):
        """Payload without columns key should not crash."""
        p = CezDataParser({"hasData": False})
        records = p.parse_records()
        assert records == []

    def test_no_values_key(self):
        """Payload without values key should not crash."""
        payload = {
            "hasData": True,
            "columns": [
                {"id": "1000", "name": "Datum", "unit": None},
            ],
        }
        p = CezDataParser(payload)
        records = p.parse_records()
        assert records == []


# ===========================================================================
# 8. Parser output dictionary (for MQTT/sensor integration)
# ===========================================================================


class TestToDict:
    """get_latest_reading_dict returns a flat dict suitable for MQTT publish."""

    def test_dict_keys(self, parser):
        d = parser.get_latest_reading_dict()
        assert "consumption_kw" in d
        assert "production_kw" in d
        assert "reactive_kw" in d
        assert "timestamp" in d
        assert "electrometer_id" in d

    def test_dict_values_match_reading(self, parser):
        d = parser.get_latest_reading_dict()
        assert d["consumption_kw"] == 11.652
        assert d["production_kw"] == 0.0
        assert d["reactive_kw"] == 5.46
        assert d["electrometer_id"] == "784703"

    def test_dict_timestamp_is_iso(self, parser):
        d = parser.get_latest_reading_dict()
        # Should be ISO 8601 string
        ts = d["timestamp"]
        parsed = datetime.fromisoformat(ts)
        assert parsed == datetime(2026, 2, 15, 0, 0)

    def test_dict_returns_none_on_empty(self):
        payload = {"hasData": False, "columns": [], "values": []}
        p = CezDataParser(payload)
        assert p.get_latest_reading_dict() is None
