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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from extaddr_device_label_map import load_extaddr_device_label_map
from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME
from util_data import data_file_path, resolve_data_dir


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
    
    if not os.path.exists(path):
        logger.warning(
            f"Extended address mapping file not found: {path}. "
            "Continuing with Unknown labels."
        )
        return {}
    
    logger.info(
        f"Loading extended address to device label mapping from {path}..."
    )
    return load_extaddr_device_label_map(path)


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
        rloc_key: Name of the rloc field (e.g., "parent_rloc16" or "rloc16").
    
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
        ...     rloc_key="parent_rloc16"
        ... )
        {
            "parent_rloc16": "0x5000",
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
