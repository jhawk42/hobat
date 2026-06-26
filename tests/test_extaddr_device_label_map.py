"""Tests for extaddr_device_label_map module."""

import json
import tempfile
from pathlib import Path

import pytest

from extaddr_device_label_map import (
    EXTADDR_FIELD_ALIASES,
    get_extaddr_from_record,
    load_extaddr_device_label_map_flexible,
    normalize_extaddr,
)


class TestNormalizeExtaddr:
    """Tests for normalize_extaddr helper."""
    
    def test_normalizes_uppercase_to_lowercase(self):
        """Should convert uppercase extaddr to lowercase."""
        assert normalize_extaddr("AA11BB22CC33DD44") == "aa11bb22cc33dd44"
    
    def test_strips_whitespace(self):
        """Should strip leading and trailing whitespace."""
        assert normalize_extaddr("  AA11BB22CC33DD44  ") == "aa11bb22cc33dd44"
    
    def test_handles_mixed_case(self):
        """Should handle mixed case input."""
        assert normalize_extaddr("Aa11Bb22Cc33Dd44") == "aa11bb22cc33dd44"
    
    def test_returns_empty_for_none(self):
        """Should return empty string for None."""
        assert normalize_extaddr(None) == ""
    
    def test_returns_empty_for_non_string(self):
        """Should return empty string for non-string types."""
        assert normalize_extaddr(123) == ""
        assert normalize_extaddr([]) == ""
        assert normalize_extaddr({}) == ""
    
    def test_handles_empty_string(self):
        """Should handle empty string."""
        assert normalize_extaddr("") == ""
    
    def test_handles_whitespace_only(self):
        """Should return empty for whitespace-only string."""
        assert normalize_extaddr("   ") == ""


class TestGetExtaddrFromRecord:
    """Tests for get_extaddr_from_record helper."""
    
    def test_extracts_from_extaddr_field(self):
        """Should extract from 'extaddr' field."""
        record = {"extAddress": "AA11BB22CC33DD44"}
        assert get_extaddr_from_record(record) == "aa11bb22cc33dd44"
    
    def test_extracts_from_extAddress_field(self):
        """Should extract from 'extAddress' field (camelCase)."""
        record = {"extAddress": "AA11BB22CC33DD44"}
        assert get_extaddr_from_record(record) == "aa11bb22cc33dd44"
    
    def test_extracts_from_extended_mac_field(self):
        """Should extract from 'Extended MAC' field."""
        record = {"Extended MAC": "AA11BB22CC33DD44"}
        assert get_extaddr_from_record(record) == "aa11bb22cc33dd44"
    
    def test_prioritizes_first_alias(self):
        """Should use first matching alias when multiple exist."""
        record = {
            "extAddress": "BB22CC33DD44EE55",
            "extAddress": "AA11BB22CC33DD44",
            "Extended MAC": "CC33DD44EE55FF66",
        }
        # First alias is 'extaddr' in EXTADDR_FIELD_ALIASES
        assert get_extaddr_from_record(record) == "aa11bb22cc33dd44"
    
    def test_returns_empty_when_no_alias_found(self):
        """Should return empty string when no alias field exists."""
        record = {"other_field": "value"}
        assert get_extaddr_from_record(record) == ""
    
    def test_handles_empty_record(self):
        """Should handle empty record."""
        assert get_extaddr_from_record({}) == ""
    
    def test_handles_non_string_values(self):
        """Should skip non-string extaddr values."""
        record = {"extAddress": 12345}
        assert get_extaddr_from_record(record) == ""
    
    def test_custom_aliases(self):
        """Should support custom alias tuple."""
        record = {"custom_field": "AA11BB22CC33DD44"}
        result = get_extaddr_from_record(record, aliases=("custom_field",))
        assert result == "aa11bb22cc33dd44"


class TestLoadExtaddrDeviceLabelMapFlexible:
    """Tests for load_extaddr_device_label_map_flexible loader."""
    
    def test_loads_list_format_with_extaddr(self):
        """Should load list format with 'extaddr' field."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = [
                {"extAddress": "AA11BB22CC33DD44", "device_label": "Kitchen"},
                {"extAddress": "BB22CC33DD44EE55", "device_label": "Bedroom"},
            ]
            json.dump(data, f)
            f.flush()
            
            mapping = load_extaddr_device_label_map_flexible(f.name)
            
            assert mapping == {
                "aa11bb22cc33dd44": "Kitchen",
                "bb22cc33dd44ee55": "Bedroom",
            }
            
            Path(f.name).unlink()
    
    def test_loads_list_format_with_extAddress(self):
        """Should load list format with 'extAddress' field (camelCase)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = [
                {"extAddress": "AA11BB22CC33DD44", "device_label": "Kitchen"},
            ]
            json.dump(data, f)
            f.flush()
            
            mapping = load_extaddr_device_label_map_flexible(f.name)
            
            assert mapping == {"aa11bb22cc33dd44": "Kitchen"}
            
            Path(f.name).unlink()
    
    def test_loads_list_format_with_extended_mac(self):
        """Should load list format with 'Extended MAC' field."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = [
                {"Extended MAC": "AA11BB22CC33DD44", "device_label": "Kitchen"},
            ]
            json.dump(data, f)
            f.flush()
            
            mapping = load_extaddr_device_label_map_flexible(f.name)
            
            assert mapping == {"aa11bb22cc33dd44": "Kitchen"}
            
            Path(f.name).unlink()
    
    def test_loads_dict_format(self):
        """Should load dict format where values contain extaddr mappings."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = {
                "device1": {"extAddress": "AA11BB22CC33DD44", "device_label": "Kitchen"},
                "device2": {"extAddress": "BB22CC33DD44EE55", "device_label": "Bedroom"},
            }
            json.dump(data, f)
            f.flush()
            
            mapping = load_extaddr_device_label_map_flexible(f.name)
            
            assert mapping == {
                "aa11bb22cc33dd44": "Kitchen",
                "bb22cc33dd44ee55": "Bedroom",
            }
            
            Path(f.name).unlink()
    
    def test_strips_device_label_whitespace(self):
        """Should strip whitespace from device labels."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = [
                {"extAddress": "AA11BB22CC33DD44", "device_label": "  Kitchen  "},
            ]
            json.dump(data, f)
            f.flush()
            
            mapping = load_extaddr_device_label_map_flexible(f.name)
            
            assert mapping == {"aa11bb22cc33dd44": "Kitchen"}
            
            Path(f.name).unlink()
    
    def test_skips_entries_without_extaddr(self):
        """Should skip entries that don't have any extaddr field."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = [
                {"extAddress": "AA11BB22CC33DD44", "device_label": "Kitchen"},
                {"device_label": "Bedroom"},  # Missing extaddr
            ]
            json.dump(data, f)
            f.flush()
            
            mapping = load_extaddr_device_label_map_flexible(f.name)
            
            assert mapping == {"aa11bb22cc33dd44": "Kitchen"}
            
            Path(f.name).unlink()
    
    def test_skips_entries_without_device_label(self):
        """Should skip entries without device_label field."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = [
                {"extAddress": "AA11BB22CC33DD44", "device_label": "Kitchen"},
                {"extAddress": "BB22CC33DD44EE55"},  # Missing device_label
            ]
            json.dump(data, f)
            f.flush()
            
            mapping = load_extaddr_device_label_map_flexible(f.name)
            
            assert mapping == {"aa11bb22cc33dd44": "Kitchen"}
            
            Path(f.name).unlink()
    
    def test_skips_entries_with_empty_device_label(self):
        """Should skip entries with empty or whitespace-only device_label."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = [
                {"extAddress": "AA11BB22CC33DD44", "device_label": "Kitchen"},
                {"extAddress": "BB22CC33DD44EE55", "device_label": ""},
                {"extAddress": "CC33DD44EE55FF66", "device_label": "   "},
            ]
            json.dump(data, f)
            f.flush()
            
            mapping = load_extaddr_device_label_map_flexible(f.name)
            
            assert mapping == {"aa11bb22cc33dd44": "Kitchen"}
            
            Path(f.name).unlink()
    
    def test_skips_non_dict_items_in_list(self):
        """Should skip non-dict items in list format."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = [
                {"extAddress": "AA11BB22CC33DD44", "device_label": "Kitchen"},
                "invalid",
                123,
                None,
            ]
            json.dump(data, f)
            f.flush()
            
            mapping = load_extaddr_device_label_map_flexible(f.name)
            
            assert mapping == {"aa11bb22cc33dd44": "Kitchen"}
            
            Path(f.name).unlink()
    
    def test_skips_non_dict_values_in_dict(self):
        """Should skip non-dict values in dict format."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = {
                "device1": {"extAddress": "AA11BB22CC33DD44", "device_label": "Kitchen"},
                "invalid": "string",
                "invalid2": 123,
            }
            json.dump(data, f)
            f.flush()
            
            mapping = load_extaddr_device_label_map_flexible(f.name)
            
            assert mapping == {"aa11bb22cc33dd44": "Kitchen"}
            
            Path(f.name).unlink()
    
    def test_returns_empty_dict_for_missing_file(self):
        """Should return empty dict when file doesn't exist."""
        mapping = load_extaddr_device_label_map_flexible("/nonexistent/file.json")
        assert mapping == {}
    
    def test_returns_empty_dict_for_invalid_json(self):
        """Should return empty dict for invalid JSON."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {")
            f.flush()
            
            mapping = load_extaddr_device_label_map_flexible(f.name)
            
            assert mapping == {}
            
            Path(f.name).unlink()
    
    def test_returns_empty_dict_for_non_list_non_dict_json(self):
        """Should return empty dict for JSON that is neither list nor dict."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump("string value", f)
            f.flush()
            
            mapping = load_extaddr_device_label_map_flexible(f.name)
            
            assert mapping == {}
            
            Path(f.name).unlink()
    
    def test_handles_mixed_alias_formats(self):
        """Should handle mixed extaddr field names in same file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = [
                {"extAddress": "AA11BB22CC33DD44", "device_label": "Kitchen"},
                {"extAddress": "BB22CC33DD44EE55", "device_label": "Bedroom"},
                {"Extended MAC": "CC33DD44EE55FF66", "device_label": "Garage"},
            ]
            json.dump(data, f)
            f.flush()
            
            mapping = load_extaddr_device_label_map_flexible(f.name)
            
            assert mapping == {
                "aa11bb22cc33dd44": "Kitchen",
                "bb22cc33dd44ee55": "Bedroom",
                "cc33dd44ee55ff66": "Garage",
            }
            
            Path(f.name).unlink()
    
    def test_custom_extaddr_aliases(self):
        """Should support custom extaddr aliases."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = [
                {"mac_address": "AA11BB22CC33DD44", "device_label": "Kitchen"},
            ]
            json.dump(data, f)
            f.flush()
            
            mapping = load_extaddr_device_label_map_flexible(
                f.name,
                extaddr_aliases=("mac_address",)
            )
            
            assert mapping == {"aa11bb22cc33dd44": "Kitchen"}
            
            Path(f.name).unlink()
