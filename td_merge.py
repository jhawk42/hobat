#!/usr/bin/env python3
"""Merge multiple Thread topology JSON files into one detailed cache file."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any


PRIORITY_FIELDS = [
    "rloc16",
    "extaddr",
    "omrIpv6Address",
    "device_label",
    "name",
    "room",
    "ver",
    "type",
    "br",
    "mode.device",
    "thread_stack_version",
    "total_children",
    "total_links",
    "mac_counters.iftotalerrors_pct",
    "mac_counters.iftotaldiscards_pct",
    "mle_counters.partitionidchanges",
    "mle_counters.betterpartitionattachattempts",
    "mle_counters.parentchanges",
]

DEFAULT_INPUT_FILES = [
    "thread-router-table.json",
    "thread-meshdiag-topology.json",
    "thread-networkdiagnostic-topology.json",
    "thread-meshdiag-routerneighbortables.json",
    "thread-restapi-devices.json",
    "thread-restapi-diagnostics.json",
    "thread-eve-topology.json",
]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def lower_str(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


def derive_mode_device(record: dict[str, Any]) -> str:
    mode_device_raw = record.get("mode.device")
    if isinstance(mode_device_raw, str) and mode_device_raw.strip():
        value = mode_device_raw.strip().upper()
        if value in {"FTD", "MTD"}:
            return value

    mode = record.get("mode")
    if isinstance(mode, dict):
        mode_device = mode.get("device")
        if isinstance(mode_device, str) and mode_device.strip():
            value = mode_device.strip().upper()
            if value in {"FTD", "MTD"}:
                return value

        device_type_ftd = mode.get("deviceTypeFTD")
        if isinstance(device_type_ftd, bool):
            return "FTD" if device_type_ftd else "MTD"

        device_type = mode.get("device_type")
        if isinstance(device_type, (int, float)):
            return "FTD" if int(device_type) != 0 else "MTD"

    role = record.get("role")
    if isinstance(role, str):
        role_text = role.strip().lower()
        if role_text == "router":
            return "FTD"
        if role_text == "child":
            return "MTD"

    node_type = record.get("type")
    if isinstance(node_type, str):
        type_text = node_type.strip().lower()
        if type_text == "router":
            return "FTD"
        if "child" in type_text:
            return "MTD"

    return ""


def normalize_identifiers(record: dict[str, Any], omr_prefix: str) -> dict[str, Any]:
    extaddr = record.get("extaddr") or record.get("extAddress")
    if isinstance(extaddr, str):
        extaddr = extaddr.lower()
        record["extaddr"] = extaddr

    rloc16 = record.get("rloc16")
    if isinstance(rloc16, str):
        record["rloc16"] = rloc16.lower()

    omr_addr = record.get("omrIpv6Address")
    if isinstance(omr_addr, str):
        omr_addr = omr_addr.lower()

    if not omr_addr:
        ipv6_values = record.get("ipv6_addrs")
        if isinstance(ipv6_values, list):
            prefix = omr_prefix.lower()
            for ip_value in ipv6_values:
                if isinstance(ip_value, str) and ip_value.lower().startswith(prefix):
                    omr_addr = ip_value.lower()
                    break

    if omr_addr:
        record["omrIpv6Address"] = omr_addr

    mode_device = derive_mode_device(record)
    if mode_device:
        record["mode.device"] = mode_device
        mode = record.get("mode")
        if isinstance(mode, dict) and (not isinstance(mode.get("device"), str) or not mode.get("device", "").strip()):
            mode["device"] = mode_device

    return record


def load_extaddr_device_label_map(path: Path) -> dict[str, str]:
    data = load_json(path)
    mapping: dict[str, str] = {}

    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            extaddr = item.get("extaddr") or item.get("extAddress")
            label = item.get("device_label")
            if isinstance(extaddr, str) and isinstance(label, str) and label:
                mapping[extaddr.lower()] = label
        return mapping

    if isinstance(data, dict):
        for _, item in data.items():
            if not isinstance(item, dict):
                continue
            extaddr = item.get("extaddr") or item.get("extAddress")
            label = item.get("device_label")
            if isinstance(extaddr, str) and isinstance(label, str) and label:
                mapping[extaddr.lower()] = label

    return mapping


def extract_records(filename: str, data: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                records.append(deepcopy(item))
        return records

    if not isinstance(data, dict):
        return records

    if "data" in data and isinstance(data["data"], list):
        for item in data["data"]:
            if not isinstance(item, dict):
                continue
            merged_item = deepcopy(item)
            attrs = merged_item.get("attributes")
            if isinstance(attrs, dict):
                for k, v in attrs.items():
                    if k not in merged_item:
                        merged_item[k] = deepcopy(v)
            records.append(merged_item)
        return records

    # Eve topology is a dict keyed by rloc16-like strings.
    for map_key, item in data.items():
        if not isinstance(item, dict):
            continue
        copied = deepcopy(item)
        copied.setdefault("_map_key", map_key)
        records.append(copied)

    return records


def value_is_empty(value: Any) -> bool:
    if value is None:
        return True
    if value == "":
        return True
    if value == [] or value == {}:
        return True
    return False


def merge_lists(a_list: list[Any], b_list: list[Any]) -> list[Any]:
    seen: set[str] = set()
    merged: list[Any] = []

    for item in a_list + b_list:
        key = json.dumps(item, sort_keys=True, ensure_ascii=True)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)

    return merged


def deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    for key, value in incoming.items():
        if key not in base:
            base[key] = deepcopy(value)
            continue

        cur = base[key]
        if isinstance(cur, dict) and isinstance(value, dict):
            deep_merge(cur, value)
        elif isinstance(cur, list) and isinstance(value, list):
            base[key] = merge_lists(cur, value)
        elif value_is_empty(cur) and not value_is_empty(value):
            base[key] = deepcopy(value)
    return base


def nested_get(record: dict[str, Any], dotted_key: str) -> Any:
    parts = dotted_key.split(".")
    cur: Any = record
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def add_identifier(
    index: dict[str, int],
    key: str,
    node_id: int,
) -> None:
    if key:
        index[key] = node_id


def merge_nodes(
    target_id: int,
    source_id: int,
    nodes: dict[int, dict[str, Any]],
    by_rloc16: dict[str, int],
    by_extaddr: dict[str, int],
    by_omr: dict[str, int],
) -> int:
    if target_id == source_id:
        return target_id

    target = nodes[target_id]
    source = nodes[source_id]
    deep_merge(target, source)

    for lookup in (by_rloc16, by_extaddr, by_omr):
        for key, value in list(lookup.items()):
            if value == source_id:
                lookup[key] = target_id

    del nodes[source_id]
    return target_id


def build_merged_records(
    base_dir: Path,
    omr_prefix: str,
    input_files: list[str],
    extaddr_to_device_label: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    nodes: dict[int, dict[str, Any]] = {}
    by_rloc16: dict[str, int] = {}
    by_extaddr: dict[str, int] = {}
    by_omr: dict[str, int] = {}
    next_id = 1

    records_read_by_source: dict[str, int] = {}
    new_nodes_by_source: dict[str, int] = defaultdict(int)
    matched_existing_by_source: dict[str, int] = defaultdict(int)
    identity_collision_count = 0
    identity_collision_examples: list[dict[str, Any]] = []

    for filename in input_files:
        data = load_json(base_dir / filename)
        records = extract_records(filename, data)
        records_read_by_source[filename] = len(records)
        for raw_record in records:
            record = normalize_identifiers(raw_record, omr_prefix)

            record_extaddr = record.get("extaddr")
            if isinstance(record_extaddr, str):
                mapped_label = extaddr_to_device_label.get(record_extaddr.lower())
                if mapped_label and value_is_empty(record.get("device_label")):
                    record["device_label"] = mapped_label

            record.setdefault("_source_files", [])
            if filename not in record["_source_files"]:
                record["_source_files"].append(filename)

            rloc16 = lower_str(record.get("rloc16"))
            extaddr = lower_str(record.get("extaddr") or record.get("extAddress"))
            omr = lower_str(record.get("omrIpv6Address"))

            candidate_ids: set[int] = set()
            if isinstance(rloc16, str) and rloc16 in by_rloc16:
                candidate_ids.add(by_rloc16[rloc16])
            if isinstance(extaddr, str) and extaddr in by_extaddr:
                candidate_ids.add(by_extaddr[extaddr])
            if isinstance(omr, str) and omr in by_omr:
                candidate_ids.add(by_omr[omr])

            if not candidate_ids:
                node_id = next_id
                next_id += 1
                nodes[node_id] = deepcopy(record)
                new_nodes_by_source[filename] += 1
            else:
                matched_existing_by_source[filename] += 1
                if len(candidate_ids) > 1:
                    identity_collision_count += 1
                    if len(identity_collision_examples) < 10:
                        identity_collision_examples.append(
                            {
                                "source_file": filename,
                                "candidate_node_ids": sorted(candidate_ids),
                                "rloc16": rloc16,
                                "extaddr": extaddr,
                                "omrIpv6Address": omr,
                            }
                        )
                node_id = min(candidate_ids)
                for other_id in sorted(candidate_ids):
                    node_id = merge_nodes(
                        node_id,
                        other_id,
                        nodes,
                        by_rloc16,
                        by_extaddr,
                        by_omr,
                    )
                deep_merge(nodes[node_id], record)
                existing_sources = nodes[node_id].setdefault("_source_files", [])
                if filename not in existing_sources:
                    existing_sources.append(filename)

            # Re-read after merges in case node id changed.
            active = nodes[node_id]
            active_rloc16 = lower_str(active.get("rloc16"))
            active_extaddr = lower_str(active.get("extaddr") or active.get("extAddress"))
            active_omr = lower_str(active.get("omrIpv6Address"))

            if isinstance(active_rloc16, str):
                add_identifier(by_rloc16, active_rloc16, node_id)
            if isinstance(active_extaddr, str):
                active["extaddr"] = active_extaddr
                add_identifier(by_extaddr, active_extaddr, node_id)
                mapped_label = extaddr_to_device_label.get(active_extaddr)
                if mapped_label and value_is_empty(active.get("device_label")):
                    active["device_label"] = mapped_label
            if isinstance(active_omr, str):
                active["omrIpv6Address"] = active_omr
                add_identifier(by_omr, active_omr, node_id)

    merged_records: list[dict[str, Any]] = []
    for _, node in sorted(nodes.items(), key=lambda x: (x[1].get("rloc16") or "", x[0])):
        source_files = node.get("_source_files")
        if isinstance(source_files, list):
            # Compatibility alias for older consumers expecting `_sources`.
            node["_sources"] = list(source_files)

        ordered: dict[str, Any] = {}

        for key in PRIORITY_FIELDS:
            if "." in key:
                value = nested_get(node, key)
                if value is not None:
                    ordered[key] = value
            elif key in node:
                ordered[key] = node[key]

        for key, value in node.items():
            if key not in ordered:
                ordered[key] = value

        merged_records.append(ordered)

    merged_nodes_by_source: dict[str, int] = defaultdict(int)
    single_source_nodes_by_source: dict[str, int] = defaultdict(int)
    multi_source_nodes = 0

    for node in nodes.values():
        source_files = node.get("_source_files") or []
        if not isinstance(source_files, list):
            continue

        unique_sources = sorted({s for s in source_files if isinstance(s, str)})
        if len(unique_sources) > 1:
            multi_source_nodes += 1
        if len(unique_sources) == 1:
            single_source_nodes_by_source[unique_sources[0]] += 1
        for src in unique_sources:
            merged_nodes_by_source[src] += 1

    report = {
        "input_files": input_files,
        "records_read_by_source": records_read_by_source,
        "new_nodes_by_source": dict(sorted(new_nodes_by_source.items())),
        "matched_existing_by_source": dict(sorted(matched_existing_by_source.items())),
        "merged_nodes_by_source": dict(sorted(merged_nodes_by_source.items())),
        "single_source_nodes_by_source": dict(sorted(single_source_nodes_by_source.items())),
        "single_source_nodes_total": sum(single_source_nodes_by_source.values()),
        "multi_source_nodes_total": multi_source_nodes,
        "identity_collision_count": identity_collision_count,
        "identity_collision_examples": identity_collision_examples,
        "total_merged_nodes": len(merged_records),
    }

    return merged_records, report


def parse_file_list_args(values: list[str] | None) -> list[str]:
    if not values:
        return []

    result: list[str] = []
    for value in values:
        for token in value.split(","):
            candidate = token.strip()
            if candidate:
                result.append(candidate)
    return result


def resolve_input_files(
    default_files: list[str],
    include_files: list[str],
    exclude_files: list[str],
) -> list[str]:
    resolved: list[str] = list(default_files)

    for filename in include_files:
        if filename not in resolved:
            resolved.append(filename)

    excluded = set(exclude_files)
    resolved = [filename for filename in resolved if filename not in excluded]

    if not resolved:
        raise ValueError("No input files selected after applying include/exclude options.")

    return resolved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge Thread topology JSON sources into one detailed cache file.",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Directory containing input JSON files (default: current directory).",
    )
    parser.add_argument(
        "--dataset-file",
        default="thread-network-dataset-info.json",
        help="File that contains prefix_omr_ipv6addr_prefix.",
    )
    parser.add_argument(
        "--output",
        default="threadcache-merged-detailed-topology.json",
        help="Output merged JSON file path.",
    )
    parser.add_argument(
        "--include-files",
        nargs="*",
        default=[],
        help=(
            "Extra JSON source files to include. "
            "Supports space-separated and/or comma-separated file names."
        ),
    )
    parser.add_argument(
        "--exclude-files",
        nargs="*",
        default=[],
        help=(
            "JSON source files to exclude from defaults. "
            "Supports space-separated and/or comma-separated file names."
        ),
    )
    parser.add_argument(
        "--report-file",
        default="",
        help="Optional path to write merge validation report JSON.",
    )
    parser.add_argument(
        "--extaddr-map-file",
        default="threadstatic-extaddr.json",
        help="Reference file used only for extaddr to device_label lookup.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir)
    include_files = parse_file_list_args(args.include_files)
    exclude_files = parse_file_list_args(args.exclude_files)

    input_files = resolve_input_files(DEFAULT_INPUT_FILES, include_files, exclude_files)

    for filename in input_files:
        if not (base_dir / filename).is_file():
            raise FileNotFoundError(f"Input file not found: {base_dir / filename}")

    extaddr_map_path = base_dir / args.extaddr_map_file
    if not extaddr_map_path.is_file():
        raise FileNotFoundError(f"Reference file not found: {extaddr_map_path}")
    extaddr_to_device_label = load_extaddr_device_label_map(extaddr_map_path)

    dataset = load_json(base_dir / args.dataset_file)
    omr_prefix = dataset.get("prefix_omr_ipv6addr_prefix", "")
    if not isinstance(omr_prefix, str) or not omr_prefix:
        raise ValueError(
            "Missing or invalid prefix_omr_ipv6addr_prefix in dataset file."
        )

    merged_records, report = build_merged_records(
        base_dir,
        omr_prefix,
        input_files,
        extaddr_to_device_label,
    )
    report["reference_extaddr_map_file"] = args.extaddr_map_file
    report["reference_extaddr_map_entries"] = len(extaddr_to_device_label)

    output_path = base_dir / args.output
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(merged_records, f, indent=2)
        f.write("\n")

    if args.report_file:
        report_path = base_dir / args.report_file
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
        print(f"Wrote merge report to {report_path}")

    print(f"Wrote {len(merged_records)} merged records to {output_path}")
    print(
        "Validation summary: "
        f"multi_source_nodes={report['multi_source_nodes_total']}, "
        f"single_source_nodes={report['single_source_nodes_total']}, "
        f"identity_collisions={report['identity_collision_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())