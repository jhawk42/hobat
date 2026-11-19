import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from td_const import (
    EXTADDR_DEVICE_LABEL_MAP_FILENAME,
    OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
    OTBR_CLI_THREAD_NETWORK_INFO_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
)
from td_device_label_sync import SyncEvidenceError, _object_spans, sync_eui
from util_data import network_scope_path


NETWORK = "extpan:1234567890abcdef"
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
ADDR = "1111111111111111"
OTHER = "2222222222222222"
EUI = "aaaaaaaaaaaaaaaa"


def _write_map(directory, rows):
    path = directory / EXTADDR_DEVICE_LABEL_MAP_FILENAME
    path.write_text(json.dumps(rows, indent=4), encoding="utf-8")
    return path


def _outcome(directory, pairs, *, item_created="2026-11-18T11:52:00Z",
             result_created=None, **changes):
    path = directory / OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME
    items = [{"id": f"d{index}", "extAddress": address, "eui": eui,
              "created": item_created}
             for index, (address, eui) in enumerate(pairs)]
    results = [{"deviceId": item["extAddress"], "diagnosticId": item["id"],
                "created": item_created if result_created is None else result_created,
                "status": "completed", "fallbackRecovered": False,
                "successfulTypes": ["extAddress", "eui"]} for item in items]
    outcome = {"items": items, "deviceResults": results, "clearedDiagnostics": True,
               "startedAt": "2026-11-18T11:50:00Z",
               "completedAt": "2026-11-18T11:55:00Z"}
    outcome.update(changes)
    path.write_text(json.dumps(outcome), encoding="utf-8")
    network_scope_path(path).write_text(json.dumps({
        "provenance": "observed", "extPanId": NETWORK[7:],
        "snapshotSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }), encoding="utf-8")
    return path


def _sync(directory, **kwargs):
    return sync_eui(directory, network_id=NETWORK, clock=lambda: NOW, **kwargs)


def _save_preview(directory, preview):
    path = directory / "reviewed.json"
    path.write_text(json.dumps(preview), encoding="utf-8")
    return path


def _capture(directory, label, rows, *, pan=NETWORK[7:]):
    directory.mkdir(exist_ok=True)
    (directory / "network-end").mkdir(exist_ok=True)
    hour = "10" if label == "before" else "11"
    meta = [f"label={label}", "capture_status=verified-network"]
    info = OTBR_CLI_THREAD_NETWORK_INFO_FILENAME
    for i, (stage, name, value) in enumerate((
        ("network_start", info, {"extPanId": pan}),
        ("fetch_all", OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME, rows),
        ("network_end", f"network-end/{info}", {"extPanId": pan}),
    )):
        start = f"2026-11-18T{hour}:0{i}:00Z"
        end = f"2026-11-18T{hour}:0{i}:59Z"
        meta.extend([f"{stage}_started_utc={start}", f"{stage}_ended_utc={end}", f"{stage}_exit=0"])
        path = directory / name
        path.write_text(json.dumps(value), encoding="utf-8")
        network_scope_path(path).write_text(json.dumps({
            "extPanId": pan, "provenance": "observed", "observedAt": end,
            "snapshotSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }), encoding="utf-8")
    (directory / "run.meta").write_text("\n".join(meta), encoding="utf-8")


def _answer(address, eui=EUI, **changes):
    return {"extAddress": address, "eui": eui, "tlvResponseHistory": [{
        "parseStatus": "valid", "finalAnswer": True, "requestAssociation": "query-id",
        "receivedTypeIds": [0, 23], "malformedTypeIds": [], "undecodedTypeIds": [],
        **changes,
    }]}


@pytest.fixture
def capture_pair(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    _capture(before, "before", [_answer(ADDR)])
    _capture(after, "after", [_answer(OTHER), {"type": "router", "children": []}])
    return {"before_capture": before, "after_capture": after}


def test_reviewed_rekey_preserves_history_and_requires_explicit_selection(tmp_path, capture_pair):
    primary = "3333333333333333"
    older = "4444444444444444"
    path = _write_map(tmp_path, [
        {"extaddr": primary, "device_label": "A", "comment": "Keep me", "eui": EUI,
         "previousExtAddresses": [older]},
        {"extAddress": "5555555555555555", "deviceLabel": "B", "unknown": {"a": 1}},
    ])
    original = path.read_bytes()
    preview = _sync(tmp_path, **capture_pair)
    candidate, = preview["candidates"]
    assert candidate["state"] == "rekey"
    assert candidate["extAddress"] == primary
    assert candidate["beforeExtAddresses"] == [ADDR]
    assert candidate["newExtAddress"] == OTHER
    assert candidate["previousExtAddresses"] == [primary, older]
    assert preview["captures"]["after"]["coverage"] == {"routerRows": 1, "childTables": 0}
    assert preview["retirementEligible"] is False
    saved = _save_preview(tmp_path, preview)
    with pytest.raises(ValueError, match="explicit --select"):
        _sync(tmp_path, **capture_pair, apply=True, from_preview=saved, all_eligible=True)
    assert path.read_bytes() == original
    assert not path.with_name(path.name + ".bak").exists()
    assert _sync(tmp_path, **capture_pair, apply=True, from_preview=saved,
                 select=[candidate["id"]])["applied"] == [candidate["id"]]
    assert path.with_name(path.name + ".bak").read_bytes() == original
    row, _ = json.loads(path.read_bytes())
    assert row["extAddress"] == row["extaddr"] == OTHER
    assert row["device_label"] == "A" and row["comment"] == "Keep me"
    assert row["previousExtAddresses"] == [primary, older]
    assert _object_spans(path.read_bytes())[1] == _object_spans(original)[1]
    assert _sync(tmp_path, **capture_pair)["candidates"][0]["state"] == "already-matching"
    with pytest.raises(SyncEvidenceError, match="no longer matches"):
        _sync(tmp_path, **capture_pair, apply=True, from_preview=saved, select=[candidate["id"]])


@pytest.mark.parametrize(("rows", "other_map", "reason"), [
    ([_answer(OTHER), {"type": "router", "children": [{"extAddress": ADDR}]}], [],
     "observed-address-overlap"),
    ([_answer(OTHER), _answer(OTHER, "bbbbbbbbbbbbbbbb")], [], "different-observed-eui"),
    ([_answer(OTHER)], [{"extAddress": "3333333333333333", "deviceLabel": "B",
                         "previousExtAddresses": [OTHER]}], "address-already-owned"),
])
def test_reviewed_rekey_rejects_overlap_and_ownership_conflicts(
    tmp_path, capture_pair, rows, other_map, reason,
):
    _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A", "eui": EUI}, *other_map])
    _capture(capture_pair["after_capture"], "after", rows)
    candidate, = _sync(tmp_path, **capture_pair)["candidates"]
    assert (candidate["state"], candidate["reason"]) == ("conflict", reason)


def test_reviewed_rekey_rejects_invalid_or_changed_capture(tmp_path, capture_pair):
    path = _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A", "eui": EUI}])
    with pytest.raises(ValueError, match="both capture"):
        _sync(tmp_path, before_capture=capture_pair["before_capture"])
    with pytest.raises(SyncEvidenceError, match="stale"):
        _sync(tmp_path, **capture_pair, max_evidence_age=300)
    preview = _sync(tmp_path, **capture_pair)
    saved = _save_preview(tmp_path, preview)
    before = path.read_bytes()
    meta = capture_pair["after_capture"] / "run.meta"
    meta.write_text(meta.read_text() + "\ncwd=ignored", encoding="utf-8")
    with pytest.raises(SyncEvidenceError, match="no longer matches"):
        _sync(tmp_path, **capture_pair, apply=True, from_preview=saved,
              select=[preview["candidates"][0]["id"]])
    _capture(capture_pair["after_capture"], "after", [_answer(OTHER)], pan="abcdefabcdefabcd")
    with pytest.raises(SyncEvidenceError, match="no matching observed network and digest"):
        _sync(tmp_path, **capture_pair)
    _capture(capture_pair["after_capture"], "after", [_answer(OTHER, receivedTypeIds=[23])])
    assert _sync(tmp_path, **capture_pair)["candidates"] == []
    assert path.read_bytes() == before


def test_reviewed_fill_saves_backup_and_preserves_untouched_row(tmp_path):
    path = _write_map(tmp_path, [
        {"extAddress": ADDR, "deviceLabel": "A"},
        {"extaddr": OTHER, "device_label": "B", "unknown": {"z": [1, 2]}},
    ])
    before = path.read_bytes()
    _outcome(tmp_path, [(ADDR, EUI)])
    preview = _sync(tmp_path)
    assert [c["state"] for c in preview["candidates"]] == ["fill-eui", "ineligible"]
    assert path.read_bytes() == before
    selected = preview["candidates"][0]["id"]
    result = _sync(tmp_path, apply=True, from_preview=_save_preview(tmp_path, preview),
                   select=[selected])
    assert result["applied"] == [selected]
    assert path.with_name(path.name + ".bak").read_bytes() == before
    rows = json.loads(path.read_bytes())
    assert rows[0]["eui"] == EUI
    assert rows[0]["lastUpdated"] == "2026-11-18T12:00:00Z"
    assert rows[1] == json.loads(before)[1]
    assert _object_spans(path.read_bytes())[1] == _object_spans(before)[1]


def test_unformatted_untouched_row_preserved_on_apply(tmp_path):
    path = tmp_path / EXTADDR_DEVICE_LABEL_MAP_FILENAME
    original = ('[{"extAddress":"1111111111111111","deviceLabel":"A"},'
                '{"extaddr":"2222222222222222","device_label":"B"}]').encode()
    path.write_bytes(original)
    _outcome(tmp_path, [(ADDR, EUI)])
    preview = _sync(tmp_path)
    result = _sync(tmp_path, apply=True, from_preview=_save_preview(tmp_path, preview),
                   all_eligible=True)
    assert len(result["applied"]) == 1
    assert _object_spans(path.read_bytes())[1] == _object_spans(original)[1]
    assert path.with_name(path.name + ".bak").read_bytes() == original


@pytest.mark.parametrize("changes", [
    {"startedAt": "2026-11-10T00:00:00Z"},
    {"completedAt": "2026-11-18T12:01:00Z"},
    {"startedAt": None},
    {"clearedDiagnostics": False},
])
def test_unbound_stale_or_future_capture_never_fills(tmp_path, changes):
    path = _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A"}])
    _outcome(tmp_path, [(ADDR, EUI)], **changes)
    preview = _sync(tmp_path)
    assert preview["candidates"][0]["state"] == "ineligible"
    before = path.read_bytes()
    result = _sync(tmp_path, apply=True, from_preview=_save_preview(tmp_path, preview),
                   all_eligible=True)
    assert result["applied"] == []
    assert path.read_bytes() == before


def test_same_capture_collision_is_conflict_not_succession(tmp_path):
    _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A", "eui": EUI}])
    _outcome(tmp_path, [(ADDR, EUI), (OTHER, EUI)])
    assert _sync(tmp_path)["candidates"][0]["state"] == "conflict"


@pytest.mark.parametrize(("item_created", "result_created"), [
    ("2026-11-18T11:49:59Z", None),
    ("2026-11-18T11:55:01Z", None),
    ("2026-11-18T11:52:00Z", "2026-11-18T11:52:01Z"),
    (None, None),
])
def test_rest_result_must_bind_to_its_collection_interval(tmp_path, item_created, result_created):
    path = _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A"}])
    before = path.read_bytes()
    _outcome(tmp_path, [(ADDR, EUI)], item_created=item_created, result_created=result_created)
    preview = _sync(tmp_path)
    assert preview["candidates"][0]["state"] == "ineligible"
    result = _sync(tmp_path, apply=True, from_preview=_save_preview(tmp_path, preview),
                   all_eligible=True)
    assert result["applied"] == []
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".bak").exists()


def test_different_stored_and_observed_eui_is_conflict(tmp_path):
    _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A", "eui": EUI}])
    _outcome(tmp_path, [(ADDR, "bbbbbbbbbbbbbbbb")])
    assert _sync(tmp_path)["candidates"][0]["reason"] == "different-observed-eui"


def test_saved_preview_rejects_changed_evidence_and_candidate_tampering(tmp_path):
    path = _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A"}])
    outcome = _outcome(tmp_path, [(ADDR, EUI)])
    preview = _sync(tmp_path)
    reviewed = _save_preview(tmp_path, preview)
    before = path.read_bytes()
    outcome.write_text(outcome.read_text() + " ", encoding="utf-8")
    with pytest.raises(SyncEvidenceError, match="no longer matches"):
        _sync(tmp_path, apply=True, from_preview=reviewed, all_eligible=True)
    assert path.read_bytes() == before
    _outcome(tmp_path, [(ADDR, EUI)])
    preview["candidates"][0]["eui"] = "bbbbbbbbbbbbbbbb"
    _save_preview(tmp_path, preview)
    with pytest.raises(SyncEvidenceError, match="no longer matches"):
        _sync(tmp_path, apply=True, from_preview=reviewed, all_eligible=True)
    assert path.read_bytes() == before


def test_unbound_scope_and_recovered_results_are_ineligible(tmp_path):
    _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A"}])
    path = _outcome(tmp_path, [(ADDR, EUI)], diagnosticRecovery={
        "devices": [{"extAddress": ADDR, "recoveryKind": "router-fallback"}]
    })
    assert _sync(tmp_path)["candidates"][0]["state"] == "ineligible"
    _outcome(tmp_path, [(ADDR, EUI)])
    network_scope_path(path).write_text("{}", encoding="utf-8")
    assert _sync(tmp_path)["candidates"][0]["state"] == "ineligible"


def test_missing_old_observation_and_touched_file_never_prove_succession(tmp_path):
    path = _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A", "eui": EUI}])
    outcome = _outcome(tmp_path, [(OTHER, EUI)])
    os.utime(outcome, None)
    preview = _sync(tmp_path)
    assert preview["candidates"][0]["reason"] == "unproven-succession"
    before = path.read_bytes()
    _sync(tmp_path, apply=True, from_preview=_save_preview(tmp_path, preview),
          all_eligible=True)
    assert path.read_bytes() == before


def test_scoped_cli_mtime_only_fills_and_retouch_invalidates_preview(tmp_path):
    _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A"}])
    cli = tmp_path / OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME
    cli.write_text(json.dumps([{"extAddress": ADDR, "eui": EUI}]), encoding="utf-8")
    network_scope_path(cli).write_text(json.dumps({
        "provenance": "observed", "extPanId": NETWORK[7:],
        "snapshotSha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
    }), encoding="utf-8")
    os.utime(cli, (NOW.timestamp() - 10,) * 2)
    preview = _sync(tmp_path)
    assert preview["candidates"][0]["state"] == "fill-eui"
    assert preview["candidates"][0]["evidenceSources"] == [cli.name]
    reviewed = _save_preview(tmp_path, preview)
    os.utime(cli, (NOW.timestamp() - 20,) * 2)
    with pytest.raises(SyncEvidenceError, match="no longer matches"):
        _sync(tmp_path, apply=True, from_preview=reviewed, all_eligible=True)
    os.utime(cli, (NOW.timestamp() + 1,) * 2)
    assert _sync(tmp_path)["candidates"][0]["state"] == "ineligible"


def test_cli_sync_preview_is_json_and_replayable(tmp_path, capsys):
    import td_cli

    path = _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A"}])
    argv = ["--datadir", str(tmp_path), "device-label", "--sync-eui", "--network", NETWORK]
    assert td_cli.main(argv) == 0
    reviewed = _save_preview(tmp_path, json.loads(capsys.readouterr().out))
    assert td_cli.main([*argv, "--apply", "--from-preview", str(reviewed), "--all-eligible"]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] == []
    assert not path.with_name(path.name + ".bak").exists()


def test_age_override_and_invalid_candidate_selection(tmp_path):
    _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A"}])
    _outcome(tmp_path, [(ADDR, EUI)], startedAt="2026-11-10T00:00:00Z")
    assert _sync(tmp_path)["candidates"][0]["state"] == "ineligible"
    preview = _sync(tmp_path, max_evidence_age=10 * 86400)
    assert preview["candidates"][0]["state"] == "fill-eui"
    with pytest.raises(SyncEvidenceError, match="unknown or ineligible"):
        _sync(tmp_path, max_evidence_age=10 * 86400, apply=True,
              from_preview=_save_preview(tmp_path, preview), select=["unknown"])


def test_backup_failure_prevents_map_write(tmp_path):
    path = _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A"}])
    original = path.read_bytes()
    _outcome(tmp_path, [(ADDR, EUI)])
    preview = _sync(tmp_path)
    path.with_name(path.name + ".bak").mkdir()
    with pytest.raises(OSError):
        _sync(tmp_path, apply=True, from_preview=_save_preview(tmp_path, preview),
              all_eligible=True)
    assert path.read_bytes() == original


def test_health_roster_is_unverified_and_does_not_authorize_apply(tmp_path, monkeypatch):
    from td_health_read import TDHealthReadService

    _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A"}])
    monkeypatch.setattr(TDHealthReadService, "__init__", lambda self, data_dir: None)
    monkeypatch.setattr(TDHealthReadService, "roster", lambda self, **kwargs: {
        "total": 1, "devices": [{"deviceId": "extaddr:" + ADDR, "fields": {
            "eui": {"value": EUI, "sourceObservedAt": "2026-11-18T11:00:00Z",
                    "observationId": "observation", "ageSeconds": 3600}
        }}],
    })
    preview = _sync(tmp_path, source="health-roster")
    candidate = preview["candidates"][0]
    assert candidate["reason"] == "unverified-observation"
    assert candidate["unverifiedEuis"] == [EUI]
    result = _sync(tmp_path, source="health-roster", apply=True,
                   from_preview=_save_preview(tmp_path, preview), all_eligible=True)
    assert result["applied"] == []


def test_cache_source_disagreement_blocks_otherwise_eligible_fill(tmp_path):
    _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A"}])
    _outcome(tmp_path, [(ADDR, EUI)])
    cli = tmp_path / OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME
    cli.write_text(json.dumps([{"extAddress": ADDR, "eui": "bbbbbbbbbbbbbbbb"}]),
                   encoding="utf-8")
    network_scope_path(cli).write_text(json.dumps({
        "provenance": "observed", "extPanId": NETWORK[7:],
        "snapshotSha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
    }), encoding="utf-8")
    candidate = _sync(tmp_path)["candidates"][0]
    assert candidate["state"] == "conflict"
    assert candidate["reason"] == "different-observed-eui"


def test_unqualified_eui_owner_blocks_fill(tmp_path):
    _write_map(tmp_path, [{"extAddress": ADDR, "deviceLabel": "A"}])
    _outcome(tmp_path, [(ADDR, EUI)])
    cli = tmp_path / OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME
    cli.write_text(json.dumps([{"extAddress": OTHER, "eui": EUI}]), encoding="utf-8")
    network_scope_path(cli).write_text(json.dumps({
        "provenance": "observed", "extPanId": NETWORK[7:],
        "snapshotSha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
    }), encoding="utf-8")
    assert _sync(tmp_path)["candidates"][0]["reason"] == "unproven-succession"


def test_selected_subset_and_noop_leave_other_rows_untouched(tmp_path):
    path = _write_map(tmp_path, [
        {"extAddress": ADDR, "deviceLabel": "A"},
        {"extAddress": OTHER, "deviceLabel": "B"},
    ])
    before = path.read_bytes()
    _outcome(tmp_path, [(ADDR, EUI), (OTHER, "bbbbbbbbbbbbbbbb")])
    preview = _sync(tmp_path)
    chosen = preview["candidates"][0]["id"]
    _sync(tmp_path, apply=True, from_preview=_save_preview(tmp_path, preview),
          select=[chosen])
    assert _object_spans(path.read_bytes())[1] == _object_spans(before)[1]
    backup = path.with_name(path.name + ".bak")
    backup_bytes = backup.read_bytes()
    after = path.read_bytes()
    preview = _sync(tmp_path)
    # Do not implicitly apply the remaining eligible candidate.
    with pytest.raises(SyncEvidenceError):
        _sync(tmp_path, apply=True, from_preview=_save_preview(tmp_path, preview),
              select=[chosen])
    assert path.read_bytes() == after
    assert backup.read_bytes() == backup_bytes
