#!/usr/bin/env python3
"""Merge multiple Thread topology JSON files into one detailed cache file."""

from __future__ import annotations

import argparse
import json
import logging

from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any, Sequence

from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME, TD_DATA_DIR_ARG_HELP
from util_data import resolve_data_dir, save_json_atomic


PRIORITY_FIELDS = [
    "rloc16",
    "extaddr",
    "omr_ipv6_addr",
    "device_label",
    "name",
    "room",
    "ver",
    "thread_version",
    "thread_stack_version",
    "type",
    "br",
    "mode.device",
    "total_children",
    "total_links",
    "mac_counters.ifinerrors_pct",
    "mac_counters.ifouterrors_pct",
    "mac_counters.ifindiscards_pct",
    "mac_counters.ifoutdiscards_pct",
    "mle_counters.partitionidchanges",
    "mle_counters.betterpartitionattachattempts",
    "mle_counters.parentchanges",
]

# Canonical merge identity model used by merge/index matching logic.
MERGE_STRATEGIES = {
    "by_identity": "by-identity",
}

MERGE_IDENTITY_FIELDS = {
    "rloc16": "rloc16",
    "extaddr_aliases": ("extaddr", "extAddress", "Extended MAC"),
    "omr_ipv6_addr": "omr_ipv6_addr",
}

DEFAULT_INPUT_FILES = [
    "td-otbr-cli-router-table.json",
    "td-otbr-cli-meshdiag-topology.json",
    "td-otbr-cli-networkdiag-topology-poll.json",
    "td-otbr-cli-networkdiag-topology-multicast-network.json",
    "td-otbr-cli-meshdiag-router-neighbortables.json",
    "td-otbr-restapi-devices.json",
    "td-otbr-restapi-diagnostics.json",
    "td-eve-topology.json",
]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_identifier_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def first_normalized_identifier(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = normalize_identifier_text(record.get(key))
        if value:
            return value
    return ""


def get_canonical_extaddr(record: dict[str, Any]) -> str:
    return first_normalized_identifier(record, MERGE_IDENTITY_FIELDS["extaddr_aliases"])


def get_canonical_omr(record: dict[str, Any]) -> str:
    return normalize_identifier_text(
        record.get(MERGE_IDENTITY_FIELDS["omr_ipv6_addr"])
    )


def normalize_record_aliases(record: dict[str, Any]) -> dict[str, Any]:
    extaddr = get_canonical_extaddr(record)
    omr_addr = get_canonical_omr(record)

    if extaddr:
        record["extaddr"] = extaddr
    if omr_addr:
        record["omr_ipv6_addr"] = omr_addr

    return record


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
        if role_text in ("router", "border router"):
            return "FTD"
        if role_text == "child":
            return "MTD"

    node_type = record.get("type")
    if isinstance(node_type, str):
        type_text = node_type.strip().lower()
        if type_text in ("router", "border router"):
            return "FTD"
        if "child" in type_text:
            return "MTD"

    return ""


def normalize_identifiers(record: dict[str, Any], omr_prefix: str) -> dict[str, Any]:
    normalize_record_aliases(record)

    rloc16 = record.get("rloc16")
    if isinstance(rloc16, str):
        record["rloc16"] = rloc16.lower()

    omr_addr = get_canonical_omr(record)

    if not omr_addr:
        ipv6_values = record.get("ipv6_addrs")
        if isinstance(ipv6_values, list):
            prefix = omr_prefix.lower()
            for ip_value in ipv6_values:
                if isinstance(ip_value, str) and ip_value.lower().startswith(prefix):
                    omr_addr = ip_value.lower()
                    break

    if omr_addr:
        record["omr_ipv6_addr"] = omr_addr

    mode_device = derive_mode_device(record)
    if mode_device:
        record["mode.device"] = mode_device
        mode = record.get("mode")
        if isinstance(mode, dict) and (
            not isinstance(mode.get("device"), str)
            or not mode.get("device", "").strip()
        ):
            mode["device"] = mode_device

    return record


def load_extaddr_device_label_map(path: Path) -> dict[str, str]:
    data = load_json(path)
    mapping: dict[str, str] = {}

    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            normalized_item = normalize_record_aliases(item)
            extaddr = get_canonical_extaddr(normalized_item)
            label = item.get("device_label")
            if extaddr and isinstance(label, str) and label:
                mapping[extaddr] = label
        return mapping

    if isinstance(data, dict):
        for _, item in data.items():
            if not isinstance(item, dict):
                continue
            normalized_item = normalize_record_aliases(item)
            extaddr = get_canonical_extaddr(normalized_item)
            label = item.get("device_label")
            if extaddr and isinstance(label, str) and label:
                mapping[extaddr] = label

    return mapping


def extract_records(filename: str, data: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                records.append(normalize_record_aliases(deepcopy(item)))
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
            records.append(normalize_record_aliases(merged_item))
        return records

    # Eve topology is a dict keyed by rloc16-like strings.
    for map_key, item in data.items():
        if not isinstance(item, dict):
            continue
        copied = deepcopy(item)
        copied.setdefault("_map_key", map_key)
        records.append(normalize_record_aliases(copied))

    return records


def value_is_empty(value: Any) -> bool:
    if value is None:
        return True
    if value == "":
        return True
    if value == [] or value == {}:
        return True
    return False


def merge_unique_strings(existing: list[Any], incoming: list[Any]) -> list[str]:
    merged: list[str] = []
    for value in existing + incoming:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def values_equivalent(left: Any, right: Any) -> bool:
    if left == right:
        return True
    try:
        return json.dumps(left, sort_keys=True, ensure_ascii=True) == json.dumps(
            right, sort_keys=True, ensure_ascii=True
        )
    except TypeError:
        return False


def append_merge_conflict(
    base: dict[str, Any], path: str, cur_val: Any, new_value: Any
) -> None:
    if not path:
        return

    conflicts = base.setdefault("_merge_conflicts", [])
    if not isinstance(conflicts, list):
        conflicts = []
        base["_merge_conflicts"] = conflicts

    if len(conflicts) >= 20:
        return

    current_text = json.dumps(
        cur_val, sort_keys=True, ensure_ascii=True, default=str
    )
    incoming_text = json.dumps(
        new_value, sort_keys=True, ensure_ascii=True, default=str
    )

    for entry in conflicts:
        if not isinstance(entry, dict):
            continue
        if (
            entry.get("path") == path
            and entry.get("current") == current_text
            and entry.get("incoming") == incoming_text
        ):
            return

    conflicts.append(
        {
            "path": path,
            "current": current_text,
            "incoming": incoming_text,
        }
    )


def merge_lists(left: list[Any], right: list[Any]) -> list[Any]:
    seen: set[str] = set()
    merged: list[Any] = []

    for item in left + right:
        key = json.dumps(item, sort_keys=True, ensure_ascii=True)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)

    return merged


def deep_merge(
    base: dict[str, Any],
    incoming: dict[str, Any],
    path_prefix: str = "",
    conflict_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if conflict_target is None:
        conflict_target = base

    for key, value in incoming.items():
        if key == "_merge_conflicts":
            existing_conflicts = conflict_target.setdefault(
                "_merge_conflicts", [])
            if isinstance(existing_conflicts, list) and isinstance(value, list):
                for conflict in value:
                    if len(existing_conflicts) >= 20:
                        break
                    if conflict not in existing_conflicts:
                        existing_conflicts.append(deepcopy(conflict))
            continue

        if key == "_source_files":
            existing_sources = (
                base.get("_source_files")
                if isinstance(base.get("_source_files"), list)
                else []
            )
            incoming_sources = value if isinstance(value, list) else []
            base["_source_files"] = merge_unique_strings(
                existing_sources, incoming_sources
            )
            continue

        current_path = f"{path_prefix}.{key}" if path_prefix else key
        if key not in base:
            base[key] = deepcopy(value)
            continue

        cur = base[key]
        if isinstance(cur, dict) and isinstance(value, dict):
            deep_merge(cur, value, current_path, conflict_target)
        elif isinstance(cur, list) and isinstance(value, list):
            base[key] = merge_lists(cur, value)
        elif value_is_empty(cur) and not value_is_empty(value):
            base[key] = deepcopy(value)
        elif (
            not value_is_empty(cur)
            and not value_is_empty(value)
            and not values_equivalent(cur, value)
        ):
            append_merge_conflict(conflict_target, current_path, cur, value)
    return base


def nested_get(record: dict[str, Any], dotted_key: str) -> Any:
    parts = dotted_key.split(".")
    cur: Any = record
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def collect_merge_identity_values(record: dict[str, Any]) -> dict[str, str]:
    identities: dict[str, str] = {}

    rloc16 = normalize_identifier_text(
        record.get(MERGE_IDENTITY_FIELDS["rloc16"]))
    if rloc16:
        identities["rloc16"] = rloc16

    extaddr = get_canonical_extaddr(record)
    if extaddr:
        identities["extaddr"] = extaddr

    omr = get_canonical_omr(record)
    if omr:
        identities["omr_ipv6_addr"] = omr

    return identities


def find_candidate_node_ids(
    identity_values: dict[str, str],
    by_rloc16: dict[str, int],
    by_extaddr: dict[str, int],
    by_omr: dict[str, int],
) -> set[int]:
    candidate_ids: set[int] = set()

    rloc16 = identity_values.get("rloc16")
    extaddr = identity_values.get("extaddr")
    omr = identity_values.get("omr_ipv6_addr")

    if isinstance(rloc16, str) and rloc16 in by_rloc16:
        candidate_ids.add(by_rloc16[rloc16])
    if isinstance(extaddr, str) and extaddr in by_extaddr:
        candidate_ids.add(by_extaddr[extaddr])
    if isinstance(omr, str) and omr in by_omr:
        candidate_ids.add(by_omr[omr])

    return candidate_ids


def index_node_identity_values(
    node: dict[str, Any],
    node_id: int,
    by_rloc16: dict[str, int],
    by_extaddr: dict[str, int],
    by_omr: dict[str, int],
) -> dict[str, str]:
    identity_values = collect_merge_identity_values(node)

    rloc16 = identity_values.get("rloc16")
    extaddr = identity_values.get("extaddr")
    omr = identity_values.get("omr_ipv6_addr")

    if isinstance(rloc16, str):
        node["rloc16"] = rloc16
        add_identifier(by_rloc16, rloc16, node_id)
    if isinstance(extaddr, str):
        node["extaddr"] = extaddr
        add_identifier(by_extaddr, extaddr, node_id)
    if isinstance(omr, str):
        node["omr_ipv6_addr"] = omr
        add_identifier(by_omr, omr, node_id)

    return identity_values


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
    device_label_map: dict[str, str],
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
                mapped_label = device_label_map.get(
                    record_extaddr.lower())
                if mapped_label and value_is_empty(record.get("device_label")):
                    record["device_label"] = mapped_label

            record.setdefault("_source_files", [])
            if filename not in record["_source_files"]:
                record["_source_files"].append(filename)

            identity_values = collect_merge_identity_values(record)
            rloc16 = identity_values.get("rloc16")
            extaddr = identity_values.get("extaddr")
            omr = identity_values.get("omr_ipv6_addr")

            candidate_ids = find_candidate_node_ids(
                identity_values, by_rloc16, by_extaddr, by_omr
            )

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
                                "omr_ipv6_addr": omr,
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
                existing_sources = nodes[node_id].setdefault(
                    "_source_files", [])
                if filename not in existing_sources:
                    existing_sources.append(filename)

            # Re-read after merges in case node id changed.
            active = nodes[node_id]
            active_identity_values = index_node_identity_values(
                active, node_id, by_rloc16, by_extaddr, by_omr
            )
            active_extaddr = active_identity_values.get("extaddr")
            if isinstance(active_extaddr, str):
                mapped_label = device_label_map.get(active_extaddr)
                if mapped_label and value_is_empty(active.get("device_label")):
                    active["device_label"] = mapped_label

    merged_records: list[dict[str, Any]] = []
    for _, node in sorted(
        nodes.items(), key=lambda x: (x[1].get("rloc16") or "", x[0])
    ):
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

        unique_sources = sorted(
            {s for s in source_files if isinstance(s, str)})
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
        "single_source_nodes_by_source": dict(
            sorted(single_source_nodes_by_source.items())
        ),
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
        raise ValueError(
            "No input files selected after applying include/exclude options."
        )

    return resolved


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge Thread topology JSON sources into one detailed cache file.",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Directory containing input JSON files (default: current directory).",
    )
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    parser.add_argument(
        "--dataset-file",
        default="td-otbr-cli-thread-network-info.json",
        help="File that contains prefix_omr_ipv6addr_prefix.",
    )
    parser.add_argument(
        "--output",
        default="td-merged-topology-all.json",
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
        default=EXTADDR_DEVICE_LABEL_MAP_FILENAME,
        help="Reference file used only for extaddr to device_label lookup.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    args = parse_args(argv)
    td_data_dir = resolve_data_dir(data_dir=args.datadir)
    base_dir = td_data_dir if args.base_dir == "." else Path(args.base_dir)
    include_files = parse_file_list_args(args.include_files)
    exclude_files = parse_file_list_args(args.exclude_files)

    input_files = resolve_input_files(
        DEFAULT_INPUT_FILES, include_files, exclude_files)

    for filename in input_files:
        if not (base_dir / filename).is_file():
            raise FileNotFoundError(
                f"Input file not found: {base_dir / filename}")

    extaddr_map_path = base_dir / args.extaddr_map_file
    if not extaddr_map_path.is_file():
        raise FileNotFoundError(
            f"Reference file not found: {extaddr_map_path}")
    device_label_map = load_extaddr_device_label_map(extaddr_map_path)

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
        device_label_map,
    )
    report["reference_extaddr_map_file"] = args.extaddr_map_file
    report["reference_extaddr_map_entries"] = len(device_label_map)

    output_path = base_dir / args.output
    save_json_atomic(merged_records, output_path, indent=2, add_trailing_newline=True)

    if args.report_file:
        report_path = base_dir / args.report_file
        save_json_atomic(report, report_path, indent=2, add_trailing_newline=True)
        logging.info(f"Wrote merge report to {report_path}")

    logging.info(
        f"Wrote {len(merged_records)} merged records to {output_path}")
    logging.info(
        "Validation summary: "
        f"multi_source_nodes={report['multi_source_nodes_total']}, "
        f"single_source_nodes={report['single_source_nodes_total']}, "
        f"identity_collisions={report['identity_collision_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
