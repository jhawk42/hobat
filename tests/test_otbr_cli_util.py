"""Tests for otbr_cli_util shared utility functions."""

import json
import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from otbr_cli_util import (
    build_timeout_error_record,
    is_response_timeout_error,
    load_extaddr_map_or_empty,
    resolve_collector_runtime,
)
from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME


class TestLoadExtaddrMapOrEmpty:
    """Tests for load_extaddr_map_or_empty helper function."""
    
    def test_returns_empty_dict_when_path_is_none(self):
        """Should return empty dict and log warning when path is None."""
        logger = Mock(spec=logging.Logger)
        result = load_extaddr_map_or_empty(path=None, logger=logger)
        
        assert result == {}
        logger.warning.assert_called_once()
        assert "No extaddr map path" in logger.warning.call_args[0][0]
    
    def test_returns_empty_dict_when_file_missing(self, tmp_path):
        """Should return empty dict and log warning when file doesn't exist."""
        logger = Mock(spec=logging.Logger)
        missing_path = tmp_path / "nonexistent.json"
        
        result = load_extaddr_map_or_empty(path=missing_path, logger=logger)
        
        assert result == {}
        logger.warning.assert_called_once()
        assert "not found" in logger.warning.call_args[0][0]
        assert str(missing_path) in logger.warning.call_args[0][0]
    
    def test_loads_valid_extaddr_map(self, tmp_path):
        """Should load and return valid extaddr map with info log."""
        logger = Mock(spec=logging.Logger)
        map_file = tmp_path / "extaddr-map.json"
        
        extaddr_data = [
            {"extaddr": "1a7fbf0434e4f043", "device_label": "Living Room Bulb"},
            {"extaddr": "8672766ae0578187", "device_label": "Kitchen Sensor"},
        ]
        map_file.write_text(json.dumps(extaddr_data))
        
        result = load_extaddr_map_or_empty(path=map_file, logger=logger)
        
        assert result == {
            "1a7fbf0434e4f043": "Living Room Bulb",
            "8672766ae0578187": "Kitchen Sensor",
        }
        logger.info.assert_called_once()
        assert "Loading extended address" in logger.info.call_args[0][0]
        assert str(map_file) in logger.info.call_args[0][0]
    
    def test_returns_empty_dict_for_invalid_json(self, tmp_path):
        """Should return empty dict when JSON is invalid (error logged by loader)."""
        logger = Mock(spec=logging.Logger)
        map_file = tmp_path / "invalid.json"
        map_file.write_text("{ invalid json }")
        
        result = load_extaddr_map_or_empty(path=map_file, logger=logger)
        
        # Underlying loader logs the JSON error
        assert result == {}
    
    def test_returns_empty_dict_for_non_list_json(self, tmp_path):
        """Should return empty dict when JSON is not a list (handled by loader)."""
        logger = Mock(spec=logging.Logger)
        map_file = tmp_path / "wrong-format.json"
        map_file.write_text('{"not": "a list"}')
        
        result = load_extaddr_map_or_empty(path=map_file, logger=logger)
        
        # Underlying loader logs the format error
        assert result == {}
    
    def test_uses_root_logger_when_none_provided(self, tmp_path):
        """Should use root logger when logger arg is None."""
        missing_path = tmp_path / "missing.json"
        
        # Should not raise, just use root logger
        result = load_extaddr_map_or_empty(path=missing_path, logger=None)
        
        assert result == {}
    
    def test_handles_pathlib_path(self, tmp_path):
        """Should accept pathlib.Path in addition to string paths."""
        logger = Mock(spec=logging.Logger)
        map_file = tmp_path / "extaddr-map.json"
        
        extaddr_data = [
            {"extaddr": "abc123", "device_label": "Test Device"},
        ]
        map_file.write_text(json.dumps(extaddr_data))
        
        # Pass Path object (not string)
        result = load_extaddr_map_or_empty(path=Path(map_file), logger=logger)
        
        assert result == {"abc123": "Test Device"}


class TestResolveCollectorRuntime:
    """Tests for resolve_collector_runtime helper function."""
    
    def test_resolves_with_explicit_datadir_arg(self, tmp_path, monkeypatch):
        """Should use explicit datadir_arg when provided."""
        custom_datadir = tmp_path / "custom_data"
        custom_datadir.mkdir()
        
        runtime = resolve_collector_runtime(
            datadir_arg=str(custom_datadir),
            default_output_filename="test-output.json",
        )
        
        assert runtime.td_data_dir == custom_datadir
        assert runtime.extaddr_map_path == custom_datadir / EXTADDR_DEVICE_LABEL_MAP_FILENAME
        assert runtime.output_path == custom_datadir / "test-output.json"
    
    def test_resolves_without_datadir_arg(self, tmp_path, monkeypatch):
        """Should fall back to default resolution when datadir_arg is None."""
        # Unset TD_DATA_DIR to ensure clean test environment
        monkeypatch.delenv("TD_DATA_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        
        runtime = resolve_collector_runtime(
            datadir_arg=None,
            default_output_filename="test-output.json",
        )
        
        # Should use default resolution (either /data or ./data)
        assert runtime.td_data_dir is not None
        assert runtime.extaddr_map_path.name == EXTADDR_DEVICE_LABEL_MAP_FILENAME
        assert runtime.output_path.name == "test-output.json"
    
    def test_output_path_is_none_when_filename_not_provided(self, tmp_path):
        """Should set output_path to None when default_output_filename is None."""
        custom_datadir = tmp_path / "data"
        custom_datadir.mkdir()
        
        runtime = resolve_collector_runtime(
            datadir_arg=str(custom_datadir),
            default_output_filename=None,
        )
        
        assert runtime.td_data_dir == custom_datadir
        assert runtime.extaddr_map_path == custom_datadir / EXTADDR_DEVICE_LABEL_MAP_FILENAME
        assert runtime.output_path is None
    
    def test_extaddr_map_path_always_resolved(self, tmp_path):
        """Should always resolve extaddr_map_path even if file doesn't exist."""
        custom_datadir = tmp_path / "data"
        custom_datadir.mkdir()
        
        runtime = resolve_collector_runtime(
            datadir_arg=str(custom_datadir),
            default_output_filename="output.json",
        )
        
        # Path is resolved but file doesn't have to exist
        assert runtime.extaddr_map_path == custom_datadir / EXTADDR_DEVICE_LABEL_MAP_FILENAME
        assert not runtime.extaddr_map_path.exists()  # File not created
    
    def test_dataclass_is_frozen(self, tmp_path):
        """Should return frozen dataclass (immutable)."""
        custom_datadir = tmp_path / "data"
        custom_datadir.mkdir()
        
        runtime = resolve_collector_runtime(
            datadir_arg=str(custom_datadir),
            default_output_filename="output.json",
        )
        
        # Should not be able to modify
        with pytest.raises(Exception):  # FrozenInstanceError
            runtime.td_data_dir = Path("/other/path")
    
    def test_multiple_collectors_use_same_datadir(self, tmp_path):
        """Should resolve different output files to same datadir."""
        custom_datadir = tmp_path / "data"
        custom_datadir.mkdir()
        
        runtime1 = resolve_collector_runtime(
            datadir_arg=str(custom_datadir),
            default_output_filename="childtables.json",
        )
        runtime2 = resolve_collector_runtime(
            datadir_arg=str(custom_datadir),
            default_output_filename="neighbortables.json",
        )
        
        # Same datadir and extaddr_map_path
        assert runtime1.td_data_dir == runtime2.td_data_dir
        assert runtime1.extaddr_map_path == runtime2.extaddr_map_path
        
        # Different output files
        assert runtime1.output_path.name == "childtables.json"
        assert runtime2.output_path.name == "neighbortables.json"
    
    def test_respects_td_data_dir_env_var(self, tmp_path, monkeypatch):
        """Should prioritize TD_DATA_DIR environment variable."""
        env_datadir = tmp_path / "env_data"
        env_datadir.mkdir()
        
        monkeypatch.setenv("TD_DATA_DIR", str(env_datadir))
        
        # Pass None to test env var takes precedence
        runtime = resolve_collector_runtime(
            datadir_arg=None,
            default_output_filename="output.json",
        )
        
        assert runtime.td_data_dir == env_datadir


class TestIntegrationScenario:
    """Integration tests combining multiple helper functions."""
    
    def test_typical_collector_workflow(self, tmp_path):
        """Test typical OTBR CLI collector initialization pattern."""
        # Setup test data
        datadir = tmp_path / "data"
        datadir.mkdir()
        
        extaddr_map_file = datadir / EXTADDR_DEVICE_LABEL_MAP_FILENAME
        extaddr_data = [
            {"extaddr": "aabbccddeeff0011", "device_label": "Router 1"},
            {"extaddr": "1122334455667788", "device_label": "Child 1"},
        ]
        extaddr_map_file.write_text(json.dumps(extaddr_data))
        
        # Typical collector initialization
        runtime = resolve_collector_runtime(
            datadir_arg=str(datadir),
            default_output_filename="td-otbr-cli-test-output.json",
        )
        
        extaddr_map = load_extaddr_map_or_empty(
            path=runtime.extaddr_map_path,
            logger=None,
        )
        
        # Verify workflow
        assert runtime.td_data_dir == datadir
        assert extaddr_map == {
            "aabbccddeeff0011": "Router 1",
            "1122334455667788": "Child 1",
        }
        assert runtime.output_path == datadir / "td-otbr-cli-test-output.json"
        
        # Simulate saving output
        output_data = {"devices": [{"extaddr": "aabbccddeeff0011"}]}
        runtime.output_path.write_text(json.dumps(output_data))
        
        # Verify output file written
        assert runtime.output_path.exists()
        assert json.loads(runtime.output_path.read_text()) == output_data


class TestIsResponseTimeoutError:
    """Tests for is_response_timeout_error helper function."""
    
    def test_detects_timeout_with_error_code(self):
        """Should detect ResponseTimeout with error code pattern."""
        output = "Error 6: ResponseTimeout\nDone"
        assert is_response_timeout_error(output) is True
    
    def test_detects_timeout_with_different_error_codes(self):
        """Should detect ResponseTimeout regardless of error code."""
        assert is_response_timeout_error("Error 1: ResponseTimeout") is True
        assert is_response_timeout_error("Error 23: ResponseTimeout") is True
        assert is_response_timeout_error("Error 999: ResponseTimeout") is True
    
    def test_detects_timeout_with_extra_whitespace(self):
        """Should handle variations in whitespace."""
        assert is_response_timeout_error("Error  6:  ResponseTimeout") is True
        assert is_response_timeout_error("Error\t6:\tResponseTimeout") is True
    
    def test_returns_false_for_normal_output(self):
        """Should return False for successful command output."""
        output = """rloc16:0x5000 ext-addr:1a7fbf0434e4f043 ver:5
ip6-addrs:
    - fd00::1
Done"""
        assert is_response_timeout_error(output) is False
    
    def test_returns_false_for_different_errors(self):
        """Should not match other error types."""
        assert is_response_timeout_error("Error 1: InvalidArgument") is False
        assert is_response_timeout_error("Error 2: NotFound") is False
        assert is_response_timeout_error("Timeout occurred") is False
    
    def test_returns_false_for_empty_string(self):
        """Should return False for empty output."""
        assert is_response_timeout_error("") is False
    
    def test_detects_timeout_within_multiline_output(self):
        """Should detect timeout anywhere in output."""
        output = """
Processing request...
Waiting for response...
Error 6: ResponseTimeout
Failed to get diagnostic data
Done
"""
        assert is_response_timeout_error(output) is True


class TestBuildTimeoutErrorRecord:
    """Tests for build_timeout_error_record helper function."""
    
    def test_builds_basic_error_record(self):
        """Should build error record with minimal arguments."""
        result = build_timeout_error_record(rloc16="0x5000")
        
        assert result["rloc16"] == "0x5000"
        assert result["device_label"] == "Unknown"
        assert result["result_table"] == []
        assert result["result_table_count"] == 0
        assert result["_error"] == {"type": "ResponseTimeout"}
    
    def test_builds_error_record_with_device_label(self):
        """Should include provided device label."""
        result = build_timeout_error_record(
            rloc16="0x5000",
            device_label="Kitchen Sensor"
        )
        
        assert result["device_label"] == "Kitchen Sensor"
    
    def test_builds_error_record_with_custom_result_key(self):
        """Should use custom result table key name."""
        result = build_timeout_error_record(
            rloc16="0x5000",
            result_table_key="router_child_table"
        )
        
        assert "router_child_table" in result
        assert result["router_child_table"] == []
        assert result["router_child_table_count"] == 0
    
    def test_builds_error_record_with_custom_rloc_key(self):
        """Should use custom rloc field name."""
        result = build_timeout_error_record(
            rloc16="0x5000",
            rloc_key="parent_rloc16"
        )
        
        assert "parent_rloc16" in result
        assert result["parent_rloc16"] == "0x5000"
        assert "rloc16" not in result
    
    def test_builds_childip6_style_error_record(self):
        """Should match childip6 error record structure."""
        result = build_timeout_error_record(
            rloc16="0x5000",
            device_label="Living Room Bulb",
            result_table_key="router_child_ip6_table",
            rloc_key="parent_rloc16"
        )
        
        expected = {
            "parent_rloc16": "0x5000",
            "device_label": "Living Room Bulb",
            "router_child_ip6_table": [],
            "router_child_ip6_table_count": 0,
            "_error": {"type": "ResponseTimeout"},
        }
        assert result == expected
    
    def test_builds_childtable_style_error_record(self):
        """Should match childtable error record structure."""
        result = build_timeout_error_record(
            rloc16="0x6400",
            device_label="Bedroom Switch",
            result_table_key="router_child_table",
            rloc_key="parent_rloc16"
        )
        
        expected = {
            "parent_rloc16": "0x6400",
            "device_label": "Bedroom Switch",
            "router_child_table": [],
            "router_child_table_count": 0,
            "_error": {"type": "ResponseTimeout"},
        }
        assert result == expected
    
    def test_builds_routerneighbortable_style_error_record(self):
        """Should match routerneighbortable error record structure."""
        result = build_timeout_error_record(
            rloc16="0x2800",
            device_label="Gateway",
            result_table_key="router_neighbor_table",
            rloc_key="rloc16"
        )
        
        expected = {
            "rloc16": "0x2800",
            "device_label": "Gateway",
            "router_neighbor_table": [],
            "router_neighbor_table_count": 0,
            "_error": {"type": "ResponseTimeout"},
        }
        assert result == expected
    
    def test_error_type_is_always_response_timeout(self):
        """Should always set error type to ResponseTimeout."""
        result = build_timeout_error_record(rloc16="0x1234")
        assert result["_error"]["type"] == "ResponseTimeout"
    
    def test_result_table_is_always_empty_list(self):
        """Should always initialize result table as empty list."""
        result = build_timeout_error_record(
            rloc16="0x1234",
            result_table_key="test_table"
        )
        assert "test_table" in result
        assert result["test_table"] == []
        assert isinstance(result["test_table"], list)
    
    def test_count_is_always_zero(self):
        """Should always set count to 0."""
        result = build_timeout_error_record(rloc16="0x1234")
        # Find the count key
        for key in result:
            if key.endswith("_count"):
                assert result[key] == 0
