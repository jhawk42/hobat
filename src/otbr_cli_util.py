"""Shared utility functions for OTBR CLI collectors.

This module provides common helper functions used across multiple OTBR CLI
collector modules (meshdiag, networkdiag, router table, etc.) to reduce
code duplication and standardize patterns.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from extaddr_device_label_map import load_extaddr_device_label_map
from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME
from util_data import data_file_path, load_optional_input, resolve_data_dir


@dataclass(frozen=True)
class CollectorRuntime:
    """Resolved runtime configuration for an OTBR CLI collector.
    
    Attributes:
        td_data_dir: Resolved data directory path
        extaddr_map_path: Full path to extaddr label map file
        output_path: Full path to output JSON file (if specified)
    """
    td_data_dir: Path
    extaddr_map_path: Path
    output_path: Path | None = None


def load_extaddr_map_or_empty(
    path: str | os.PathLike[str] | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, str]:
    """Load extaddr-to-device-label map with safe fallback to empty dict.
    
    This function standardizes the pattern used across OTBR CLI collectors:
    - If path is None or file doesn't exist: log warning and return {}
    - If file exists: log info and load the mapping
    - If JSON is invalid: return {} (error logged by underlying loader)
    
    Args:
        path: Path to the extaddr label map JSON file. If None, returns empty dict.
        logger: Optional logger for info/warning messages. If None, uses root logger.
    
    Returns:
        Dictionary mapping extaddr (lowercase hex) to device_label string.
        Returns empty dict if file is missing or invalid.
    
    Examples:
        >>> extaddr_map = load_extaddr_map_or_empty("/data/td-static-extaddr-device-label.json")
        >>> device_label = extaddr_map.get("1a7fbf0434e4f043", "Unknown")
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    if path is None:
        logger.warning(
            "No extaddr map path provided. Continuing with empty label map."
        )
        return {}

    logger.info(
        f"Loading extended address to device label mapping from {path}..."
    )
    result = load_optional_input(
        path,
        loader=lambda p: load_extaddr_device_label_map(str(p)),
        default_value={},
        command_path="otbr-cli",
        data_dir=Path(path).resolve().parent,
        logger=logger,
        classification="optional",
        fallback_action="continue fallback=empty-map",
    )
    return result.value


def resolve_collector_runtime(
    datadir_arg: str | os.PathLike[str] | None = None,
    default_output_filename: str | None = None,
) -> CollectorRuntime:
    """Resolve standard runtime paths for an OTBR CLI collector.
    
    This function standardizes the datadir and output path resolution pattern
    used by all OTBR CLI collectors, handling environment variables, CLI args,
    and defaults consistently.
    
    Args:
        datadir_arg: Data directory from CLI argument (typically from parse_datadir_from_argv).
                    If None, uses TD_DATA_DIR env var or defaults.
        default_output_filename: Default output filename (e.g., "td-otbr-cli-meshdiag-childtables.json").
                                If None, output_path will be None.
    
    Returns:
        CollectorRuntime with resolved paths for data directory, extaddr map, and output file.
    
    Examples:
        >>> runtime = resolve_collector_runtime(
        ...     datadir_arg="/custom/data",
        ...     default_output_filename="td-otbr-cli-meshdiag-childtables.json"
        ... )
        >>> extaddr_map = load_extaddr_map_or_empty(runtime.extaddr_map_path)
        >>> # ... collect data ...
        >>> save_json_atomic(data, runtime.output_path)
    """
    td_data_dir = resolve_data_dir(data_dir=datadir_arg)
    
    extaddr_map_path = data_file_path(
        EXTADDR_DEVICE_LABEL_MAP_FILENAME, td_data_dir
    )
    
    output_path = None
    if default_output_filename:
        output_path = data_file_path(default_output_filename, td_data_dir)
    
    return CollectorRuntime(
        td_data_dir=td_data_dir,
        extaddr_map_path=extaddr_map_path,
        output_path=output_path,
    )


def is_response_timeout_error(output: str) -> bool:
    """Detect ResponseTimeout error in OTBR CLI command output.
    
    Checks for the standard "Error <code>: ResponseTimeout" pattern that
    appears in meshdiag command output when a device fails to respond within
    the timeout window.
    
    Args:
        output: Raw text output from an OTBR CLI command (e.g., meshdiag childtable).
    
    Returns:
        True if output contains ResponseTimeout error, False otherwise.
    
    Examples:
        >>> output = "Error 6: ResponseTimeout\\nDone"
        >>> is_response_timeout_error(output)
        True
        
        >>> output = "rloc16:0x5000 ext-addr:1a7fbf0434e4f043\\nDone"
        >>> is_response_timeout_error(output)
        False
    """
    return re.search(r"Error\s+(\d+):\s+ResponseTimeout", output) is not None


def build_timeout_error_record(
    rloc16: str,
    device_label: str = "Unknown",
    result_table_key: str = "result_table",
    rloc_key: str = "rloc16",
) -> dict[str, Any]:
    """Build standardized error record for ResponseTimeout failures.
    
    Creates a consistent error envelope structure used across meshdiag collectors
    when a device fails to respond to diagnostic queries.
    
    Args:
        rloc16: The RLOC16 address of the device that timed out (e.g., "0x5000").
        device_label: Human-readable device label from extaddr map (default: "Unknown").
        result_table_key: Name of the empty result array field (e.g., "router_child_table").
        rloc_key: Name of the rloc field (e.g., "rloc16").
    
    Returns:
        Dictionary with error envelope containing:
        - rloc field with the provided rloc16 value
        - device_label field
        - empty result table array
        - count field set to 0 (if result_table_key doesn't contain "neighbor")
        - _error field with type "ResponseTimeout"
    
    Examples:
        >>> build_timeout_error_record(
        ...     rloc16="0x5000",
        ...     device_label="Kitchen Sensor",
        ...     result_table_key="router_child_table",
        ...     rloc_key="rloc16"
        ... )
        {
            "rloc16": "0x5000",
            "device_label": "Kitchen Sensor",
            "router_child_table": [],
            "router_child_table_count": 0,
            "_error": {"type": "ResponseTimeout"}
        }
    """
    error_record = {
        rloc_key: rloc16,
        "device_label": device_label,
        result_table_key: [],
        "_error": {"type": "ResponseTimeout"},
    }
    
    # Add count field for non-neighbor tables (childtable and childip6 have counts)
    # routerneighbortable has count too, so we include it for all
    count_key = f"{result_table_key}_count"
    error_record[count_key] = 0
    
    return error_record


def collect_per_router(
    router_table_data: list[dict],
    collect_fn: Callable[[str, dict | None, dict | None], dict],
    extaddr_map: dict | None = None,
    collection_name: str = "data",
    on_result: Callable[[list[dict], str, dict | None], None] | None = None,
) -> list[dict]:
    """Orchestrate per-router data collection with standardized logging.
    
    This function encapsulates the common pattern used by meshdiag collectors:
    - Extract RLOCs from router table
    - For each router, log collection start with device context
    - Call collector function with (rloc16, router, extaddr_map)
    - Collect results into a list
    
    Args:
        router_table_data: Router table from fetch_and_parse_router_table().
                          Should be list of dicts with "rloc16" and "extaddr" fields.
        collect_fn: Callback function that collects data for one router.
                   Signature: fn(rloc16: str, router: dict | None, extaddr_map: dict | None) -> dict
        extaddr_map: Optional mapping of extaddr -> device_label for logging and collection.
        collection_name: Name of data being collected (for logging), e.g. "meshdiag childip6".
    
    Returns:
        List of collection results (one dict per router in router_table_data).
    
    Examples:
        >>> def collect_child_table(rloc16, router, extaddr_map):
        ...     # Fetch and parse childtable for this router
        ...     return {"rloc16": rloc16, "children": [...]}
        
        >>> router_table = fetch_and_parse_router_table(extaddr_map)
        >>> results = collect_per_router(
        ...     router_table_data=router_table,
        ...     collect_fn=collect_child_table,
        ...     extaddr_map=extaddr_map,
        ...     collection_name="meshdiag childtable"
        ... )
    """
    # Extract RLOCs from router table (filter out entries without rloc16)
    router_rlocs = [
        router.get("rloc16") 
        for router in router_table_data 
        if router.get("rloc16")
    ]
    
    results = []
    
    for rloc16 in router_rlocs:
        # Find the full router record for this rloc16
        router = next(
            (r for r in router_table_data if r.get("rloc16") == rloc16),
            None
        )
        
        # Log collection start with device context
        if router:
            extaddr = router.get("extaddr")
            device_label = (
                extaddr_map.get(extaddr, "Unknown") 
                if extaddr_map and extaddr 
                else "Unknown"
            )
            logging.info(
                f"Fetching {collection_name} for router rloc16 {rloc16} "
                f"(Node: {device_label}, ExtAddr: {extaddr})..."
            )
        else:
            logging.info(
                f"Fetching {collection_name} for router rloc16 {rloc16} "
                "(Node: Unknown, ExtAddr: Unknown)..."
            )
        
        # Call collector function
        result = collect_fn(rloc16, router, extaddr_map)
        results.append(result)

        if on_result is not None:
            on_result(results, rloc16, router)
    
    return results


def parse_rss_metrics(line: str) -> dict[str, int] | None:
    """Parse RSS (Received Signal Strength) metrics from meshdiag telemetry line.
    
    Extracts average, last, and margin RSS values from lines like:
    "rss - ave:-20 last:-18 margin:80"
    
    Args:
        line: Telemetry line from meshdiag childtable or routerneighbortable output.
    
    Returns:
        Dictionary with keys: rss_ave, rss_last, rss_margin (all int values).
        Returns None if line doesn't match RSS pattern.
    
    Examples:
        >>> parse_rss_metrics("rss - ave:-20 last:-18 margin:80")
        {"rss_ave": -20, "rss_last": -18, "rss_margin": 80}
        
        >>> parse_rss_metrics("some other line")
        None
    """
    match = re.match(
        r"rss\s+-\s+ave:(-?\d+)\s+last:(-?\d+)\s+margin:(-?\d+)",
        line.strip(),
    )
    if match:
        return {
            "rss_ave": int(match.group(1)),
            "rss_last": int(match.group(2)),
            "rss_margin": int(match.group(3)),
        }
    return None


def parse_err_rate_metrics(line: str) -> dict[str, float] | None:
    """Parse error rate metrics from meshdiag telemetry line.
    
    Extracts frame and message error rate percentages from lines like:
    "err-rate - frame:0.00% msg:0.00%"
    
    Args:
        line: Telemetry line from meshdiag childtable or routerneighbortable output.
    
    Returns:
        Dictionary with keys: err_rate_frame_pct, err_rate_msg_pct (both float values).
        Returns None if line doesn't match error rate pattern.
    
    Examples:
        >>> parse_err_rate_metrics("err-rate - frame:0.50% msg:1.25%")
        {"err_rate_frame_pct": 0.5, "err_rate_msg_pct": 1.25}
        
        >>> parse_err_rate_metrics("some other line")
        None
    """
    match = re.match(
        r"err-rate\s+-\s+frame:([0-9]+(?:\.[0-9]+)?)%\s+msg:([0-9]+(?:\.[0-9]+)?)%",
        line.strip(),
    )
    if match:
        return {
            "err_rate_frame_pct": float(match.group(1)),
            "err_rate_msg_pct": float(match.group(2)),
        }
    return None


def parse_conn_time(line: str) -> str | None:
    """Parse connection time from meshdiag telemetry line.
    
    Extracts connection time value from lines like:
    "conn-time:00:12:34"
    
    Args:
        line: Telemetry line from meshdiag childtable or routerneighbortable output.
    
    Returns:
        Connection time string value (format varies, e.g., "00:12:34" or other formats).
        Returns None if line doesn't match conn-time pattern.
    
    Examples:
        >>> parse_conn_time("conn-time:00:12:34")
        "00:12:34"
        
        >>> parse_conn_time("conn-time:1d2h3m")
        "1d2h3m"
        
        >>> parse_conn_time("some other line")
        None
    """
    match = re.match(r"conn-time:(\S+)", line.strip())
    if match:
        return match.group(1)
    return None
