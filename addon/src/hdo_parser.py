"""HDO (Hromadné Dálkové Ovládání) signal parser.

Parses HDO tariff schedule data from the DIP API into structured
HdoData for downstream MQTT publishing.

Input format (from DIP API):
    {
        "signals": [{
            "signal": "EVV2",
            "den": "Neděle",
            "datum": "15.02.2026",
            "casy": "00:00-08:00;   09:00-12:00;   13:00-15:00;   16:00-19:00;   20:00-24:00"
        }]
    }

Low-tariff windows are the time ranges listed in "casy".
High-tariff is everything outside those windows.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HdoData:
    """Parsed HDO tariff data for a single day."""

    is_low_tariff: bool
    next_switch: datetime
    today_schedule: list[tuple[str, str]]
    signal_name: str


def _parse_time_ranges(casy: str) -> list[tuple[str, str]]:
    """Parse semicolon-separated time ranges into list of (start, end) tuples.

    Example:
        "00:00-08:00;   09:00-12:00" -> [("00:00", "08:00"), ("09:00", "12:00")]
    """
    ranges: list[tuple[str, str]] = []
    for part in casy.split(";"):
        part = part.strip()
        if not part:
            continue
        if "-" not in part:
            logger.warning("Skipping malformed time range: %s", part)
            continue
        start, end = part.split("-", 1)
        ranges.append((start.strip(), end.strip()))
    return ranges


def _time_from_str(s: str) -> time:
    """Parse HH:MM string to time object. Handles '24:00' as midnight."""
    if s == "24:00":
        return time(0, 0)
    return datetime.strptime(s, "%H:%M").time()


def _is_in_low_tariff(now_time: time, ranges: list[tuple[str, str]]) -> bool:
    """Check if current time falls within any low-tariff window."""
    for start_s, end_s in ranges:
        start = _time_from_str(start_s)
        end = _time_from_str(end_s)

        if end == time(0, 0) and start != time(0, 0):
            # Range like "20:00-24:00" means 20:00 to midnight
            if now_time >= start:
                return True
        elif start <= now_time < end:
            return True
    return False


def _find_next_switch(now: datetime, ranges: list[tuple[str, str]]) -> datetime:
    """Find the next tariff switch time (low→high or high→low).

    Searches today's schedule first, then wraps to next day.
    """
    now_time = now.time()
    today = now.date()

    # Collect all boundary times for today
    boundaries: list[time] = []
    for start_s, end_s in ranges:
        start = _time_from_str(start_s)
        end = _time_from_str(end_s)
        boundaries.append(start)
        if end != time(0, 0):
            boundaries.append(end)
        else:
            # 24:00 → midnight of next day; skip as boundary for today
            pass

    boundaries.sort()

    # Find the next boundary after now
    for b in boundaries:
        if b > now_time:
            return datetime.combine(today, b)

    # No more boundaries today → first boundary tomorrow
    if boundaries:
        return datetime.combine(today + timedelta(days=1), boundaries[0])

    # No boundaries at all (shouldn't happen with valid data)
    return datetime.combine(today + timedelta(days=1), time(0, 0))


def parse_hdo_signals(
    signals_data: dict[str, Any],
    *,
    now: datetime | None = None,
) -> HdoData:
    """Parse DIP API signals response into HdoData.

    Args:
        signals_data: The "data" portion of DIP API response, containing
            {"signals": [{"signal": ..., "casy": ..., ...}]}
        now: Override current time for testing. Defaults to datetime.now().

    Returns:
        HdoData with parsed tariff information.

    Raises:
        ValueError: If signals_data is missing required fields.
    """
    if now is None:
        now = datetime.now()

    signals = signals_data.get("signals")
    if not signals:
        raise ValueError("No signals found in data")

    # Use first signal entry
    signal = signals[0]

    signal_name = signal.get("signal", "")
    casy = signal.get("casy", "")

    if not casy:
        raise ValueError("No time schedule (casy) found in signal data")

    # Parse time ranges
    schedule = _parse_time_ranges(casy)

    # Determine current tariff
    is_low = _is_in_low_tariff(now.time(), schedule)

    # Calculate next switch
    next_switch = _find_next_switch(now, schedule)

    return HdoData(
        is_low_tariff=is_low,
        next_switch=next_switch,
        today_schedule=schedule,
        signal_name=signal_name,
    )
