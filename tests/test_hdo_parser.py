"""Tests for HDO signal parser.

Covers:
- Time range parsing from DIP API format
- Low/high tariff detection at various times
- Next switch time calculation
- Edge cases (midnight wrap, malformed data, empty signals)
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from addon.src.hdo_parser import (
    HdoData,
    _find_next_switch,
    _is_in_low_tariff,
    _parse_time_ranges,
    _time_from_str,
    parse_hdo_signals,
)

# ── Fixtures ──────────────────────────────────────────────────────────

FAKE_HDO_DATA = {
    "signals": [
        {
            "signal": "EVV2",
            "den": "Neděle",
            "datum": "15.02.2026",
            "casy": "00:00-08:00;   09:00-12:00;   13:00-15:00;   16:00-19:00;   20:00-24:00",
        }
    ]
}


FAKE_HDO_DATA_FULL = {
    "data": {
        "signals": [
            {
                "signal": "EVV2",
                "den": "Neděle",
                "datum": "15.02.2026",
                "casy": "00:00-08:00;   09:00-12:00;   13:00-15:00;   16:00-19:00;   20:00-24:00",
            }
        ]
    }
}


@pytest.mark.parametrize("interleaved", [False, True])
def test_multiple_signal_channels_follow_portal_default_without_combining(interleaved):
    primary = [
        {"signal": "TEST|1", "datum": "19.10.2026", "casy": "00:00-08:00;20:00-24:00"},
        {"signal": "TEST|1", "datum": "20.10.2026", "casy": "00:00-06:00"},
    ]
    secondary = [
        {"signal": "TEST|2", "datum": "19.10.2026", "casy": "00:00-24:00"},
        {"signal": "TEST|3", "datum": "19.10.2026", "casy": "12:00-14:00"},
        {"signal": "TEST|2", "datum": "20.10.2026", "casy": "00:00-24:00"},
    ]
    signals = (
        [primary[0], *secondary, primary[1]] if interleaved else primary + secondary
    )
    now = datetime(2026, 10, 19, 12)
    result = parse_hdo_signals({"signals": signals}, now=now)
    assert result == parse_hdo_signals({"signals": primary}, now=now)
    assert result.signal_name == "TEST|1"
    assert result.is_low_tariff is False
    assert result.next_switch == datetime(
        2026, 10, 19, 20, tzinfo=ZoneInfo("Europe/Prague")
    )
    late = parse_hdo_signals({"signals": signals}, now=datetime(2026, 10, 19, 23))
    assert late.next_switch == datetime(
        2026, 10, 20, 6, tzinfo=ZoneInfo("Europe/Prague")
    )


def test_first_signal_is_not_assumed_to_have_a_specific_suffix():
    result = parse_hdo_signals(
        {
            "signals": [
                {"signal": "OTHER", "datum": "19.10.2026", "casy": "00:00-08:00"},
                {"signal": "TEST|1", "datum": "19.10.2026", "casy": "00:00-24:00"},
            ]
        },
        now=datetime(2026, 10, 19, 12),
    )
    assert result.signal_name == "OTHER"
    assert result.is_low_tariff is False


def test_missing_selected_date_does_not_fall_back_to_another_channel():
    result = parse_hdo_signals(
        {
            "signals": [
                {"signal": "TEST|1", "datum": "18.10.2026", "casy": "00:00-24:00"},
                {"signal": "TEST|2", "datum": "19.10.2026", "casy": "00:00-24:00"},
            ]
        },
        now=datetime(2026, 10, 19, 12),
    )
    assert result.is_low_tariff is None
    assert result.next_switch is None


def test_identical_duplicate_selected_schedule_is_accepted():
    entry = {"signal": "TEST", "datum": "19.10.2026", "casy": "00:00-08:00"}
    now = datetime(2026, 10, 19, 7)
    assert parse_hdo_signals(
        {"signals": [entry, dict(entry)]}, now=now
    ) == parse_hdo_signals({"signals": [entry]}, now=now)


def test_conflicting_duplicate_selected_schedule_is_rejected():
    entry = {"signal": "TEST", "datum": "19.10.2026", "casy": "00:00-08:00"}
    with pytest.raises(ValueError, match="Ambiguous"):
        parse_hdo_signals(
            {"signals": [entry, dict(entry, casy="00:00-24:00")]},
            now=datetime(2026, 10, 19, 12),
        )


# ── Time range parsing ────────────────────────────────────────────────


class TestParseTimeRanges:
    """Verify semicolon-separated time range parsing."""

    def test_parses_five_ranges(self) -> None:
        casy = "00:00-08:00;   09:00-12:00;   13:00-15:00;   16:00-19:00;   20:00-24:00"
        result = _parse_time_ranges(casy)
        assert len(result) == 5
        assert result == [
            ("00:00", "08:00"),
            ("09:00", "12:00"),
            ("13:00", "15:00"),
            ("16:00", "19:00"),
            ("20:00", "24:00"),
        ]

    def test_parses_single_range(self) -> None:
        result = _parse_time_ranges("06:00-22:00")
        assert result == [("06:00", "22:00")]

    def test_handles_extra_whitespace(self) -> None:
        result = _parse_time_ranges("  06:00 - 22:00 ;  23:00 - 24:00  ")
        assert result == [("06:00", "22:00"), ("23:00", "24:00")]

    def test_empty_string_returns_empty_list(self) -> None:
        result = _parse_time_ranges("")
        assert result == []

    def test_rejects_malformed_entries(self) -> None:
        with pytest.raises(ValueError):
            _parse_time_ranges("06:00-22:00;INVALID;23:00-24:00")


# ── Time string parsing ──────────────────────────────────────────────


class TestTimeFromStr:
    """Verify time string to time object conversion."""

    def test_normal_time(self) -> None:
        assert _time_from_str("08:00") == time(8, 0)

    def test_midnight_24(self) -> None:
        assert _time_from_str("24:00") == time(0, 0)

    def test_midnight_00(self) -> None:
        assert _time_from_str("00:00") == time(0, 0)

    def test_noon(self) -> None:
        assert _time_from_str("12:00") == time(12, 0)

    def test_with_minutes(self) -> None:
        assert _time_from_str("13:30") == time(13, 30)


# ── Low tariff detection ─────────────────────────────────────────────


class TestIsInLowTariff:
    """Verify tariff detection at various times."""

    SCHEDULE = [
        ("00:00", "08:00"),
        ("09:00", "12:00"),
        ("13:00", "15:00"),
        ("16:00", "19:00"),
        ("20:00", "24:00"),
    ]

    def test_midnight_is_low_tariff(self) -> None:
        assert _is_in_low_tariff(time(0, 0), self.SCHEDULE) is True

    def test_early_morning_is_low_tariff(self) -> None:
        assert _is_in_low_tariff(time(3, 0), self.SCHEDULE) is True

    def test_0759_is_low_tariff(self) -> None:
        assert _is_in_low_tariff(time(7, 59), self.SCHEDULE) is True

    def test_0800_is_high_tariff(self) -> None:
        """08:00 is the end of the low tariff range → high tariff."""
        assert _is_in_low_tariff(time(8, 0), self.SCHEDULE) is False

    def test_0830_is_high_tariff(self) -> None:
        assert _is_in_low_tariff(time(8, 30), self.SCHEDULE) is False

    def test_0900_is_low_tariff(self) -> None:
        assert _is_in_low_tariff(time(9, 0), self.SCHEDULE) is True

    def test_1200_is_high_tariff(self) -> None:
        assert _is_in_low_tariff(time(12, 0), self.SCHEDULE) is False

    def test_1500_is_high_tariff(self) -> None:
        assert _is_in_low_tariff(time(15, 0), self.SCHEDULE) is False

    def test_1530_is_high_tariff(self) -> None:
        assert _is_in_low_tariff(time(15, 30), self.SCHEDULE) is False

    def test_1600_is_low_tariff(self) -> None:
        assert _is_in_low_tariff(time(16, 0), self.SCHEDULE) is True

    def test_2000_is_low_tariff(self) -> None:
        assert _is_in_low_tariff(time(20, 0), self.SCHEDULE) is True

    def test_2359_is_low_tariff(self) -> None:
        """23:59 is within 20:00-24:00 window."""
        assert _is_in_low_tariff(time(23, 59), self.SCHEDULE) is True


# ── Next switch calculation ───────────────────────────────────────────


class TestFindNextSwitch:
    """Verify next tariff switch time calculation."""

    SCHEDULE = [
        ("00:00", "08:00"),
        ("09:00", "12:00"),
        ("13:00", "15:00"),
        ("16:00", "19:00"),
        ("20:00", "24:00"),
    ]

    def test_at_0300_next_switch_is_0800(self) -> None:
        now = datetime(2026, 2, 15, 3, 0, tzinfo=ZoneInfo("Europe/Prague"))
        result = _find_next_switch(now, self.SCHEDULE)
        assert result == datetime(2026, 2, 15, 8, 0, tzinfo=ZoneInfo("Europe/Prague"))

    def test_at_0830_next_switch_is_0900(self) -> None:
        now = datetime(2026, 2, 15, 8, 30, tzinfo=ZoneInfo("Europe/Prague"))
        result = _find_next_switch(now, self.SCHEDULE)
        assert result == datetime(2026, 2, 15, 9, 0, tzinfo=ZoneInfo("Europe/Prague"))

    def test_at_1230_next_switch_is_1300(self) -> None:
        now = datetime(2026, 2, 15, 12, 30, tzinfo=ZoneInfo("Europe/Prague"))
        result = _find_next_switch(now, self.SCHEDULE)
        assert result == datetime(2026, 2, 15, 13, 0, tzinfo=ZoneInfo("Europe/Prague"))

    def test_at_1930_next_switch_is_2000(self) -> None:
        now = datetime(2026, 2, 15, 19, 30, tzinfo=ZoneInfo("Europe/Prague"))
        result = _find_next_switch(now, self.SCHEDULE)
        assert result == datetime(2026, 2, 15, 20, 0, tzinfo=ZoneInfo("Europe/Prague"))

    def test_at_2200_does_not_invent_tomorrow(self) -> None:
        """After last boundary (20:00), next is 00:00 tomorrow (first boundary)."""
        now = datetime(2026, 2, 15, 22, 0, tzinfo=ZoneInfo("Europe/Prague"))
        result = _find_next_switch(now, self.SCHEDULE)
        assert result is None

    def test_at_0000_next_switch_is_0800(self) -> None:
        """At exact midnight, next boundary after 00:00 is 08:00."""
        now = datetime(2026, 2, 15, 0, 0, tzinfo=ZoneInfo("Europe/Prague"))
        result = _find_next_switch(now, self.SCHEDULE)
        assert result == datetime(2026, 2, 15, 8, 0, tzinfo=ZoneInfo("Europe/Prague"))

    def test_empty_schedule_has_no_known_switch(self) -> None:
        """When schedule is empty (no valid slots), return next day at midnight."""
        now = datetime(2026, 2, 15, 10, 0, tzinfo=ZoneInfo("Europe/Prague"))
        result = _find_next_switch(now, [])
        assert result is None


# ── Full parse_hdo_signals ────────────────────────────────────────────


class TestParseHdoSignals:
    """Verify end-to-end HDO signal parsing."""

    def test_returns_hdo_data_instance(self) -> None:
        now = datetime(2026, 2, 15, 10, 0, tzinfo=ZoneInfo("Europe/Prague"))
        result = parse_hdo_signals(FAKE_HDO_DATA, now=now)
        assert isinstance(result, HdoData)

    def test_signal_name_extracted(self) -> None:
        now = datetime(2026, 2, 15, 10, 0, tzinfo=ZoneInfo("Europe/Prague"))
        result = parse_hdo_signals(FAKE_HDO_DATA, now=now)
        assert result.signal_name == "EVV2"

    def test_schedule_parsed_correctly(self) -> None:
        now = datetime(2026, 2, 15, 10, 0, tzinfo=ZoneInfo("Europe/Prague"))
        result = parse_hdo_signals(FAKE_HDO_DATA, now=now)
        assert result.today_schedule == [
            ("00:00", "08:00"),
            ("09:00", "12:00"),
            ("13:00", "15:00"),
            ("16:00", "19:00"),
            ("20:00", "24:00"),
        ]

    def test_low_tariff_during_window(self) -> None:
        """10:00 is within 09:00-12:00 → low tariff."""
        now = datetime(2026, 2, 15, 10, 0, tzinfo=ZoneInfo("Europe/Prague"))
        result = parse_hdo_signals(FAKE_HDO_DATA, now=now)
        assert result.is_low_tariff is True

    def test_high_tariff_outside_window(self) -> None:
        """08:30 is between 08:00 and 09:00 → high tariff."""
        now = datetime(2026, 2, 15, 8, 30, tzinfo=ZoneInfo("Europe/Prague"))
        result = parse_hdo_signals(FAKE_HDO_DATA, now=now)
        assert result.is_low_tariff is False

    def test_next_switch_calculated(self) -> None:
        now = datetime(2026, 2, 15, 10, 0, tzinfo=ZoneInfo("Europe/Prague"))
        result = parse_hdo_signals(FAKE_HDO_DATA, now=now)
        assert result.next_switch == datetime(
            2026, 2, 15, 12, 0, tzinfo=ZoneInfo("Europe/Prague")
        )

    def test_next_switch_during_high_tariff(self) -> None:
        now = datetime(2026, 2, 15, 8, 30, tzinfo=ZoneInfo("Europe/Prague"))
        result = parse_hdo_signals(FAKE_HDO_DATA, now=now)
        assert result.next_switch == datetime(
            2026, 2, 15, 9, 0, tzinfo=ZoneInfo("Europe/Prague")
        )

    def test_is_low_tariff_is_bool(self) -> None:
        now = datetime(2026, 2, 15, 10, 0, tzinfo=ZoneInfo("Europe/Prague"))
        result = parse_hdo_signals(FAKE_HDO_DATA, now=now)
        assert isinstance(result.is_low_tariff, bool)

    def test_next_switch_is_datetime(self) -> None:
        now = datetime(2026, 2, 15, 10, 0, tzinfo=ZoneInfo("Europe/Prague"))
        result = parse_hdo_signals(FAKE_HDO_DATA, now=now)
        assert isinstance(result.next_switch, datetime)

    def test_raises_on_empty_signals(self) -> None:
        with pytest.raises(ValueError, match="No signals found"):
            parse_hdo_signals({"signals": []})

    def test_raises_on_missing_signals(self) -> None:
        with pytest.raises(ValueError, match="No signals found"):
            parse_hdo_signals({})

    def test_raises_on_empty_casy(self) -> None:
        data = {"signals": [{"signal": "EVV2", "casy": ""}]}
        result = parse_hdo_signals(data)
        assert result.is_low_tariff is None
        assert result.next_switch is None

    def test_works_with_nested_data_structure(self) -> None:
        """parse_hdo_signals takes the 'data' portion, not the full response."""
        now = datetime(2026, 2, 15, 10, 0, tzinfo=ZoneInfo("Europe/Prague"))
        result = parse_hdo_signals(FAKE_HDO_DATA_FULL["data"], now=now)
        assert result.signal_name == "EVV2"
        assert result.is_low_tariff is True


# ── Frozen dataclass ──────────────────────────────────────────────────


class TestHdoDataImmutability:
    """Verify HdoData is frozen/immutable."""

    def test_cannot_modify_fields(self) -> None:
        data = HdoData(
            is_low_tariff=True,
            next_switch=datetime(2026, 2, 15, 12, 0, tzinfo=ZoneInfo("Europe/Prague")),
            today_schedule=[("00:00", "08:00")],
            signal_name="EVV2",
        )
        with pytest.raises(AttributeError):
            data.is_low_tariff = False  # type: ignore[misc]
