"""HDO (Hromadné Dálkové Ovládání) signal parser.

Parses HDO tariff schedule data from the DIP API into structured
HdoData for downstream MQTT publishing.

Input format (the "data" portion of the DIP API response):
    {
        "signals": [{
            "signal": "EVV2",
            "den": "Neděle",
            "datum": "15.02.2026",
            "casy": "00:00-08:00;   09:00-12:00;   13:00-15:00;   16:00-19:00;   20:00-24:00"
        }]
    }

The response may contain multiple dated entries. "datum" selects the schedule
for a date in Europe/Prague; "den" is the display name of the weekday.
Entries are grouped by "signal". As in the DIP frontend, the first signal
in response order is selected; other channels are never combined with it.
Low-tariff windows are the time ranges listed in "casy". High tariff is
everything outside those windows on a day with a known schedule.
"24:00" denotes midnight at the end of that day, including full-day windows.

Missing or unverifiable schedules produce None fields (MQTT unknown states).
The next switch is timezone-aware and uses only available consecutive dates;
today's schedule is never repeated to invent tomorrow's tariff transitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

PRAGUE = ZoneInfo("Europe/Prague")


@dataclass(frozen=True)
class HdoData:
    """Current tariff and dated schedule; None denotes an unknown field."""

    is_low_tariff: bool | None
    next_switch: datetime | None
    today_schedule: list[tuple[str, str]] | None
    signal_name: str | None


UNKNOWN_HDO = HdoData(None, None, None, None)


def _time_from_str(value: str) -> time:
    """Parse HH:MM string to time object. Handles '24:00' as midnight."""
    return time(0) if value == "24:00" else datetime.strptime(value, "%H:%M").time()


def _parse_time_ranges(value: str) -> list[tuple[str, str]]:
    """Parse semicolon-separated time ranges into list of (start, end) tuples.

    Example:
        "00:00-08:00;   09:00-12:00" -> [("00:00", "08:00"), ("09:00", "12:00")]

    Invalid or reversed ranges raise ValueError so partial schedules cannot
    silently produce an incorrect tariff state.
    """
    if not isinstance(value, str):
        raise ValueError("HDO schedule must be a string")
    ranges = []
    for part in value.split(";"):
        if not part.strip():
            continue
        start, end = (x.strip() for x in part.strip().split("-", 1))
        start_time, end_time = _time_from_str(start), _time_from_str(end)
        if start == "24:00" or (end != "24:00" and end_time <= start_time):
            raise ValueError("Invalid HDO time range")
        ranges.append(
            (
                start_time.strftime("%H:%M"),
                "24:00" if end == "24:00" else end_time.strftime("%H:%M"),
            )
        )
    return ranges


def _is_in_low_tariff(now_time: time, ranges: list[tuple[str, str]]) -> bool:
    """Check if current time falls within any low-tariff window."""
    return any(
        _time_from_str(start) <= now_time
        and (end == "24:00" or now_time < _time_from_str(end))
        for start, end in ranges
    )


def _intervals(day, ranges):
    result = []
    for start, end in ranges:
        begin = datetime.combine(day, _time_from_str(start), PRAGUE)
        finish = datetime.combine(
            day + timedelta(days=1) if end == "24:00" else day,
            _time_from_str(end),
            PRAGUE,
        )
        result.append((begin.astimezone(timezone.utc), finish.astimezone(timezone.utc)))
    merged = []
    for begin, finish in sorted(result):
        if merged and begin <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(finish, merged[-1][1]))
        else:
            merged.append((begin, finish))
    return merged


def _find_next_switch(now: datetime, ranges: list[tuple[str, str]]) -> datetime | None:
    """Find the next tariff switch time (low→high or high→low) today.

    Return None when no further transition is supported by today's schedule;
    tomorrow's schedule cannot be inferred from today's windows.
    """
    local = now.replace(tzinfo=PRAGUE) if now.tzinfo is None else now.astimezone(PRAGUE)
    instant = local.astimezone(timezone.utc)
    midnight = datetime.combine(local.date() + timedelta(days=1), time(0), PRAGUE)
    candidates = sorted({b for pair in _intervals(local.date(), ranges) for b in pair})
    for boundary in candidates:
        if instant < boundary < midnight.astimezone(timezone.utc):
            return boundary.astimezone(PRAGUE)
    return None


def parse_hdo_signals(
    signals_data: dict[str, Any], *, now: datetime | None = None
) -> HdoData:
    """Parse DIP response data, selecting today's schedule by its Czech date.

    ``signals_data`` is the response's "data" object, not the outer envelope.
    ``now`` defaults to the current Prague time; a naive override is interpreted
    as Prague local time. Missing dates yield unknown values, while absent
    signals or conflicting schedules for the selected signal raise ValueError.

    Args:
        signals_data: The "data" portion of the DIP API response, containing
            {"signals": [{"signal": ..., "datum": ..., "casy": ..., ...}]}.
        now: Override current time for testing. Defaults to current Prague time.

    Returns:
        HdoData with the current tariff, schedule, and next known transition.

    Raises:
        ValueError: If signals are absent or dated schedules are ambiguous.
    """
    signals = signals_data.get("signals")
    if not signals:
        raise ValueError("No signals found in data")
    now = now or datetime.now(PRAGUE)
    local = now.replace(tzinfo=PRAGUE) if now.tzinfo is None else now.astimezone(PRAGUE)
    today = local.date()
    # Match DIP's getMappedSignals/initSignals default selection. Multiple
    # channels can have different windows for the same date.
    selected_signal = signals[0].get("signal")
    dated: dict[date, dict[str, Any]] = {}
    for signal in signals:
        if signal.get("signal") != selected_signal:
            continue
        try:
            day = datetime.strptime(signal.get("datum", ""), "%d.%m.%Y").date()
        except (TypeError, ValueError):
            continue
        if day in dated:
            if dated[day].get("casy") != signal.get("casy"):
                raise ValueError("Ambiguous HDO schedule for one date")
            continue
        dated[day] = signal
    if today not in dated:
        return UNKNOWN_HDO
    signal = dated[today]
    name = signal.get("signal") or None
    try:
        schedule = _parse_time_ranges(signal["casy"])
        if not schedule:
            return HdoData(None, None, None, name)
    except (KeyError, TypeError, ValueError):
        return HdoData(None, None, None, name)
    instant = local.astimezone(timezone.utc)
    all_intervals = []
    day = today
    while day in dated:
        try:
            ranges = _parse_time_ranges(dated[day]["casy"])
            if not ranges:
                break
        except (KeyError, TypeError, ValueError):
            break
        all_intervals.extend(_intervals(day, ranges))
        day += timedelta(days=1)
    # The end of the last known day cannot establish tomorrow's tariff.
    horizon = datetime.combine(day, time(0), PRAGUE).astimezone(timezone.utc)

    def low(at):
        return any(start <= at < end for start, end in all_intervals)

    next_switch = None
    boundaries = sorted({b for pair in all_intervals for b in pair})
    for boundary in boundaries:
        if instant < boundary < horizon and low(
            boundary - timedelta(microseconds=1)
        ) != low(boundary):
            next_switch = boundary.astimezone(PRAGUE)
            break
    return HdoData(low(instant), next_switch, schedule, name)
