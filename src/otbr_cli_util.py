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
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from extaddr_device_label_map import load_extaddr_device_label_map
from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME
from util_data import (
    CollectionWriteOutcome,
    data_file_path,
    load_optional_input,
    resolve_data_dir,
)
import util_network


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


def classify_meshdiag_table_response(output: str) -> tuple[str, str | None]:
    """Classify an OTBR meshdiag response without treating an error as a table."""
    if not isinstance(output, str):
        return "protocol-error", "ProtocolError"
    error_match = re.search(r"Error\s+\d+:\s*([A-Za-z][A-Za-z0-9_-]*)", output)
    if error_match:
        error_type = error_match.group(1)
        return ("timeout", error_type) if error_type == "ResponseTimeout" else ("error", error_type)
    if not output.rstrip().endswith("Done"):
        return "protocol-error", "ProtocolError"
    return "success", None


def canonical_router_rloc16(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(str(value), 0)
    except (TypeError, ValueError):
        return None
    if not 0 <= parsed < 0xFFFE or not util_network.is_router(parsed):
        return None
    return f"0x{parsed:04x}"


def canonical_extaddr(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace(":", "").replace("-", "")
    if not re.fullmatch(r"[0-9a-f]{16}", normalized):
        return None
    return normalized


def build_meshdiag_target_identity(router: dict | None, rloc16: object, device_label: str) -> dict[str, str]:
    identity: dict[str, str] = {"device_label": device_label, "address_kind": "mesh-local-rloc"}
    canonical_rloc16 = canonical_router_rloc16(rloc16)
    if canonical_rloc16 is not None:
        identity["rloc16"] = canonical_rloc16
    extaddr = canonical_extaddr(router.get("extaddr")) if isinstance(router, dict) else None
    if extaddr is not None:
        identity["extaddr"] = extaddr
    return identity


def _meshdiag_ping_evidence(status: str = "not-attempted") -> dict[str, object]:
    return {"status": status, "attempted": False, "elapsed_ms": 0}


def add_meshdiag_table_evidence(
    record: dict[str, Any],
    *,
    command: str,
    table_status: str,
    error_type: str | None,
    elapsed_ms: int,
    router: dict | None,
    device_label: str,
    ping: Callable[[Any], Any] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Attach independent table and bounded reachability evidence to one result."""
    record["table_attempt"] = {
        "command": command,
        "status": table_status,
        "elapsed_ms": elapsed_ms,
        "error_type": error_type,
    }
    record["target_identity"] = build_meshdiag_target_identity(
        router, record.get("rloc16"), device_label
    )
    if table_status == "success":
        record["ping"] = _meshdiag_ping_evidence()
        return record

    record["_error"] = {"type": error_type or "ProtocolError"}
    if table_status == "protocol-error":
        record["ping"] = _meshdiag_ping_evidence()
        return record

    canonical_rloc16 = canonical_router_rloc16(record.get("rloc16"))
    if canonical_rloc16 is None:
        record["ping"] = _meshdiag_ping_evidence("unavailable")
        return record
    try:
        meshlocal_prefix = util_network.fetch_meshlocal_prefix()
        target = util_network.build_rloc16_ipv6_address(
            util_network.build_rloc_ipv6_address_prefix(meshlocal_prefix),
            canonical_rloc16[2:],
        )
        from td_device_actions import normalize_unicast_address

        normalized_target, family = normalize_unicast_address(target)
        if family != "ipv6":
            raise ValueError("derived target is not IPv6")
    except Exception as exc:
        logging.info(
            "meshdiag fallback ping unavailable router=%s reason=%s",
            canonical_rloc16,
            type(exc).__name__,
        )
        record["ping"] = _meshdiag_ping_evidence("unavailable")
        return record

    from otbr_cli_device import PING_DEFAULT_INTERVAL, PING_DEFAULT_TIMEOUT, PingRequest, ping_device

    started_at = monotonic()
    try:
        result = (ping or ping_device)(
            PingRequest(
                target=normalized_target,
                count=2,
                interval_seconds=PING_DEFAULT_INTERVAL,
                timeout_seconds=PING_DEFAULT_TIMEOUT,
            )
        )
        if result.error_category == "none" and result.received > 0:
            ping_status = "reply"
        elif result.error_category == "timeout":
            ping_status = "no-reply"
        elif "unsupported" in result.output.lower():
            ping_status = "unsupported"
        else:
            ping_status = "error"
        record["ping"] = {
            "status": ping_status,
            "attempted": True,
            "elapsed_ms": max(0, round((monotonic() - started_at) * 1000)),
            "target": normalized_target,
            "sent": result.sent,
            "received": result.received,
            "loss": result.loss,
            "round_trip_summary_ms": result.round_trip_summary_ms,
            "timeout_seconds": result.timeout_seconds,
            "error_category": result.error_category,
        }
    except Exception as exc:
        logging.warning(
            "meshdiag fallback ping failed router=%s error_type=%s",
            canonical_rloc16,
            type(exc).__name__,
        )
        record["ping"] = {
            "status": "error",
            "attempted": True,
            "elapsed_ms": max(0, round((monotonic() - started_at) * 1000)),
            "target": normalized_target,
            "error_category": "local-dispatch",
        }
    return record


def build_meshdiag_ambiguous_result(
    *,
    rloc16: str,
    router: dict,
    device_label: str,
    result_table_key: str,
    command: str,
) -> dict[str, Any]:
    record = build_timeout_error_record(
        rloc16=rloc16,
        device_label=device_label,
        result_table_key=result_table_key,
    )
    record["_error"] = {"type": "AmbiguousTarget"}
    record["table_attempt"] = {
        "command": command,
        "status": "error",
        "elapsed_ms": 0,
        "error_type": "AmbiguousTarget",
    }
    record["target_identity"] = build_meshdiag_target_identity(router, rloc16, device_label)
    record["ping"] = _meshdiag_ping_evidence("unavailable")
    return record


def meshdiag_collection_outcome(results: list[dict[str, Any]]) -> CollectionWriteOutcome:
    if any("table_attempt" not in record for record in results):
        has_failures = any("_error" in record for record in results)
        return (
            CollectionWriteOutcome.partial(
                has_usable_data=any("_error" not in record for record in results)
            )
            if has_failures
            else CollectionWriteOutcome.complete()
        )
    successful = [
        record for record in results
        if record.get("table_attempt", {}).get("status") == "success"
    ]
    if len(successful) == len(results):
        return CollectionWriteOutcome.complete()
    return CollectionWriteOutcome.partial(has_usable_data=bool(successful))


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
    ambiguous_result_fn: Callable[[str, dict], dict] | None = None,
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
    results = []
    routers_by_rloc: dict[str, dict] = {}
    ambiguous_rlocs: set[str] = set()
    for router in router_table_data:
        if not isinstance(router, dict):
            continue
        rloc16 = canonical_router_rloc16(router.get("rloc16"))
        if rloc16 is None:
            continue
        existing = routers_by_rloc.get(rloc16)
        if existing is None:
            routers_by_rloc[rloc16] = router
        elif canonical_extaddr(existing.get("extaddr")) != canonical_extaddr(router.get("extaddr")):
            ambiguous_rlocs.add(rloc16)

    for rloc16, router in routers_by_rloc.items():
        if rloc16 in ambiguous_rlocs:
            logging.warning("Skipping ambiguous %s router identity for %s", rloc16, collection_name)
            if ambiguous_result_fn is None:
                continue
            result = ambiguous_result_fn(rloc16, router)
            results.append(result)
            if on_result is not None:
                on_result(results, rloc16, router)
            continue
        
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
