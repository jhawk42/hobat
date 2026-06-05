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
    collect_per_router,
    is_response_timeout_error,
    load_extaddr_map_or_empty,
    parse_conn_time,
    parse_err_rate_metrics,
    parse_rss_metrics,
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
        monkeypatch.delenv("TD_DATA_DIR", raising=False)
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
    
    def test_output_path_is_none_when_filename_not_provided(self, tmp_path, monkeypatch):
        """Should set output_path to None when default_output_filename is None."""
        monkeypatch.delenv("TD_DATA_DIR", raising=False)
        custom_datadir = tmp_path / "data"
        custom_datadir.mkdir()
        
        runtime = resolve_collector_runtime(
            datadir_arg=str(custom_datadir),
            default_output_filename=None,
        )
        
        assert runtime.td_data_dir == custom_datadir
        assert runtime.extaddr_map_path == custom_datadir / EXTADDR_DEVICE_LABEL_MAP_FILENAME
        assert runtime.output_path is None
    
    def test_extaddr_map_path_always_resolved(self, tmp_path, monkeypatch):
        """Should always resolve extaddr_map_path even if file doesn't exist."""
        monkeypatch.delenv("TD_DATA_DIR", raising=False)
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
    
    def test_respects_datadir_arg_over_td_data_dir_env_var(self, tmp_path, monkeypatch):
        """Should prioritize explicit datadir_arg over TD_DATA_DIR."""
        env_datadir = tmp_path / "env_data"
        cli_datadir = tmp_path / "cli_data"
        env_datadir.mkdir()
        cli_datadir.mkdir()
        
        monkeypatch.setenv("TD_DATA_DIR", str(env_datadir))
        
        runtime = resolve_collector_runtime(
            datadir_arg=str(cli_datadir),
            default_output_filename="output.json",
        )
        
        assert runtime.td_data_dir == cli_datadir

    def test_respects_td_data_dir_env_var_when_datadir_arg_missing(self, tmp_path, monkeypatch):
        """Should use TD_DATA_DIR when explicit datadir_arg is not provided."""
        env_datadir = tmp_path / "env_data"
        env_datadir.mkdir()

        monkeypatch.setenv("TD_DATA_DIR", str(env_datadir))

        runtime = resolve_collector_runtime(
            datadir_arg=None,
            default_output_filename="output.json",
        )

        assert runtime.td_data_dir == env_datadir


class TestIntegrationScenario:
    """Integration tests combining multiple helper functions."""
    
    def test_typical_collector_workflow(self, tmp_path, monkeypatch):
        """Test typical OTBR CLI collector initialization pattern."""
        monkeypatch.delenv("TD_DATA_DIR", raising=False)
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
            rloc_key="rloc16"
        )
        
        assert "rloc16" in result
        assert result["rloc16"] == "0x5000"
        assert "parent_rloc16" not in result
    
    def test_builds_childip6_style_error_record(self):
        """Should match childip6 error record structure."""
        result = build_timeout_error_record(
            rloc16="0x5000",
            device_label="Living Room Bulb",
            result_table_key="router_child_ip6_table",
            rloc_key="rloc16"
        )
        
        expected = {
            "rloc16": "0x5000",
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
            rloc_key="rloc16"
        )
        
        expected = {
            "rloc16": "0x6400",
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


class TestCollectPerRouter:
    """Tests for collect_per_router orchestration helper."""
    
    def test_collects_data_for_all_routers(self):
        """Should call collect_fn for each router and return list of results."""
        router_table = [
            {"rloc16": "0x5000", "extaddr": "aabbccddeeff0011"},
            {"rloc16": "0x6400", "extaddr": "1122334455667788"},
            {"rloc16": "0x2800", "extaddr": "8877665544332211"},
        ]
        
        def mock_collect(rloc16, router, extaddr_map):
            return {"rloc16": rloc16, "data": f"collected for {rloc16}"}
        
        results = collect_per_router(
            router_table_data=router_table,
            collect_fn=mock_collect,
            extaddr_map=None,
            collection_name="test data"
        )
        
        assert len(results) == 3
        assert results[0] == {"rloc16": "0x5000", "data": "collected for 0x5000"}
        assert results[1] == {"rloc16": "0x6400", "data": "collected for 0x6400"}
        assert results[2] == {"rloc16": "0x2800", "data": "collected for 0x2800"}
    
    def test_returns_empty_list_for_empty_router_table(self):
        """Should return empty list when router table is empty."""
        def mock_collect(rloc16, router, extaddr_map):
            return {"rloc16": rloc16}
        
        results = collect_per_router(
            router_table_data=[],
            collect_fn=mock_collect,
            collection_name="test data"
        )
        
        assert results == []
    
    def test_passes_router_object_and_extaddr_map_to_callback(self):
        """Should pass full router object and extaddr_map to collect_fn."""
        router_table = [
            {"rloc16": "0x5000", "extaddr": "aabbccddeeff0011", "version": 5},
        ]
        extaddr_map = {"aabbccddeeff0011": "Router 1"}
        
        collected_args = []
        
        def mock_collect(rloc16, router, extaddr_map):
            collected_args.append((rloc16, router, extaddr_map))
            return {"rloc16": rloc16}
        
        collect_per_router(
            router_table_data=router_table,
            collect_fn=mock_collect,
            extaddr_map=extaddr_map,
            collection_name="test"
        )
        
        assert len(collected_args) == 1
        assert collected_args[0][0] == "0x5000"
        assert collected_args[0][1] == {"rloc16": "0x5000", "extaddr": "aabbccddeeff0011", "version": 5}
        assert collected_args[0][2] == {"aabbccddeeff0011": "Router 1"}
    
    def test_filters_out_routers_without_rloc16(self):
        """Should skip routers that don't have rloc16 field."""
        router_table = [
            {"rloc16": "0x5000", "extaddr": "aabbccddeeff0011"},
            {"extaddr": "1122334455667788"},  # Missing rloc16
            {"rloc16": None, "extaddr": "8877665544332211"},  # None rloc16
            {"rloc16": "0x6400", "extaddr": "ffeeddccbbaa9988"},
        ]
        
        call_count = 0
        
        def mock_collect(rloc16, router, extaddr_map):
            nonlocal call_count
            call_count += 1
            return {"rloc16": rloc16}
        
        results = collect_per_router(
            router_table_data=router_table,
            collect_fn=mock_collect,
            collection_name="test"
        )
        
        # Should only collect for routers with valid rloc16
        assert call_count == 2
        assert len(results) == 2
        assert results[0]["rloc16"] == "0x5000"
        assert results[1]["rloc16"] == "0x6400"
    
    def test_logs_collection_start_with_device_context(self, caplog):
        """Should log collection start with device label and extaddr."""
        router_table = [
            {"rloc16": "0x5000", "extaddr": "aabbccddeeff0011"},
        ]
        extaddr_map = {"aabbccddeeff0011": "Living Room Bulb"}
        
        def mock_collect(rloc16, router, extaddr_map):
            return {"rloc16": rloc16}
        
        with caplog.at_level(logging.INFO):
            collect_per_router(
                router_table_data=router_table,
                collect_fn=mock_collect,
                extaddr_map=extaddr_map,
                collection_name="meshdiag childtable"
            )
        
        assert len(caplog.records) == 1
        log_message = caplog.records[0].message
        assert "Getting meshdiag childtable" in log_message
        assert "0x5000" in log_message
        assert "Living Room Bulb" in log_message
        assert "aabbccddeeff0011" in log_message
    
    def test_logs_unknown_when_no_extaddr_map(self, caplog):
        """Should log 'Unknown' device label when extaddr_map is None."""
        router_table = [
            {"rloc16": "0x5000", "extaddr": "aabbccddeeff0011"},
        ]
        
        def mock_collect(rloc16, router, extaddr_map):
            return {"rloc16": rloc16}
        
        with caplog.at_level(logging.INFO):
            collect_per_router(
                router_table_data=router_table,
                collect_fn=mock_collect,
                extaddr_map=None,
                collection_name="meshdiag childip6"
            )
        
        log_message = caplog.records[0].message
        assert "Unknown" in log_message
        assert "0x5000" in log_message
    
    def test_logs_unknown_when_extaddr_not_in_map(self, caplog):
        """Should log 'Unknown' when extaddr not found in map."""
        router_table = [
            {"rloc16": "0x5000", "extaddr": "aabbccddeeff0011"},
        ]
        extaddr_map = {"different_extaddr": "Some Device"}
        
        def mock_collect(rloc16, router, extaddr_map):
            return {"rloc16": rloc16}
        
        with caplog.at_level(logging.INFO):
            collect_per_router(
                router_table_data=router_table,
                collect_fn=mock_collect,
                extaddr_map=extaddr_map,
                collection_name="test"
            )
        
        log_message = caplog.records[0].message
        assert "Unknown" in log_message
    
    def test_collect_fn_can_return_any_dict_structure(self):
        """Should work with any dict structure returned by collect_fn."""
        router_table = [
            {"rloc16": "0x5000", "extaddr": "aabbccddeeff0011"},
        ]
        
        def mock_collect(rloc16, router, extaddr_map):
            return {
                "rloc16": rloc16,
                "device_label": "Test",
                "router_child_table": [{"child": 1}, {"child": 2}],
                "router_child_table_count": 2,
            }
        
        results = collect_per_router(
            router_table_data=router_table,
            collect_fn=mock_collect,
            collection_name="test"
        )
        
        assert len(results) == 1
        assert results[0]["rloc16"] == "0x5000"
        assert results[0]["router_child_table_count"] == 2
    
    def test_maintains_order_of_router_table(self):
        """Should maintain the order of routers from router_table_data."""
        router_table = [
            {"rloc16": "0x2800", "extaddr": "third"},
            {"rloc16": "0x5000", "extaddr": "first"},
            {"rloc16": "0x6400", "extaddr": "second"},
        ]
        
        def mock_collect(rloc16, router, extaddr_map):
            return {"rloc16": rloc16, "extaddr": router.get("extaddr")}
        
        results = collect_per_router(
            router_table_data=router_table,
            collect_fn=mock_collect,
            collection_name="test"
        )
        
        assert results[0]["extaddr"] == "third"
        assert results[1]["extaddr"] == "first"
        assert results[2]["extaddr"] == "second"


class TestParseRssMetrics:
    """Tests for parse_rss_metrics telemetry parser."""
    
    def test_parses_valid_rss_line(self):
        """Should parse RSS metrics with all three values."""
        line = "rss - ave:-20 last:-18 margin:80"
        result = parse_rss_metrics(line)
        
        assert result == {
            "rss_ave": -20,
            "rss_last": -18,
            "rss_margin": 80,
        }
    
    def test_parses_positive_rss_values(self):
        """Should handle positive RSS values."""
        line = "rss - ave:15 last:20 margin:100"
        result = parse_rss_metrics(line)
        
        assert result["rss_ave"] == 15
        assert result["rss_last"] == 20
        assert result["rss_margin"] == 100
    
    def test_parses_with_extra_whitespace(self):
        """Should handle variations in whitespace."""
        line = "  rss  -  ave:-25  last:-22  margin:85  "
        result = parse_rss_metrics(line)
        
        assert result is not None
        assert result["rss_ave"] == -25
    
    def test_returns_none_for_non_matching_line(self):
        """Should return None for lines that don't match pattern."""
        assert parse_rss_metrics("some other line") is None
        assert parse_rss_metrics("") is None
        assert parse_rss_metrics("rss: invalid format") is None
    
    def test_returns_none_for_incomplete_rss_line(self):
        """Should return None if RSS line is missing fields."""
        assert parse_rss_metrics("rss - ave:-20 last:-18") is None
        assert parse_rss_metrics("rss - ave:-20") is None
    
    def test_parses_zero_values(self):
        """Should handle zero RSS values."""
        line = "rss - ave:0 last:0 margin:0"
        result = parse_rss_metrics(line)
        
        assert result["rss_ave"] == 0
        assert result["rss_last"] == 0
        assert result["rss_margin"] == 0


class TestParseErrRateMetrics:
    """Tests for parse_err_rate_metrics telemetry parser."""
    
    def test_parses_valid_err_rate_line(self):
        """Should parse error rate percentages."""
        line = "err-rate - frame:0.50% msg:1.25%"
        result = parse_err_rate_metrics(line)
        
        assert result == {
            "err_rate_frame_pct": 0.5,
            "err_rate_msg_pct": 1.25,
        }
    
    def test_parses_integer_percentages(self):
        """Should handle integer error rates without decimal."""
        line = "err-rate - frame:2% msg:3%"
        result = parse_err_rate_metrics(line)
        
        assert result["err_rate_frame_pct"] == 2.0
        assert result["err_rate_msg_pct"] == 3.0
    
    def test_parses_zero_error_rates(self):
        """Should handle zero error rates."""
        line = "err-rate - frame:0.00% msg:0.00%"
        result = parse_err_rate_metrics(line)
        
        assert result["err_rate_frame_pct"] == 0.0
        assert result["err_rate_msg_pct"] == 0.0
    
    def test_parses_high_error_rates(self):
        """Should handle high error rate values."""
        line = "err-rate - frame:99.99% msg:100.00%"
        result = parse_err_rate_metrics(line)
        
        assert result["err_rate_frame_pct"] == 99.99
        assert result["err_rate_msg_pct"] == 100.0
    
    def test_parses_with_extra_whitespace(self):
        """Should handle variations in whitespace."""
        line = "  err-rate  -  frame:1.5%  msg:2.5%  "
        result = parse_err_rate_metrics(line)
        
        assert result is not None
        assert result["err_rate_frame_pct"] == 1.5
    
    def test_returns_none_for_non_matching_line(self):
        """Should return None for lines that don't match pattern."""
        assert parse_err_rate_metrics("some other line") is None
        assert parse_err_rate_metrics("") is None
        assert parse_err_rate_metrics("err-rate: invalid") is None
    
    def test_returns_none_for_incomplete_err_rate_line(self):
        """Should return None if error rate line is missing fields."""
        assert parse_err_rate_metrics("err-rate - frame:0.5%") is None
        assert parse_err_rate_metrics("err-rate - msg:1.0%") is None


class TestParseConnTime:
    """Tests for parse_conn_time telemetry parser."""
    
    def test_parses_time_format(self):
        """Should parse connection time in HH:MM:SS format."""
        line = "conn-time:00:12:34"
        result = parse_conn_time(line)
        
        assert result == "00:12:34"
    
    def test_parses_duration_format(self):
        """Should parse connection time in duration format."""
        line = "conn-time:1d2h3m"
        result = parse_conn_time(line)
        
        assert result == "1d2h3m"
    
    def test_parses_numeric_format(self):
        """Should parse numeric connection time values."""
        line = "conn-time:123456"
        result = parse_conn_time(line)
        
        assert result == "123456"
    
    def test_parses_with_extra_whitespace(self):
        """Should handle leading/trailing whitespace."""
        line = "  conn-time:00:05:30  "
        result = parse_conn_time(line)
        
        assert result == "00:05:30"
    
    def test_returns_none_for_non_matching_line(self):
        """Should return None for lines that don't match pattern."""
        assert parse_conn_time("some other line") is None
        assert parse_conn_time("") is None
        assert parse_conn_time("connection-time:invalid") is None
    
    def test_parses_short_time_values(self):
        """Should parse short connection time values."""
        line = "conn-time:1m"
        result = parse_conn_time(line)
        
        assert result == "1m"
    
    def test_parses_complex_time_format(self):
        """Should parse complex time formats."""
        line = "conn-time:2d15h42m36s"
        result = parse_conn_time(line)
        
        assert result == "2d15h42m36s"
