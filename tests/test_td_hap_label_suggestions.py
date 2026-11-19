import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from td_const import (
    EXTADDR_DEVICE_LABEL_MAP_FILENAME,
    MDNS_SCOPES_HAP_FILENAME,
    OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
    OTBR_CLI_THREAD_NETWORK_INFO_FILENAME,
)
from td_hap_label_suggestions import compare_eve_names, preview_hap_names
from util_data import network_scope_path

PAN = "123456789012abcd"
NETWORK = f"extpan:{PAN}"
A = "1234567890120001"
B = "1234567890120002"
ROOT = Path(__file__).resolve().parents[1]


def _reply(addr, seen, *ips):
    return {"extAddress": addr, "tlvResponseHistory": [{
        "parseStatus": "valid", "requestAssociation": "query-id",
        "receivedTypeIds": [0, 8],
        "addressListEvidence": {"extAddress": addr, "capturedAtEpoch": seen, "ipv6Addresses": list(ips)},
    }]}


def _hap(name, ip, seen, category=None):
    return {
        "name": f"{name}._hap._udp.local.", "scope": "_hap._udp.local.", "event": "update",
        "capturedAtEpoch": seen, "omrIpv6Address": ip,
        "serviceInfo": {"properties": {"ci": {"categoryName": category}}},
    }


def _pair(directory, now, otbr, hap, *, end_pan=PAN):
    stages = {}
    for stage, name, data, pan, start, end in (
        ("network-start", OTBR_CLI_THREAD_NETWORK_INFO_FILENAME,
         {"extPanId": PAN, "prefixOmr": "fd42::/64"}, PAN, now - 700, now - 690),
        ("otbr", OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME, otbr, PAN, now - 690, now - 30),
        ("hap", MDNS_SCOPES_HAP_FILENAME, hap, PAN, now - 30, now - 20),
        ("network-end", OTBR_CLI_THREAD_NETWORK_INFO_FILENAME,
         {"extPanId": end_pan, "prefixOmr": "fd42::/64"}, end_pan, now - 20, now - 10),
    ):
        dest = directory / stage / name
        dest.parent.mkdir()
        raw = json.dumps(data).encode()
        dest.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        scope = json.dumps({
            "snapshotSha256": digest, "extPanId": pan,
            "provenance": "operator" if stage == "hap" else "observed",
            "observedAt": datetime.fromtimestamp(end - 1, timezone.utc).isoformat(),
        }).encode()
        network_scope_path(dest).write_bytes(scope)
        stages[stage] = {
            "exit": 0, "startedAt": start, "endedAt": end,
            "snapshotSha256": digest, "scopeSha256": hashlib.sha256(scope).hexdigest(),
        }
    (directory / "hap-capture.json").write_text(json.dumps({"schemaVersion": 1, "stages": stages}))


def test_hap_preview_checks_unique_reply_match_and_time_limits(tmp_path):
    now = time.time()
    _pair(tmp_path, now, [
        _reply(A, now - 325, "fd42::1", "fd42::2"), _reply(A, now - 326, "fd42::3"),
        _reply(B, now - 40, "fd42::2", "fd42::4"),
    ], [
        _hap("Hall", "fd42:0:0:0:0:0:0:1", now - 25, "Sensors"),
        _hap("Shared", "fd42::2", now - 25), _hap("Too old", "fd42::3", now - 25),
        _hap("Missing time", "fd42::4", None), _hap("No match", "fd42::9", now - 25),
        _hap("Outside prefix", "fd43::4", now - 25),
    ])
    label_map = tmp_path / EXTADDR_DEVICE_LABEL_MAP_FILENAME
    result = preview_hap_names(tmp_path, label_map, NETWORK, now=now)
    assert [r["reason"] for r in result["candidates"]] == [
        None, "multiple-otbr-addresses", "capture-times-too-far-apart",
        "missing-or-invalid-hap-capture-time", "unmatched-omr-address", "missing-or-invalid-omr-address",
    ]
    [hit] = [r for r in result["candidates"] if r["state"] == "resolved"]
    assert (hit["extAddress"], hit["deviceLabel"], hit["categoryName"]) == (A, "Hall - Sensors", "Sensors")
    assert hit["originalName"] == "Hall._hap._udp.local."
    assert not label_map.exists()
    with pytest.raises(ValueError, match="stale"):
        preview_hap_names(tmp_path, label_map, NETWORK, now=now + 86400)


def test_hap_cli_reports_conflicts_and_protects_history_without_writing(tmp_path):
    now = time.time()
    _pair(tmp_path, now, [_reply(A, now - 100, "fd42::1"), _reply(B, now - 40, "fd42::2")], [
        _hap("Lamp", "fd42::1", now - 25), _hap("Hall", "fd42::1", now - 25),
        _hap("History", "fd42::2", now - 25),
    ])
    label_map = tmp_path / EXTADDR_DEVICE_LABEL_MAP_FILENAME
    label_map.write_text(json.dumps([{"extAddress": "1234567890120003", "deviceLabel": "Old",
                                      "previousExtAddresses": [B]}]))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    cmd = [sys.executable, "-m", "td_cli", "--datadir", str(tmp_path), "device-label",
           f"--suggest-hap={tmp_path}", "--network", NETWORK]
    opts = {"cwd": ROOT, "env": {"PYTHONPATH": str(ROOT / "src")}, "capture_output": True, "text": True}
    out = subprocess.run(cmd, check=True, **opts)
    denied = subprocess.run([*cmd, "--apply"], **opts)
    assert denied.returncode == 2 and "explicit --select IDs" in denied.stderr
    rows = json.loads(out.stdout)["candidates"]
    assert [r["state"] for r in rows] == ["conflict", "conflict", "ineligible"]
    assert rows[-1]["reason"] == "address-already-mapped"
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("failure", ["network", "tampered", "legacy"])
def test_hap_preview_rejects_unverified_pairs(tmp_path, failure):
    now = time.time()
    reply = _reply(A, now - 40, "fd42::1")
    if failure == "legacy":
        del reply["tlvResponseHistory"][0]["addressListEvidence"]
    _pair(tmp_path, now, [reply], [_hap("Lamp", "fd42::1", now - 25)],
          end_pan="abcd000000001234" if failure == "network" else PAN)
    if failure == "tampered":
        (tmp_path / "hap" / MDNS_SCOPES_HAP_FILENAME).write_text("[]")
    with pytest.raises(ValueError, match="did not verify|no timestamped"):
        preview_hap_names(tmp_path, tmp_path / EXTADDR_DEVICE_LABEL_MAP_FILENAME, NETWORK, now=now)


def test_eve_comparison_never_promotes_matches_to_suggestions(tmp_path):
    now = time.time()
    _pair(tmp_path, now, [
        _reply(A, now - 40, "fd42::1", "fd42::2"), _reply(B, now - 40, "fd42::2"),
    ], [])
    layout = tmp_path / "Eve Thread Network Layout.evethreadlayout"
    layout.write_text(json.dumps({"nodes": [
        {"name": "Hall", "ip_addresses": ["fd42:0:0:0::1", "fd42::1"]},
        {"name": "Shared", "ip_addresses": ["fd42::2"]},
        {"name": "RLOC only", "rloc16": "0x0400", "ip_addresses": ["fe80::1"]},
        {"name": "Unknown owner", "ip_addresses": ["fd42::3"]},
    ]}))
    label_map = tmp_path / EXTADDR_DEVICE_LABEL_MAP_FILENAME
    label_map.write_text(json.dumps([{"extAddress": B, "deviceLabel": "Saved",
                                      "previousExtAddresses": [A]}]))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    cmd = [sys.executable, "-m", "td_cli", "--datadir", str(tmp_path), "device-label",
           "--compare-eve", str(tmp_path), "--network", NETWORK]
    opts = {"cwd": ROOT, "env": {"PYTHONPATH": str(ROOT / "src")}, "capture_output": True, "text": True}
    out = subprocess.run(cmd, check=True, **opts)
    denied = subprocess.run([*cmd, "--apply"], **opts)
    assert denied.returncode == 2 and "preview-only" in denied.stderr
    report = json.loads(out.stdout)
    assert report["mode"] == "manual-comparison" and "candidates" not in report
    assert report["eveObservationTime"] is None and report["eveNetworkProvenance"] == "operator-confirmed"
    unique, ambiguous, missing, unmatched = report["comparisons"]
    assert unique["state"] == "unverified" and unique["reason"] == "eve-observation-time-unknown"
    [hit] = unique["matches"]
    assert hit["extAddress"] == A and hit["alreadyMapped"] and hit["omrIpv6Address"] == "fd42::1"
    assert ambiguous["state"] == "ambiguous"
    assert {match["extAddress"] for match in ambiguous["matches"]} == {A, B}
    assert missing["reason"] == "missing-valid-omr-address"
    assert unmatched["reason"] == "unmatched-omr-address"
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="stale"):
        compare_eve_names(tmp_path, label_map, NETWORK, now=now + 86400)


def test_hap_apply_rechecks_evidence_and_creates_map_once(tmp_path):
    now = time.time()
    _pair(tmp_path, now, [_reply(A, now - 40, "fd42::1"), _reply(B, now - 40, "fd42::2")], [
        _hap("Lamp", "fd42::1", now - 25), _hap("Hall", "fd42::2", now - 25),
    ])
    label_map = tmp_path / EXTADDR_DEVICE_LABEL_MAP_FILENAME
    cmd = [sys.executable, "-m", "td_cli", "--datadir", str(tmp_path), "device-label",
           "--suggest-hap", str(tmp_path), "--network", NETWORK]
    opts = {"cwd": ROOT, "env": {"PYTHONPATH": str(ROOT / "src")}, "capture_output": True, "text": True}
    out = subprocess.run(cmd, check=True, **opts)
    preview = tmp_path / "preview.json"
    preview.write_text(out.stdout)
    a, b = [row["id"] for row in json.loads(out.stdout)["candidates"]]
    apply = [*cmd, "--apply", "--from-preview", str(preview), "--select", b, "--select", a]
    receipt = tmp_path / "hap-capture.json"
    original = receipt.read_bytes()
    receipt.write_bytes(original + b"\n")
    rejected = subprocess.run(apply, **opts)
    assert rejected.returncode == 5 and "no longer matches" in rejected.stderr
    assert not label_map.exists()
    receipt.write_bytes(original)
    report = json.loads(subprocess.run(apply, check=True, **opts).stdout)
    assert report["applied"] == sorted([a, b])
    assert [(r["extAddress"], r["deviceLabel"]) for r in json.loads(label_map.read_text())] == [
        (A, "Lamp"), (B, "Hall"),
    ]
    assert not label_map.with_suffix(".json.bak").exists()
