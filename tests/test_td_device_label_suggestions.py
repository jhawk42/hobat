import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ha_matter_ws_extractor import extract_nodes_info
from ha_matter_ws_snapshots import build_device_snapshot
from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME, HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME
from td_device_label_suggestions import preview_ha_matter_names
from util_data import network_scope_path

PAN = "123456789012abcd"
NETWORK = f"extpan:{PAN}"
A = "1234567890120001"
B = "1234567890120002"
C = "1234567890120003"
D = "1234567890120004"
ROOT = Path(__file__).resolve().parents[1]


def _inventory(tmp_path, rows, **scope_overrides):
    snapshot = tmp_path / HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME
    raw = json.dumps(rows).encode()
    snapshot.write_bytes(raw)
    scope = {
        "snapshotSha256": hashlib.sha256(raw).hexdigest(),
        "provenance": "observed",
        "extPanId": PAN,
        "sources": [snapshot.name],
        **scope_overrides,
    }
    network_scope_path(snapshot).write_text(json.dumps(scope), encoding="utf-8")
    return snapshot


def _row(address, label, pan=PAN):
    return {
        "thread": {"extAddress": address, "extendedPanId": pan},
        "matter": {"rawNodeLabel": label, "deviceLabel": "Display name"},
    }


def test_preview_preserves_raw_root_node_label_through_inventory(tmp_path):
    nodes = [
        {"node_id": 1, "name": "Fallback", "attributes": {
            "0/40/5": " Office Sensor ", "0/53/63": int(A, 16), "0/53/4": int(PAN, 16),
        }},
        {"node_id": 2, "name": "Fallback", "attributes": {
            "1/40/5": "Other endpoint", "0/53/63": int(B, 16), "0/53/4": int(PAN, 16),
        }},
    ]
    rows = build_device_snapshot(extract_nodes_info(nodes))
    assert rows[1]["matter"]["deviceLabel"] == "Fallback"
    _inventory(tmp_path, rows)
    result = preview_ha_matter_names(tmp_path, tmp_path / EXTADDR_DEVICE_LABEL_MAP_FILENAME, NETWORK)
    candidates = {row["extAddress"]: row for row in result["candidates"]}
    assert candidates[A]["state"] == "resolved"
    assert candidates[A]["deviceLabel"] == "Office Sensor"
    assert candidates[A]["evidence"][0]["label"] == "/0/matter/rawNodeLabel"
    assert candidates[B]["reason"] == "missing-or-invalid-raw-node-label"
    assert candidates[B]["deviceLabel"] is None


def test_cli_preview_is_deterministic_and_does_not_modify_inputs(tmp_path):
    _inventory(tmp_path, [
        _row(A, "Lamp"), _row(A.upper(), " Lamp "), _row(B, "Hall"), _row(B, "Entry"),
        _row(C, "New name"), _row(D, "Old address"), _row("0" * 16, "No address"),
        _row("1234567890120005", "Other network", "ffff000000000001"),
        {"extAddress": "1234567890120006", "matter": {"rawNodeLabel": "No Thread identity"}},
        _row("1234567890120007", None),
    ])
    label_map = tmp_path / EXTADDR_DEVICE_LABEL_MAP_FILENAME
    label_map.write_text(json.dumps([{
        "extAddress": C, "deviceLabel": "Unknown", "previousExtAddresses": [D],
    }]), encoding="utf-8")
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    command = [sys.executable, "-m", "td_cli", "--datadir", str(tmp_path), "device-label",
               "--suggest-ha-matter", "--network", NETWORK]
    opts = {"cwd": ROOT, "env": {"PYTHONPATH": str(ROOT / "src")}, "capture_output": True, "text": True}
    first = subprocess.run(command, check=True, **opts)
    second = subprocess.run(command, check=True, **opts)
    denied = subprocess.run([*command, "--apply"], **opts)
    assert denied.returncode == 2 and "explicit --select IDs" in denied.stderr
    assert first.stdout == second.stdout
    report = json.loads(first.stdout)
    assert report["schemaVersion"] == 1
    assert report["inputFingerprints"]["map"] == hashlib.sha256(label_map.read_bytes()).hexdigest()
    candidates = report["candidates"]
    assert [r["extAddress"] for r in candidates if r["state"] == "resolved"] == [A]
    assert len(next(r for r in candidates if r["extAddress"] == A)["evidence"]) == 2
    assert {r["deviceLabel"] for r in candidates if r["state"] == "conflict"} == {"Hall", "Entry"}
    assert {r["extAddress"] for r in candidates if r["reason"] == "address-already-mapped"} == {C, D}
    assert len({r["id"] for r in candidates}) == len(candidates)
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}


@pytest.mark.parametrize("override", [
    {"provenance": "operator"}, {"snapshotSha256": "stale"}, {"extPanId": "abcd000000001234"},
    {"sources": ["topology.json"]},
])
def test_preview_rejects_unverified_inventory_scope(tmp_path, override):
    _inventory(tmp_path, [_row(A, "Lamp")], **override)
    with pytest.raises(ValueError, match="digest-bound observed scope"):
        preview_ha_matter_names(tmp_path, tmp_path / EXTADDR_DEVICE_LABEL_MAP_FILENAME, NETWORK)


def test_ha_matter_apply_is_selected_additive_and_rejects_replay(tmp_path):
    _inventory(tmp_path, [_row(A, "Lamp"), _row(B, "Hall"), _row(C, "Overwrite")])
    label_map = tmp_path / EXTADDR_DEVICE_LABEL_MAP_FILENAME
    original_row = f'{{"extAddress":"{C}", "deviceLabel":"Saved", "comment":"Keep"}}'
    original = f"[{original_row}]\n"
    label_map.write_text(original)
    command = [sys.executable, "-m", "td_cli", "--datadir", str(tmp_path), "device-label",
               "--suggest-ha-matter", "--network", NETWORK]
    opts = {"cwd": ROOT, "env": {"PYTHONPATH": str(ROOT / "src")}, "capture_output": True, "text": True}
    out = subprocess.run(command, check=True, **opts)
    preview_file = tmp_path / "preview.json"
    preview_file.write_text(out.stdout)
    candidates = {c["extAddress"]: c["id"] for c in json.loads(out.stdout)["candidates"]}
    apply = [*command, "--apply", "--from-preview", str(preview_file), "--select", candidates[A]]
    denied = subprocess.run([*apply, "--select", candidates[C]], **opts)
    assert denied.returncode == 5 and "unknown or ineligible" in denied.stderr
    assert label_map.read_text() == original
    backup = label_map.with_suffix(".json.bak")
    assert not backup.exists()
    result = json.loads(subprocess.run(apply, check=True, **opts).stdout)
    assert [row["extAddress"] for row in result["inserted"]] == [A]
    after = label_map.read_text()
    assert original_row in after
    assert [row["extAddress"] for row in json.loads(after)] == [A, C]
    assert backup.read_text() == original
    replay = subprocess.run(apply, **opts)
    assert replay.returncode == 5 and "no longer matches" in replay.stderr
    assert label_map.read_text() == after and backup.read_text() == original
