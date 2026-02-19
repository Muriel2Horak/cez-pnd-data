import pytest

from addon.src.main import validate_electrometers_config


class TestConfigValidation:
    """Test configuration validation for multi-electrometer setup."""

    def test_valid_pair_list(self):
        """Test that valid electrometer pairs pass validation."""
        valid_config = '[{"electrometer_id": "784703", "ean": "85912345678901"}, {"electrometer_id": "784704", "ean": "85912345678902"}]'
        result = validate_electrometers_config(valid_config)

        assert len(result) == 2
        assert result[0]["electrometer_id"] == "784703"
        assert result[0]["ean"] == "85912345678901"
        assert result[1]["electrometer_id"] == "784704"
        assert result[1]["ean"] == "85912345678902"

    def test_duplicate_electrometer_id_fails(self):
        """Test that duplicate electrometer_id fails with specific error."""
        duplicate_id_config = '[{"electrometer_id": "784703", "ean": "85912345678901"}, {"electrometer_id": "784703", "ean": "85912345678902"}]'

        with pytest.raises(ValueError) as exc_info:
            validate_electrometers_config(duplicate_id_config)

        error_msg = str(exc_info.value)
        assert "duplicate electrometer_id" in error_msg.lower()
        assert "784703" in error_msg

    def test_duplicate_ean_fails(self):
        """Test that duplicate ean fails with specific error."""
        duplicate_ean_config = '[{"electrometer_id": "784703", "ean": "85912345678901"}, {"electrometer_id": "784704", "ean": "85912345678901"}]'

        with pytest.raises(ValueError) as exc_info:
            validate_electrometers_config(duplicate_ean_config)

        error_msg = str(exc_info.value)
        assert "duplicate ean" in error_msg.lower()
        assert "85912345678901" in error_msg

    def test_empty_electrometer_id_fails(self):
        """Test that empty electrometer_id fails validation."""
        empty_id_config = '[{"electrometer_id": "", "ean": "85912345678901"}]'

        with pytest.raises(ValueError) as exc_info:
            validate_electrometers_config(empty_id_config)

        error_msg = str(exc_info.value)
        assert "empty or invalid" in error_msg.lower()
        assert "electrometer_id" in error_msg

    def test_empty_ean_fails(self):
        """Test that empty ean fails validation."""
        empty_ean_config = '[{"electrometer_id": "784703", "ean": ""}]'

        with pytest.raises(ValueError) as exc_info:
            validate_electrometers_config(empty_ean_config)

        error_msg = str(exc_info.value)
        assert "empty or invalid" in error_msg.lower()
        assert "ean" in error_msg

    def test_malformed_json_fails(self):
        """Test that malformed JSON fails validation."""
        malformed_config = '[{"electrometer_id": "784703", "ean": "85912345678901"'

        with pytest.raises(ValueError) as exc_info:
            validate_electrometers_config(malformed_config)

        error_msg = str(exc_info.value)
        assert "malformed json" in error_msg.lower()

    def test_missing_field_fails(self):
        """Test that missing required field fails validation."""
        missing_ean_config = '[{"electrometer_id": "784703"}]'

        with pytest.raises(ValueError) as exc_info:
            validate_electrometers_config(missing_ean_config)

        error_msg = str(exc_info.value)
        assert "missing required field" in error_msg.lower()
        assert "ean" in error_msg

    def test_single_scalar_backward_compat(self):
        """Test that single scalar electrometer_id passes for backward compatibility."""
        result = validate_electrometers_config(None)
        assert result == []

        result = validate_electrometers_config("")
        assert result == []

    def test_not_array_fails(self):
        """Test that non-array JSON fails validation."""
        object_config = '{"electrometer_id": "784703", "ean": "85912345678901"}'

        with pytest.raises(ValueError) as exc_info:
            validate_electrometers_config(object_config)

        error_msg = str(exc_info.value)
        assert "must be a json array" in error_msg.lower()

    def test_non_object_element_fails(self):
        """Test that non-object element in array fails validation."""
        non_object_config = (
            '[{"electrometer_id": "784703", "ean": "85912345678901"}, "invalid"]'
        )

        with pytest.raises(ValueError) as exc_info:
            validate_electrometers_config(non_object_config)

        error_msg = str(exc_info.value)
        assert "must be an object" in error_msg.lower()

    def test_whitespace_values_fails(self):
        """Test that whitespace-only values fail validation."""
        whitespace_config = '[{"electrometer_id": "   ", "ean": "85912345678901"}]'

        with pytest.raises(ValueError) as exc_info:
            validate_electrometers_config(whitespace_config)

        error_msg = str(exc_info.value)
        assert "empty or invalid" in error_msg.lower()
        assert "electrometer_id" in error_msg

    def test_single_electrometer_passes(self):
        """Test that single valid electrometer passes validation."""
        single_config = '[{"electrometer_id": "784703", "ean": "85912345678901"}]'
        result = validate_electrometers_config(single_config)

        assert len(result) == 1
        assert result[0]["electrometer_id"] == "784703"
        assert result[0]["ean"] == "85912345678901"
