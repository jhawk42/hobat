from __future__ import annotations

from pathlib import Path

from td_dataset_catalog import load_dataset_catalog


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_JS = REPO_ROOT / "src" / "js" / "tdash-dataset.js"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mdns_datasets_are_present_in_dashboard_registry() -> None:
    entries = [entry for entry in load_dataset_catalog()["datasets"] if entry["source"] == "mdns"]
    files = {file for entry in entries for file in entry["files"]}

    assert {"td-mdns-scopes-thread.json", "td-mdns-scopes-br.json",
            "td-mdns-scopes-hap.json", "td-mdns-scopes-matter.json"} <= files


def test_mdns_datasets_support_progressive_checkpoint_fetching() -> None:
    text = _read_text(DATASET_JS)

    assert 'td-mdns-scopes-thread.json' in text
    assert 'td-mdns-scopes-br.json' in text
    assert 'td-mdns-scopes-hap.json' in text
    assert 'td-mdns-scopes-matter.json' in text
    assert 'checkpoint_filename' in text
    assert 'checkpoint_last_modified' in text
    assert 'onCheckpointData' in text


def test_phase4_progressive_rollout_file_names_are_aligned() -> None:
    text = _read_text(DATASET_JS)

    assert 'td-otbr-restapi-devices-fetch.json' in text
    assert 'td-otbr-restapi-devices-fetch-all.json' not in text
    assert 'td-otbr-cli-networkdiag-multicast-network.json' in text
    assert 'td-otbr-restapi-diagnostics-fetch-all.json' in text
    assert 'td-otbr-restapi-mesh-diagnostics-fetch-all.json' in text