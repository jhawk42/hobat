from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_view_status_owner(node_json) -> None:
    assert node_json("tests/js/run-view-status-owner.mjs") == {
        "presentedCount": 5,
        "finalStatus": "Topology error: empty dataset",
        "staleDatasetRejected": True,
        "transientOverrideRestored": True,
    }


def test_renderers_publish_status_through_view_owner() -> None:
    topology_source = (REPO_ROOT / "src/js/tdash-topology-renderer.js").read_text(
        encoding="utf-8",
    )
    table_source = (REPO_ROOT / "src/js/tdash-table-renderer.js").read_text(
        encoding="utf-8",
    )

    assert 'publishViewStatus("topology", status.text, statusDatasetToken);' in topology_source
    assert 'publishViewStatus("table", statusText, _tableDatasetToken);' in table_source
    assert 'document.getElementById("view-status-line-content").textContent' not in topology_source
    assert 'document.getElementById("view-status-line-content").textContent' not in table_source