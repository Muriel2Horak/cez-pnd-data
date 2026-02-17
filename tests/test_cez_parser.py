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
from addon.src.parser import (CezDataParser, ParsedReading,
                              detect_electrometer_id, parse_czech_decimal,
                              parse_czech_timestamp)

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


# ===========================================================================
# 9. Multi-assembly fixtures (Tab 03, 04, 07, 08, 17)
# ===========================================================================


@pytest.fixture
def tab03_payload() -> dict:
    """Tab 03: Reactive consumption — Profil +A, Profil +Ri, Profil -Rc."""
    return {
        "hasData": True,
        "size": 2,
        "columns": [
            {"id": "1000", "name": "Datum", "unit": None},
            {"id": "1001", "name": "Profil +A", "unit": "kW"},
            {"id": "1002", "name": "Profil +Ri", "unit": "kW"},
            {"id": "1003", "name": "Profil -Rc", "unit": "kW"},
        ],
        "values": [
            {
                "1000": {"v": "01.01.2026 00:15"},
                "1001": {"v": "1,5", "s": 32},
                "1002": {"v": "0,8", "s": 32},
                "1003": {"v": "0,3", "s": 32},
            },
            {
                "1000": {"v": "01.01.2026 00:30"},
                "1001": {"v": "2,0", "s": 32},
                "1002": {"v": "1,1", "s": 32},
                "1003": {"v": "0,5", "s": 32},
            },
        ],
        "statuses": {"32": {"n": "naměřená data OK", "c": "#222222", "m": 32}},
    }


@pytest.fixture
def tab04_payload() -> dict:
    """Tab 04: Reactive production — Profil -A, Profil -Ri, Profil +Rc."""
    return {
        "hasData": True,
        "size": 2,
        "columns": [
            {"id": "1000", "name": "Datum", "unit": None},
            {"id": "1001", "name": "Profil -A", "unit": "kW"},
            {"id": "1002", "name": "Profil -Ri", "unit": "kW"},
            {"id": "1003", "name": "Profil +Rc", "unit": "kW"},
        ],
        "values": [
            {
                "1000": {"v": "01.01.2026 00:15"},
                "1001": {"v": "0,2", "s": 32},
                "1002": {"v": "0,05", "s": 32},
                "1003": {"v": "0,1", "s": 32},
            },
            {
                "1000": {"v": "01.01.2026 00:30"},
                "1001": {"v": "0,4", "s": 32},
                "1002": {"v": "0,07", "s": 32},
                "1003": {"v": "0,15", "s": 32},
            },
        ],
        "statuses": {"32": {"n": "naměřená data OK", "c": "#222222", "m": 32}},
    }


@pytest.fixture
def tab07_payload() -> dict:
    """Tab 07: Daily consumption — +A d/784703."""
    return {
        "hasData": True,
        "size": 2,
        "columns": [
            {"id": "1000", "name": "Datum", "unit": None},
            {"id": "1001", "name": "+A d/784703", "unit": "kWh"},
        ],
        "values": [
            {
                "1000": {"v": "01.01.2026 00:15"},
                "1001": {"v": "12,5", "s": 32},
            },
            {
                "1000": {"v": "01.01.2026 00:30"},
                "1001": {"v": "13,2", "s": 32},
            },
        ],
        "statuses": {"32": {"n": "naměřená data OK", "c": "#222222", "m": 32}},
    }


@pytest.fixture
def tab08_payload() -> dict:
    """Tab 08: Daily production — -A d/784703."""
    return {
        "hasData": True,
        "size": 2,
        "columns": [
            {"id": "1000", "name": "Datum", "unit": None},
            {"id": "1001", "name": "-A d/784703", "unit": "kWh"},
        ],
        "values": [
            {
                "1000": {"v": "01.01.2026 00:15"},
                "1001": {"v": "5,3", "s": 32},
            },
            {
                "1000": {"v": "01.01.2026 00:30"},
                "1001": {"v": "6,1", "s": 32},
            },
        ],
        "statuses": {"32": {"n": "naměřená data OK", "c": "#222222", "m": 32}},
    }


@pytest.fixture
def tab17_payload() -> dict:
    """Tab 17: Register readings — +E, -E, +E_NT, +E_VT."""
    return {
        "hasData": True,
        "size": 2,
        "columns": [
            {"id": "1000", "name": "Datum", "unit": None},
            {"id": "1001", "name": "+E/784703", "unit": "kWh"},
            {"id": "1002", "name": "-E/784703", "unit": "kWh"},
            {"id": "1003", "name": "+E_NT/784703", "unit": "kWh"},
            {"id": "1004", "name": "+E_VT/784703", "unit": "kWh"},
        ],
        "values": [
            {
                "1000": {"v": "01.01.2026 00:15"},
                "1001": {"v": "1000,5", "s": 32},
                "1002": {"v": "200,3", "s": 32},
                "1003": {"v": "600,2", "s": 32},
                "1004": {"v": "400,3", "s": 32},
            },
            {
                "1000": {"v": "01.01.2026 00:30"},
                "1001": {"v": "1001,0", "s": 32},
                "1002": {"v": "200,5", "s": 32},
                "1003": {"v": "600,5", "s": 32},
                "1004": {"v": "400,5", "s": 32},
            },
        ],
        "statuses": {"32": {"n": "naměřená data OK", "c": "#222222", "m": 32}},
    }


# ===========================================================================
# 10. Tab 03 — Reactive consumption (Profil +A, +Ri, -Rc)
# ===========================================================================


class TestTab03ReactiveConsumption:
    """Tab 03 columns: Profil +A → consumption, Profil +Ri → reactive_import_inductive,
    Profil -Rc → reactive_export_capacitive."""

    def test_discovers_consumption_from_profil_plus_a(self, tab03_payload):
        p = CezDataParser(tab03_payload)
        assert p.consumption_col_id == "1001"

    def test_discovers_reactive_import_inductive(self, tab03_payload):
        p = CezDataParser(tab03_payload)
        assert p.reactive_import_inductive_col_id == "1002"

    def test_discovers_reactive_export_capacitive(self, tab03_payload):
        p = CezDataParser(tab03_payload)
        assert p.reactive_export_capacitive_col_id == "1003"

    def test_parses_reactive_import_inductive_value(self, tab03_payload):
        p = CezDataParser(tab03_payload)
        records = p.parse_records()
        assert len(records) == 2
        assert records[0].reactive_import_inductive_kw == 0.8
        assert records[1].reactive_import_inductive_kw == 1.1

    def test_parses_reactive_export_capacitive_value(self, tab03_payload):
        p = CezDataParser(tab03_payload)
        records = p.parse_records()
        assert records[0].reactive_export_capacitive_kw == 0.3
        assert records[1].reactive_export_capacitive_kw == 0.5

    def test_consumption_from_profil_plus_a(self, tab03_payload):
        p = CezDataParser(tab03_payload)
        records = p.parse_records()
        assert records[0].consumption_kw == 1.5

    def test_dict_includes_reactive_fields(self, tab03_payload):
        p = CezDataParser(tab03_payload)
        d = p.get_latest_reading_dict()
        assert d is not None
        assert d["reactive_import_inductive_kw"] == 1.1
        assert d["reactive_export_capacitive_kw"] == 0.5

    def test_no_meter_id_from_profil_columns(self, tab03_payload):
        """Profil columns have no meter ID embedded — electrometer_id should be None."""
        p = CezDataParser(tab03_payload)
        assert p.electrometer_id is None


# ===========================================================================
# 11. Tab 04 — Reactive production (Profil -A, -Ri, +Rc)
# ===========================================================================


class TestTab04ReactiveProduction:
    """Tab 04 columns: Profil -A → production, Profil -Ri → reactive_export_inductive,
    Profil +Rc → reactive_import_capacitive."""

    def test_discovers_production_from_profil_minus_a(self, tab04_payload):
        p = CezDataParser(tab04_payload)
        assert p.production_col_id == "1001"

    def test_discovers_reactive_export_inductive(self, tab04_payload):
        p = CezDataParser(tab04_payload)
        assert p.reactive_export_inductive_col_id == "1002"

    def test_discovers_reactive_import_capacitive(self, tab04_payload):
        p = CezDataParser(tab04_payload)
        assert p.reactive_import_capacitive_col_id == "1003"

    def test_parses_reactive_export_inductive_value(self, tab04_payload):
        p = CezDataParser(tab04_payload)
        records = p.parse_records()
        assert records[0].reactive_export_inductive_kw == 0.05
        assert records[1].reactive_export_inductive_kw == 0.07

    def test_parses_reactive_import_capacitive_value(self, tab04_payload):
        p = CezDataParser(tab04_payload)
        records = p.parse_records()
        assert records[0].reactive_import_capacitive_kw == 0.1
        assert records[1].reactive_import_capacitive_kw == 0.15

    def test_production_from_profil_minus_a(self, tab04_payload):
        p = CezDataParser(tab04_payload)
        records = p.parse_records()
        assert records[0].production_kw == 0.2

    def test_dict_includes_reactive_fields(self, tab04_payload):
        p = CezDataParser(tab04_payload)
        d = p.get_latest_reading_dict()
        assert d is not None
        assert d["reactive_export_inductive_kw"] == 0.07
        assert d["reactive_import_capacitive_kw"] == 0.15


# ===========================================================================
# 12. Tab 07 — Daily consumption (+A d/NNNN)
# ===========================================================================


class TestTab07DailyConsumption:
    """Tab 07 column: +A d/784703 → daily_consumption."""

    def test_discovers_daily_consumption(self, tab07_payload):
        p = CezDataParser(tab07_payload)
        assert p.daily_consumption_col_id == "1001"

    def test_parses_daily_consumption_value(self, tab07_payload):
        p = CezDataParser(tab07_payload)
        records = p.parse_records()
        assert len(records) == 2
        assert records[0].daily_consumption_kwh == 12.5
        assert records[1].daily_consumption_kwh == 13.2

    def test_extracts_meter_id_from_daily_column(self, tab07_payload):
        p = CezDataParser(tab07_payload)
        assert p.electrometer_id == "784703"

    def test_dict_includes_daily_consumption(self, tab07_payload):
        p = CezDataParser(tab07_payload)
        d = p.get_latest_reading_dict()
        assert d is not None
        assert d["daily_consumption_kwh"] == 13.2
        assert d["electrometer_id"] == "784703"


# ===========================================================================
# 13. Tab 08 — Daily production (-A d/NNNN)
# ===========================================================================


class TestTab08DailyProduction:
    """Tab 08 column: -A d/784703 → daily_production."""

    def test_discovers_daily_production(self, tab08_payload):
        p = CezDataParser(tab08_payload)
        assert p.daily_production_col_id == "1001"

    def test_parses_daily_production_value(self, tab08_payload):
        p = CezDataParser(tab08_payload)
        records = p.parse_records()
        assert len(records) == 2
        assert records[0].daily_production_kwh == 5.3
        assert records[1].daily_production_kwh == 6.1

    def test_extracts_meter_id_from_daily_column(self, tab08_payload):
        p = CezDataParser(tab08_payload)
        assert p.electrometer_id == "784703"

    def test_dict_includes_daily_production(self, tab08_payload):
        p = CezDataParser(tab08_payload)
        d = p.get_latest_reading_dict()
        assert d is not None
        assert d["daily_production_kwh"] == 6.1


# ===========================================================================
# 14. Tab 17 — Register readings (+E, -E, +E_NT, +E_VT)
# ===========================================================================


class TestTab17RegisterReadings:
    """Tab 17 columns: +E → register_consumption, -E → register_production,
    +E_NT → register_low_tariff, +E_VT → register_high_tariff."""

    def test_discovers_register_consumption(self, tab17_payload):
        p = CezDataParser(tab17_payload)
        assert p.register_consumption_col_id == "1001"

    def test_discovers_register_production(self, tab17_payload):
        p = CezDataParser(tab17_payload)
        assert p.register_production_col_id == "1002"

    def test_discovers_register_low_tariff(self, tab17_payload):
        p = CezDataParser(tab17_payload)
        assert p.register_low_tariff_col_id == "1003"

    def test_discovers_register_high_tariff(self, tab17_payload):
        p = CezDataParser(tab17_payload)
        assert p.register_high_tariff_col_id == "1004"

    def test_parses_register_consumption_value(self, tab17_payload):
        p = CezDataParser(tab17_payload)
        records = p.parse_records()
        assert records[0].register_consumption_kwh == 1000.5
        assert records[1].register_consumption_kwh == 1001.0

    def test_parses_register_production_value(self, tab17_payload):
        p = CezDataParser(tab17_payload)
        records = p.parse_records()
        assert records[0].register_production_kwh == 200.3
        assert records[1].register_production_kwh == 200.5

    def test_parses_register_low_tariff_value(self, tab17_payload):
        p = CezDataParser(tab17_payload)
        records = p.parse_records()
        assert records[0].register_low_tariff_kwh == 600.2
        assert records[1].register_low_tariff_kwh == 600.5

    def test_parses_register_high_tariff_value(self, tab17_payload):
        p = CezDataParser(tab17_payload)
        records = p.parse_records()
        assert records[0].register_high_tariff_kwh == 400.3
        assert records[1].register_high_tariff_kwh == 400.5

    def test_extracts_meter_id_from_register_columns(self, tab17_payload):
        p = CezDataParser(tab17_payload)
        assert p.electrometer_id == "784703"

    def test_dict_includes_register_fields(self, tab17_payload):
        p = CezDataParser(tab17_payload)
        d = p.get_latest_reading_dict()
        assert d is not None
        assert d["register_consumption_kwh"] == 1001.0
        assert d["register_production_kwh"] == 200.5
        assert d["register_low_tariff_kwh"] == 600.5
        assert d["register_high_tariff_kwh"] == 400.5
        assert d["electrometer_id"] == "784703"


# ===========================================================================
# 15. Tab 00 backward compatibility regression
# ===========================================================================


class TestTab00BackwardCompatibility:
    """Existing Tab 00 parsing must remain UNCHANGED after multi-assembly support."""

    def test_tab00_consumption_unchanged(self, minimal_payload):
        p = CezDataParser(minimal_payload)
        records = p.parse_records()
        assert records[0].consumption_kw == 1.5
        assert records[1].consumption_kw == 2.0

    def test_tab00_production_unchanged(self, minimal_payload):
        p = CezDataParser(minimal_payload)
        records = p.parse_records()
        assert records[0].production_kw == 0.0
        assert records[1].production_kw == 0.1

    def test_tab00_reactive_unchanged(self, minimal_payload):
        p = CezDataParser(minimal_payload)
        records = p.parse_records()
        assert records[0].reactive_kw == 3.14
        assert records[1].reactive_kw == 4.0

    def test_tab00_new_fields_are_none(self, minimal_payload):
        """New fields should be None for Tab 00 payloads."""
        p = CezDataParser(minimal_payload)
        records = p.parse_records()
        first = records[0]
        assert first.reactive_import_inductive_kw is None
        assert first.reactive_export_capacitive_kw is None
        assert first.reactive_export_inductive_kw is None
        assert first.reactive_import_capacitive_kw is None
        assert first.daily_consumption_kwh is None
        assert first.daily_production_kwh is None
        assert first.register_consumption_kwh is None
        assert first.register_production_kwh is None
        assert first.register_low_tariff_kwh is None
        assert first.register_high_tariff_kwh is None

    def test_tab00_dict_includes_new_fields_as_none(self, minimal_payload):
        """Dict output should include all new fields even for Tab 00 (as None)."""
        p = CezDataParser(minimal_payload)
        d = p.get_latest_reading_dict()
        assert d is not None
        assert d["reactive_import_inductive_kw"] is None
        assert d["reactive_export_capacitive_kw"] is None
        assert d["reactive_export_inductive_kw"] is None
        assert d["reactive_import_capacitive_kw"] is None
        assert d["daily_consumption_kwh"] is None
        assert d["daily_production_kwh"] is None
        assert d["register_consumption_kwh"] is None
        assert d["register_production_kwh"] is None
        assert d["register_low_tariff_kwh"] is None
        assert d["register_high_tariff_kwh"] is None

    def test_tab00_electrometer_id_unchanged(self, minimal_payload):
        p = CezDataParser(minimal_payload)
        assert p.electrometer_id == "999999"

    def test_tab00_column_discovery_unchanged(self, minimal_payload):
        p = CezDataParser(minimal_payload)
        assert p.timestamp_col_id == "1000"
        assert p.consumption_col_id == "1001"
        assert p.production_col_id == "1002"
        assert p.reactive_col_id == "1003"

    def test_tab00_latest_reading_dict_keys_superset(self, minimal_payload):
        """Dict must still have original keys: consumption_kw, production_kw, reactive_kw, timestamp, electrometer_id."""
        p = CezDataParser(minimal_payload)
        d = p.get_latest_reading_dict()
        assert "consumption_kw" in d
        assert "production_kw" in d
        assert "reactive_kw" in d
        assert "timestamp" in d
        assert "electrometer_id" in d


# ===========================================================================
# 16. Cross-tab: detect_electrometer_id with new column patterns
# ===========================================================================


class TestDetectElectrometerIdMultiAssembly:
    """detect_electrometer_id should work with Tab 07/08/17 column patterns."""

    def test_detects_from_daily_consumption_column(self, tab07_payload):
        meter_id = detect_electrometer_id(tab07_payload)
        assert meter_id == "784703"

    def test_detects_from_daily_production_column(self, tab08_payload):
        meter_id = detect_electrometer_id(tab08_payload)
        assert meter_id == "784703"

    def test_detects_from_register_column(self, tab17_payload):
        meter_id = detect_electrometer_id(tab17_payload)
        assert meter_id == "784703"

    def test_no_id_from_profil_columns(self, tab03_payload):
        """Profil columns don't contain meter ID."""
        meter_id = detect_electrometer_id(tab03_payload)
        assert meter_id is None

    def test_no_id_from_profil_columns_with_fallback(self, tab03_payload):
        meter_id = detect_electrometer_id(tab03_payload, fallback_id="MANUAL")
        assert meter_id == "MANUAL"
