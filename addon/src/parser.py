"""CEZ PND data payload parser.

Parses the JSON response from the CEZ PND data endpoint into structured
readings. Handles:
- Czech decimal format (comma as decimal separator)
- Czech timestamp format (DD.MM.YYYY HH:MM, including 24:00 edge case)
- Dynamic column discovery (not fixed order)
- Electrometer ID auto-detection from column headers
- Graceful handling of missing/partial data
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedReading:
    """A single parsed 15-minute interval reading."""

    timestamp: datetime
    consumption_kw: Optional[float]  # +A (active import)
    production_kw: Optional[float]  # -A (active export)
    reactive_kw: Optional[float]  # Rv (reactive)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

# Pattern to extract meter ID from column name like "+A/784703", "-A/784703", "Rv/784703"
_METER_ID_PATTERN = re.compile(r"^(?:\+A|-A|Rv)/(\d+)$")

# Czech timestamp: DD.MM.YYYY HH:MM
_TIMESTAMP_PATTERN = re.compile(
    r"^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})$"
)


def parse_czech_decimal(value: Optional[str]) -> Optional[float]:
    """Convert Czech decimal format string to float.

    '1,42' -> 1.42, '0,0' -> 0.0.
    Returns None for None, empty, or unparseable values.
    """
    if value is None or value == "":
        return None
    try:
        return float(value.replace(",", "."))
    except (ValueError, AttributeError):
        return None


def parse_czech_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Convert Czech timestamp 'DD.MM.YYYY HH:MM' to datetime.

    Handles the special '24:00' case (midnight of the next day).
    Returns None for None, empty, or unparseable values.
    """
    if not value:
        return None

    match = _TIMESTAMP_PATTERN.match(value.strip())
    if not match:
        return None

    day, month, year, hour, minute = (int(g) for g in match.groups())

    if hour == 24 and minute == 0:
        # 24:00 means midnight of the next day
        base = datetime(year, month, day)
        return base + timedelta(days=1)

    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def detect_electrometer_id(
    payload: dict, *, fallback_id: Optional[str] = None
) -> Optional[str]:
    """Auto-detect electrometer ID from column headers.

    Looks for column names matching '+A/{id}', '-A/{id}', or 'Rv/{id}'.
    Returns the first detected ID, or fallback_id if none found.
    """
    columns = payload.get("columns", [])
    for col in columns:
        name = col.get("name", "")
        m = _METER_ID_PATTERN.match(name)
        if m:
            return m.group(1)
    return fallback_id


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------


class CezDataParser:
    """Parses a CEZ PND data API response payload.

    Column discovery is dynamic — the parser finds timestamp, +A, -A, Rv
    columns regardless of their order or numeric IDs.
    """

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self._columns = payload.get("columns", [])
        self._values = payload.get("values", [])

        # Discover column IDs
        self.timestamp_col_id: Optional[str] = None
        self.consumption_col_id: Optional[str] = None  # +A
        self.production_col_id: Optional[str] = None  # -A
        self.reactive_col_id: Optional[str] = None  # Rv

        self._electrometer_id: Optional[str] = None

        self._discover_columns()

    def _discover_columns(self) -> None:
        """Map logical roles to column IDs based on column names."""
        for col in self._columns:
            col_id = col.get("id", "")
            name = col.get("name", "")

            if name == "Datum":
                self.timestamp_col_id = col_id
            elif name.startswith("+A/"):
                self.consumption_col_id = col_id
                self._extract_meter_id(name)
            elif name.startswith("-A/"):
                self.production_col_id = col_id
                self._extract_meter_id(name)
            elif name.startswith("Rv/"):
                self.reactive_col_id = col_id
                self._extract_meter_id(name)

    def _extract_meter_id(self, name: str) -> None:
        """Extract electrometer ID from a column name if not already set."""
        if self._electrometer_id is None:
            m = _METER_ID_PATTERN.match(name)
            if m:
                self._electrometer_id = m.group(1)

    @property
    def electrometer_id(self) -> Optional[str]:
        """The detected electrometer ID, or None."""
        return self._electrometer_id

    def _extract_cell_value(
        self, row: dict, col_id: Optional[str]
    ) -> Optional[str]:
        """Get the 'v' string from a cell, or None if missing."""
        if col_id is None:
            return None
        cell = row.get(col_id)
        if cell is None:
            return None
        return cell.get("v")

    def parse_records(self) -> list[ParsedReading]:
        """Parse all value rows into a list of ParsedReading."""
        records: list[ParsedReading] = []
        for row in self._values:
            ts_str = self._extract_cell_value(row, self.timestamp_col_id)
            ts = parse_czech_timestamp(ts_str)
            if ts is None:
                # Skip rows without a valid timestamp
                continue

            consumption = parse_czech_decimal(
                self._extract_cell_value(row, self.consumption_col_id)
            )
            production = parse_czech_decimal(
                self._extract_cell_value(row, self.production_col_id)
            )
            reactive = parse_czech_decimal(
                self._extract_cell_value(row, self.reactive_col_id)
            )

            records.append(
                ParsedReading(
                    timestamp=ts,
                    consumption_kw=consumption,
                    production_kw=production,
                    reactive_kw=reactive,
                )
            )
        return records

    def get_latest_reading(self) -> Optional[ParsedReading]:
        """Return the most recent reading (last in the list), or None."""
        records = self.parse_records()
        if not records:
            return None
        return records[-1]

    def get_latest_reading_dict(self) -> Optional[dict]:
        """Return the latest reading as a flat dict for MQTT publishing.

        Returns None if no readings are available.
        """
        latest = self.get_latest_reading()
        if latest is None:
            return None
        return {
            "timestamp": latest.timestamp.isoformat(),
            "consumption_kw": latest.consumption_kw,
            "production_kw": latest.production_kw,
            "reactive_kw": latest.reactive_kw,
            "electrometer_id": self._electrometer_id,
        }
