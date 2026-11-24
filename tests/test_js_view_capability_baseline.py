"""Snapshot projected dashboard filters over cached datasets."""

import json
from pathlib import Path

import pytest

from td_dataset_catalog import load_dataset_catalog


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/view_capability_baseline.json"
ROLE_AUTHORITY_FILTERS = {
    "border-routers",
    "main-routers",
    "reed-devices",
    "routers-with-children",
    "routers-without-children",
}


def _legacy_baseline():
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for entry in load_dataset_catalog()["datasets"]:
        if "unified" in entry and all(
            (ROOT / "data" / filename).is_file() for filename in entry["files"]
        ):
            expected[entry["value"]] = expected["otbr_restapi_topology"]

    return expected


@pytest.mark.requires_data_dir
def test_cached_view_capabilities_cover_catalog_and_preserve_shape(node_json) -> None:
    expected = _legacy_baseline()
    actual = node_json(
        "tests/js/run-view-capability-snapshot.mjs", "data",
        f"--datasets={','.join(expected)}", "--shape-only", timeout=60,
    )
    assert set(actual) == set(expected)
    for dataset, snapshot in actual.items():
        assert set(snapshot) == set(expected[dataset]), dataset
        assert set(snapshot["flags"]) == set(expected[dataset]["flags"]), dataset
        assert set(snapshot["offered"]) == set(expected[dataset]["offered"]), dataset
        assert set(snapshot["diagnosticMatches"]) == set(expected[dataset]["diagnosticMatches"]), dataset
        offered = snapshot["offered"]
        combinations = {
            f"{node}|{link}|{diagnostic}"
            for node in offered["nodeModes"]
            for link in offered["linkModes"]
            for diagnostic in offered["diagnosticModes"]
        }
        assert set(snapshot["visibility"]) == combinations, dataset
        assert all(value is None for value in snapshot["visibility"].values()), dataset


def test_thread_watch_view_shape_does_not_require_local_cache(node_json, tmp_path) -> None:
    (tmp_path / "td-thread-watch-devices.json").write_text(json.dumps([
        {"type": "threadDevice", "role": "router", "isRouter": True, "threadWatch": {"name": "router"}},
        {"type": "threadDevice", "threadWatch": {"name": "unknown"}},
    ]))
    runner = "tests/js/run-view-capability-snapshot.mjs"
    assert node_json(runner, str(tmp_path), "--datasets=otbr_restapi_topology", "--shape-only") == {}
    actual = node_json(runner, str(tmp_path), "thread_watch_devices", "--shape-only")
    snapshot = actual["thread_watch_devices"]
    assert snapshot["nodeCount"] == snapshot["rowCount"] == 2
    assert "main-routers" in snapshot["offered"]["nodeModes"]
    assert snapshot["edgeCategories"] == []


@pytest.mark.requires_data_dir
def test_projection_matches_legacy_except_documented_role_changes(node_json) -> None:
    comparisons = node_json(
        "tests/js/run-view-capability-snapshot.mjs", "data",
        f"--datasets={','.join(_legacy_baseline())}", "--compare", timeout=90,
    )
    for dataset, comparison in comparisons.items():
        assert set(comparison) == {"legacy", "projected"}, dataset
        legacy = comparison["legacy"]
        projected = comparison["projected"]
        assert {
            key: value for key, value in projected.items() if key != "visibility"
        } == {
            key: value for key, value in legacy.items() if key != "visibility"
        }, dataset
        assert set(projected["visibility"]) == set(legacy["visibility"]), dataset
        changed_filters = {
            combination.split("|", 1)[0]
            for combination in legacy["visibility"]
            if legacy["visibility"][combination] != projected["visibility"][combination]
        }
        # Mutable caches can expose row/adaptor role differences in any source.
        assert changed_filters <= ROLE_AUTHORITY_FILTERS, dataset