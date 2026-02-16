"""Tests for live_verify_rules module.

Tests validation functions for PND and HDO data structure.
"""

from __future__ import annotations

import pytest

from pathlib import Path

# Add scripts/ to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from live_verify_rules import (
    validate_pnd_data,
    validate_hdo_data,
)


class TestPndValidation:
    """Test PND data validation (A+B+C)."""

    def test_a_non_empty_payload_passes(self):
        """A: hasData=true, values not empty -> valid."""
        data = {
            "hasData": True,
            "size": 2,
            "columns": [{"id": "1000", "name": "Datum"}],
            "values": {
                "1000": {"v": "16.02.2026 00:00", "s": "32"},
                "1001": {"v": "2.5", "s": "32"},
            },
            "intervalFrom": "16.02.2026 00:00",
            "intervalTo": "16.02.2026 23:59",
        }
        result = validate_pnd_data(data)
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_a_empty_payload_fails(self):
        """A: hasData=false -> invalid."""
        data = {"hasData": False, "size": 0, "values": {}, "columns": []}
        result = validate_pnd_data(data)
        assert result["valid"] is False
        assert "hasData is false or missing" in result["errors"]

    def test_a_size_zero_fails(self):
        """A: size=0 -> invalid."""
        data = {
            "hasData": True,
            "size": 0,
            "values": {},
            "columns": [{"id": "1000", "name": "Datum"}],
        }
        result = validate_pnd_data(data)
        assert result["valid"] is False
        assert "size is 0" in result["errors"]

    def test_a_all_values_empty_fails(self):
        """A: all values are empty/null -> invalid."""
        data = {
            "hasData": True,
            "size": 2,
            "values": {
                "1000": {"v": None, "s": "32"},
                "1001": {"v": "", "s": "32"},
            },
            "columns": [{"id": "1000", "name": "Datum"}],
        }
        result = validate_pnd_data(data)
        assert result["valid"] is False
        assert "all values are empty/null" in result["errors"]

    def test_b_columns_present_passes(self):
        """B: columns exists -> valid."""
        data = {
            "hasData": True,
            "size": 1,
            "columns": [{"id": "1000", "name": "Datum"}],
            "values": {"1000": {"v": "test", "s": "32"}},
            "intervalFrom": "16.02.2026 00:00",
            "intervalTo": "16.02.2026 23:59",
        }
        result = validate_pnd_data(data)
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_missing_signal_fails(self):
        """Missing signal -> invalid."""
        data = {"casy": ["08:00-16:00"], "den": "pondělí", "datum": "16.02.2026"}
        result = validate_hdo_data(data)
        assert result["valid"] is False
        assert "missing required key 'signal'" in result["errors"]

    def test_missing_casy_fails(self):
        """Missing casy -> invalid."""
        data = {"signal": "EVV2", "den": "pondělí", "datum": "16.02.2026"}
        result = validate_hdo_data(data)
        assert result["valid"] is False
        assert "HDO: missing required key 'casy'" in result["errors"][0]

    def test_empty_signal_fails(self):
        """Empty signal -> invalid."""
        data = {"signal": "", "casy": ["08:00-16:00"], "den": "pondělí", "datum": "16.02.2026"}
        result = validate_hdo_data(data)
        assert result["valid"] is False
        assert "signal is missing or empty" in result["errors"]

    def test_invalid_casy_format_fails(self):
        """Invalid casy format -> invalid."""
        data = {
            "signal": "EVV2",
            "casy": ["invalid format"],
            "den": "pondělí",
            "datum": "16.02.2026",
        }
        result = validate_hdo_data(data)
        assert result["valid"] is False
        assert "invalid casy format" in result["errors"][0]

    def test_valid_casy_format_passes(self):
        """Valid casy format (HH:MM-HH:MM) -> valid."""
        data = {
            "signal": "EVV2",
            "casy": ["08:00-16:00", "20:00-22:00"],
            "den": "pondělí",
            "datum": "16.02.2026",
        }
        result = validate_hdo_data(data)
        assert result["valid"] is True

    def test_invalid_datum_format_fails(self):
        """Invalid datum format -> invalid."""
        data = {
            "signal": "EVV2",
            "casy": ["08:00-16:00"],
            "den": "pondělí",
            "datum": "16.02.26",  # Invalid year
        }
        result = validate_hdo_data(data)
        assert result["valid"] is False
        assert "invalid datum format" in result["errors"][0]

    def test_valid_datum_format_passes(self):
        """Valid datum format (DD.MM.YYYY) -> valid."""
        data = {
            "signal": "EVV2",
            "casy": ["08:00-16:00"],
            "den": "pondělí",
            "datum": "16.02.2026",
        }
        result = validate_hdo_data(data)
        assert result["valid"] is True
