"""Read-only name preview from a bracketed HAP and OTBR capture."""

import ipaddress
import json
import math
import re
import time
from datetime import datetime
from pathlib import Path

from device_label import (
    _load_static_records_strict,
    _record_extaddr,
    normalize_valid_device_label,
    normalize_valid_extaddr,
    strip_dns_sd_service_suffix,
)
from td_const import OTBR_CLI_THREAD_NETWORK_INFO_FILENAME
from td_dataset_catalog import load_dataset_catalog, resolve_dataset, unique_json_object
from td_device_label_suggestions import _digest
from td_health_manifest import MANIFEST_PATH
from td_network_identity import network_id_from_ext_pan_id
from util_data import data_file_path, network_scope_path

MAX_AGE = 86400
MAX_SKEW = 300
SCOPE = "_hap._udp.local."
RECEIPT = "hap-capture.json"


def _read_json(raw: bytes):
    return json.loads(raw, object_pairs_hook=unique_json_object)


def _epoch(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("invalid capture timestamp")
    return float(value)


def _scope_epoch(value: object) -> float:
    if not isinstance(value, str):
        raise ValueError("missing network scope observation time")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("network scope observation time has no timezone")
    return parsed.timestamp()


def _capture(directory, network, now, otbr, hap):
    raw_receipt = (directory / RECEIPT).read_bytes()
    receipt = _read_json(raw_receipt)
    if not isinstance(receipt, dict) or receipt.get("schemaVersion") != 1:
        raise ValueError("invalid HAP capture receipt")
    stages = receipt.get("stages")
    names = (OTBR_CLI_THREAD_NETWORK_INFO_FILENAME, otbr, hap, OTBR_CLI_THREAD_NETWORK_INFO_FILENAME)
    order = ("network-start", "otbr", "hap", "network-end")
    if not isinstance(stages, dict) or set(stages) != set(order):
        raise ValueError("capture must include both snapshots and both network checks")
    fingerprints = {RECEIPT: _digest(raw_receipt)}
    checked = {}
    previous_end = now - MAX_AGE
    expected_pan = network.removeprefix("extpan:")
    for stage, name in zip(order, names):
        meta = stages[stage]
        if not isinstance(meta, dict) or type(meta.get("exit")) is not int or meta["exit"] != 0:
            raise ValueError(f"{stage} did not complete successfully")
        start, end = _epoch(meta.get("startedAt")), _epoch(meta.get("endedAt"))
        if not previous_end <= start < end <= now:
            raise ValueError(f"{stage} is stale, future, or out of order")
        previous_end = end
        path = data_file_path(name, directory / stage)
        raw = path.read_bytes()
        companion = network_scope_path(path)
        scope_raw = companion.read_bytes()
        scope = _read_json(scope_raw)
        digest, scope_digest = _digest(raw), _digest(scope_raw)
        if (meta.get("snapshotSha256") != digest or meta.get("scopeSha256") != scope_digest
                or not isinstance(scope, dict) or scope.get("snapshotSha256") != digest
                or scope.get("extPanId") != expected_pan
                or scope.get("provenance") != ("operator" if stage == "hap" else "observed")
                or not start <= _scope_epoch(scope.get("observedAt")) <= end):
            raise ValueError(f"{stage} snapshot or network scope did not verify")
        fingerprints[f"{stage}/{name}"] = digest
        fingerprints[f"{stage}/{companion.name}"] = scope_digest
        checked[stage] = (_read_json(raw), start, end)

    prefixes = []
    for stage in ("network-start", "network-end"):
        info, _, _ = checked[stage]
        if not isinstance(info, dict) or network_id_from_ext_pan_id(info.get("extPanId")) != network:
            raise ValueError(f"{stage} does not report the selected network")
        prefix = info.get("prefixOmr")
        if not isinstance(prefix, str) or "/" not in prefix:
            raise ValueError(f"{stage} has no verified OMR prefix")
        prefixes.append(ipaddress.IPv6Network(prefix))
    if prefixes[0] != prefixes[1] or prefixes[0].prefixlen != 64:
        raise ValueError("network checks must agree on a /64 OMR prefix")
    return checked, prefixes[0], fingerprints


def _address(value: object) -> ipaddress.IPv6Address:
    if not isinstance(value, str) or "%" in value:
        raise ValueError("invalid IPv6 address")
    address = ipaddress.IPv6Address(value)
    if address.is_link_local or address.is_multicast or address.is_unspecified:
        raise ValueError("not a unicast OMR address")
    return address


def _owners(rows, start, end, prefix):
    if not isinstance(rows, list) or not rows:
        raise ValueError("OTBR capture needs diagnostic rows")
    owners = {}
    found = False
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        history = row.get("tlvResponseHistory")
        if not isinstance(history, list):
            continue
        for j, reply in enumerate(history):
            if not isinstance(reply, dict):
                continue
            evidence = reply.get("addressListEvidence")
            if (not isinstance(evidence, dict) or reply.get("parseStatus") != "valid"
                    or reply.get("requestAssociation") not in ("query-id", "responder-target")
                    or not isinstance(reply.get("receivedTypeIds"), list)
                    or any(reply["receivedTypeIds"].count(tlv) != 1 for tlv in (0, 8))):
                continue
            try:
                address = normalize_valid_extaddr(evidence.get("extAddress"))
                captured = _epoch(evidence.get("capturedAtEpoch"))
                if (address != normalize_valid_extaddr(row.get("extAddress"))
                        or address in {"0" * 16, "f" * 16} or not start <= captured <= end
                        or not isinstance(evidence.get("ipv6Addresses"), list)):
                    continue
                ips = {_address(value) for value in evidence["ipv6Addresses"]
                       if isinstance(value, str) and ipaddress.IPv6Address(value) in prefix}
            except ValueError:
                continue
            found = True
            for ip in ips:
                owners.setdefault(ip, {}).setdefault(address, []).append({
                    "path": f"/{i}/tlvResponseHistory/{j}/addressListEvidence",
                    "capturedAtEpoch": captured,
                })
    if not found:
        raise ValueError("OTBR capture has no timestamped, correlated address-list replies; collect a new pair")
    return owners


def _hap_candidate(row, index, owners, start, end, prefix):
    result = {
        "id": _digest(f"mdns_hap:{index}".encode()), "extAddress": None, "deviceLabel": None,
        "state": "ineligible", "reason": "malformed-or-inactive-hap-record",
        "originalName": None, "categoryName": None, "omrIpv6Address": None,
        "evidence": {"hapPath": f"/{index}", "otbrReplies": []},
    }
    if not isinstance(row, dict) or row.get("scope") != SCOPE or row.get("event") not in ("add", "update"):
        return result
    info = row.get("serviceInfo")
    properties = info.get("properties") if isinstance(info, dict) else None
    ci = properties.get("ci") if isinstance(properties, dict) else None
    category = ci.get("categoryName") if isinstance(ci, dict) else None
    original = row.get("name")
    result["originalName"] = original if isinstance(original, str) else None
    try:
        name = normalize_valid_device_label(strip_dns_sd_service_suffix(original, SCOPE))
    except ValueError:
        return {**result, "reason": "invalid-hap-name"}
    try:
        category = normalize_valid_device_label(category)
    except ValueError:
        category = None
    try:
        label = normalize_valid_device_label(f"{name} - {category}" if category else name)
    except ValueError:
        return {**result, "reason": "invalid-hap-name-or-category"}
    result.update(categoryName=category, deviceLabel=label)
    try:
        ip = _address(row.get("omrIpv6Address"))
        if ip not in prefix:
            raise ValueError("outside verified OMR prefix")
    except ValueError:
        return {**result, "reason": "missing-or-invalid-omr-address"}
    result["omrIpv6Address"] = str(ip)
    try:
        captured = _epoch(row.get("capturedAtEpoch"))
        if not start <= captured <= end:
            raise ValueError("outside HAP stage")
    except ValueError:
        return {**result, "reason": "missing-or-invalid-hap-capture-time"}
    result["evidence"]["hapCapturedAtEpoch"] = captured
    matches = owners.get(ip, {})
    if len(matches) > 1:
        result["evidence"]["otbrReplies"] = [
            {"extAddress": addr, **reply} for addr, replies in sorted(matches.items()) for reply in replies
        ]
        return {**result, "state": "ambiguous", "reason": "multiple-otbr-addresses"}
    if not matches:
        return {**result, "reason": "unmatched-omr-address"}
    address, replies = next(iter(matches.items()))
    result["evidence"]["otbrReplies"] = [
        reply for reply in replies if abs(reply["capturedAtEpoch"] - captured) <= MAX_SKEW
    ]
    if not result["evidence"]["otbrReplies"]:
        return {**result, "reason": "capture-times-too-far-apart"}
    return {**result, "extAddress": address, "state": "resolved", "reason": None}


def _comparison_inputs(directory: Path, network: str, now: float | None):
    if not re.fullmatch(r"extpan:[0-9a-fA-F]{16}", network):
        raise ValueError("network must be extpan:<16 hexadecimal digits>")
    network = network_id_from_ext_pan_id(network.removeprefix("extpan:"))
    manifest = MANIFEST_PATH.read_bytes()
    catalog = load_dataset_catalog()
    if manifest != MANIFEST_PATH.read_bytes():
        raise ValueError("dataset catalog changed during preview")
    otbr, = resolve_dataset(catalog, "otbr_cli_diagnostics_fetch", "otbr-cli")["files"]
    hap, = resolve_dataset(catalog, "mdns_hap", "mdns")["files"]
    checked, prefix, fingerprints = _capture(directory, network, time.time() if now is None else now, otbr, hap)
    owners = _owners(*checked["otbr"], prefix)
    fingerprints["@dataset-manifest"] = _digest(manifest)
    return network, catalog, checked, prefix, owners, fingerprints


def _mapped_addresses(map_path: Path, fingerprints: dict) -> set[str]:
    records = _load_static_records_strict(map_path, allow_missing=True, fingerprints=fingerprints)
    mapped = {_record_extaddr(row) for row in records}
    mapped.update(normalize_valid_extaddr(addr) for row in records for addr in row.get("previousExtAddresses", []))
    return mapped


def preview_hap_names(directory: Path, map_path: Path, network: str, *, now: float | None = None) -> dict:
    network, _, checked, prefix, owners, fingerprints = _comparison_inputs(directory, network, now)
    rows, start, end = checked["hap"]
    if not isinstance(rows, list):
        raise ValueError("HAP capture must contain a JSON list")
    mapped = _mapped_addresses(map_path, fingerprints)
    candidates = [_hap_candidate(row, index, owners, start, end, prefix) for index, row in enumerate(rows)]
    labels = {}
    for candidate in candidates:
        if candidate["state"] == "resolved":
            labels.setdefault(candidate["extAddress"], set()).add(candidate["deviceLabel"])
    for candidate in candidates:
        if candidate["state"] != "resolved":
            continue
        address = candidate["extAddress"]
        if address in mapped:
            candidate.update(state="ineligible", reason="address-already-mapped")
        elif len(labels[address]) > 1:
            candidate.update(state="conflict", reason="distinct-hap-names-for-address")
    return {
        "schemaVersion": 1, "source": "mdns", "dataset": "mdns_hap", "networkId": network,
        "omrPrefix": str(prefix), "inputFingerprints": fingerprints, "candidates": candidates,
    }


def compare_eve_names(directory: Path, map_path: Path, network: str, *, now: float | None = None) -> dict:
    """Compare native Eve names without treating them as qualified suggestions."""
    network, catalog, _, prefix, owners, fingerprints = _comparison_inputs(directory, network, now)
    filename, = resolve_dataset(catalog, "eve_layout", "eve")["files"]
    raw = data_file_path(filename, map_path.parent).read_bytes()
    fingerprints[filename] = _digest(raw)
    layout = _read_json(raw)
    if not isinstance(layout, dict) or not isinstance(layout.get("nodes"), list):
        raise ValueError("native Eve layout must contain a nodes list")
    mapped = _mapped_addresses(map_path, fingerprints)
    return {
        "schemaVersion": 1, "mode": "manual-comparison", "source": "eve", "dataset": "eve_layout",
        "networkId": network, "eveNetworkProvenance": "operator-confirmed",
        "eveObservationTime": None, "omrPrefix": str(prefix),
        "inputFingerprints": fingerprints,
        "comparisons": [
            _compare_eve_node(node, i, owners, prefix, mapped)
            for i, node in enumerate(layout["nodes"])
        ],
    }


def _compare_eve_node(node, index, owners, prefix, mapped):
    row = {
        "evePath": f"/nodes/{index}", "eveName": None, "state": "ineligible",
        "reason": "missing-or-invalid-eve-name", "matches": [],
    }
    try:
        row["eveName"] = normalize_valid_device_label(node.get("name") if isinstance(node, dict) else None)
    except ValueError:
        return row
    ips = set()
    values = node.get("ip_addresses")
    for value in values if isinstance(values, list) else ():
        try:
            ip = _address(value)
        except ValueError:
            continue
        if ip in prefix:
            ips.add(ip)
    row["matches"] = [
        {"omrIpv6Address": str(ip), "extAddress": addr, "alreadyMapped": addr in mapped, "otbrReplies": replies}
        for ip in sorted(ips) for addr, replies in sorted(owners.get(ip, {}).items())
    ]
    count = len({match["extAddress"] for match in row["matches"]})
    if count > 1:
        row.update(state="ambiguous", reason="multiple-otbr-addresses")
    elif count == 1:
        row.update(state="unverified", reason="eve-observation-time-unknown")
    else:
        row["reason"] = "unmatched-omr-address" if ips else "missing-valid-omr-address"
    return row
