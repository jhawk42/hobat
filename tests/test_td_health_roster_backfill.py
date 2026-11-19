import json
import sqlite3
from contextlib import closing
from datetime import datetime

import pytest

import td_cli
import td_health_roster_backfill as backfill
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_read import TDHealthReadService
from td_health_sqlite import SQLiteHealthStore
from td_health_sweep_evidence import digest_bytes


NETWORK = "extpan:1234567890abcdef"
EXTS = ("1111111111111111", "2222222222222222")
EUIS = ("aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb")
START = "2026-01-01T00:00:00+00:00"
END = "2026-01-01T00:00:01+00:00"


def _fact(connection, ext, key, value, network=NETWORK):
    connection.execute(
        """INSERT INTO device_last_known
           (network_id, device_id, field_key, value_json, value_class, observation_id,
            source_observed_at, confidence, conflict_state)
           VALUES (?, ?, ?, ?, ?, 'fixture', ?, 'high', 'none')""",
        (network, "extaddr:" + ext, key, json.dumps(value),
         "alias" if key == "eui" else "identity", START),
    )


@pytest.fixture
def case(tmp_path):
    database = tmp_path / HOBAT_DATABASE_FILENAME
    store = SQLiteHealthStore(database)
    with closing(store._connect()) as db, db:
        for ext in EXTS:
            db.execute("INSERT INTO devices VALUES (?, ?)", ("extaddr:" + ext, ext))
            _fact(db, ext, "extAddress", ext)
    evidence = tmp_path / "sweep"
    evidence.mkdir()
    container = "a" * 64
    instance = f"{container} {START}"
    prefix = "fd00::ff:fe00:"

    def save(name, value):
        raw = json.dumps(value).encode()
        (evidence / name).write_bytes(raw)
        return digest_bytes(raw)

    targets = ["0400", "0800"]
    inputs = save("inputs.json", {
        "captureId": "fixture", "otbrInstance": instance, "networkId": NETWORK,
        "startedAt": START, "rloc16": targets, "requestedTlvs": [0, 1, 2, 23], "prefix": prefix,
        "merged": [{"extAddress": ext, "rloc16": rloc, "_networkInstance": NETWORK}
                   for ext, rloc in zip(EXTS, targets)],
    })
    windows = []
    for rloc, start, end in zip(targets, (START, END), (START, END)):
        names = {}
        names[f"{rloc}.json"] = save(f"{rloc}.json", {
            "requestedRloc16": rloc, "startedAt": start, "finishedAt": end,
            "command": ["docker", "exec", "-it", container, "/usr/sbin/ot-ctl",
                        "networkdiagnostic", "get", prefix + rloc, "0", "1", "2", "23"],
        })
        # Both replies appear in the second command's window.
        replies = "".join(
            f"DIAG_GET.rsp/ans from {prefix}{target}: 0008{ext}0102{target}1708{eui}\n"
            for target, ext, eui in zip(targets, EXTS, EUIS)
        ) if rloc == "0800" else ""
        streams = {f"{rloc}.stdout.txt": replies, f"{rloc}.stderr.txt": ""}
        for side in ("before", "after"):
            for kind, value in (("extpanid", NETWORK[7:]), ("mleid", "fd00::1234")):
                streams[f"{rloc}.{side}.{kind}.stdout.txt"] = f"{value}\r\nDone\r\n"
                streams[f"{rloc}.{side}.{kind}.stderr.txt"] = ""
        for name, value in streams.items():
            raw = value.encode()
            (evidence / name).write_bytes(raw)
            names[name] = digest_bytes(raw)
        windows.append({
            "requestedRloc16": rloc, "startedAt": start, "finishedAt": end,
            "before": {"startedAt": start, "finishedAt": start},
            "after": {"startedAt": end, "finishedAt": end}, "sha256": names,
        })
    receipt = save("network-receipt.json", {
        "version": 1, "captureId": "fixture", "networkId": NETWORK, "otbrInstance": instance,
        "inputsSha256": inputs, "windows": windows,
    })
    save("collection-complete.json", {
        "queryCount": 2, "finishedAt": END, "networkReceiptSha256": receipt,
    })
    return store, evidence


def _run(case, **kwargs):
    store, evidence = case
    return backfill.backfill_roster_eui(store.path, network=NETWORK, evidence_dir=evidence, **kwargs)


def test_preview_apply_backup_and_normal_roster_read(case, capsys, tmp_path):
    store, evidence = case
    with closing(store._connect()) as db, db:
        db.execute("DROP TABLE roster_eui_aliases")
        db.execute("DELETE FROM schema_migrations WHERE version=11")
    service = TDHealthReadService(tmp_path)
    read_time = datetime.fromisoformat(END)
    before = service.roster(network_id=NETWORK, read_time=read_time)
    args = ["--datadir", str(tmp_path), "health", "backfill-roster-eui",
            "--network", NETWORK, "--evidence-dir", str(evidence)]
    assert td_cli.main(args) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["counts"] == {"fill-eui": 2}
    assert preview["candidates"][0]["evidence"][0]["startedAt"] == END
    assert not (tmp_path / ".migration-backups").exists()
    saved = tmp_path / "preview.json"
    saved.write_text(json.dumps(preview))
    assert td_cli.main([*args, "--apply", "--from-preview", str(saved), "--all-eligible"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert len(applied["applied"]) == 2
    with closing(sqlite3.connect(applied["backupPath"])) as db:
        assert db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 10
    after = service.roster(network_id=NETWORK, read_time=read_time)
    for a, b, eui in zip(after["devices"], before["devices"], EUIS):
        assert a["fields"]["eui"]["value"] == eui
        assert a["fields"]["eui"]["sourceObservedAt"] is None
        assert a["euiAlias"]["provenance"]["replies"][0]["startedAt"] == END
        for key in ("lastObservedAt", "lastEndpointPresenceAt", "ageSeconds", "fieldCounts", "rosterState"):
            assert a[key] == b[key]
    with closing(store._connect()) as db, db:
        _fact(db, EXTS[0], "eui", "cccccccccccccccc")
    detail = service.roster_device(network_id=NETWORK, device_id="extaddr:" + EXTS[0])
    assert detail["fields"]["eui"]["value"] == "cccccccccccccccc"
    assert detail["euiAlias"]["state"] == "different-admitted-eui"
    repeat = _run(case)
    assert repeat["counts"] == {"already-matching": 1, "conflict": 1}
    assert _run(case, reviewed=repeat, all_eligible=True)["backupPath"] is None


def test_stale_roster_and_tampered_capture_refuse_apply(case):
    store, evidence = case
    preview = _run(case)
    with closing(store._connect()) as db, db:
        _fact(db, EXTS[0], "eui", EUIS[1])
    assert _run(case)["counts"] == {"conflict": 2}
    with pytest.raises(ValueError, match="Saved preview"):
        _run(case, reviewed=preview, all_eligible=True)
    (evidence / "0800.stdout.txt").write_text("changed")
    with pytest.raises(ValueError, match="window digest mismatch"):
        _run(case)
    assert not (store.path.parent / ".migration-backups").exists()


def test_backup_and_batch_failure_leave_no_aliases(case, monkeypatch):
    store, _ = case
    preview = _run(case)
    with monkeypatch.context() as mock:
        def fail(*args):
            raise OSError("Backup failed")
        mock.setattr(backfill, "_create_migration_backup", fail)
        with pytest.raises(OSError, match="Backup failed"):
            _run(case, reviewed=preview, all_eligible=True)
    with closing(store._connect()) as db, db:
        db.execute(f"""CREATE TRIGGER reject_second BEFORE INSERT ON roster_eui_aliases
            WHEN NEW.eui='{EUIS[1]}' BEGIN SELECT RAISE(ABORT, 'rejected'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="rejected"):
        _run(case, reviewed=preview, all_eligible=True)
    with closing(store._connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM roster_eui_aliases").fetchone()[0] == 0
