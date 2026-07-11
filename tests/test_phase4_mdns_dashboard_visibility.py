from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_REGISTRY_JS = REPO_ROOT / "src" / "js" / "tdash-dataset-registry.js"
DATASET_JS = REPO_ROOT / "src" / "js" / "tdash-dataset.js"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mdns_datasets_are_present_in_dashboard_registry() -> None:
    text = _read_text(DATASET_REGISTRY_JS)

    assert 'source: "mdns"' in text
    assert 'value: "mdns_thread_scopes_thread"' in text or 'td-mdns-scopes-thread.json' in text
    assert 'td-mdns-scopes-thread.json' in text
    assert 'td-mdns-scopes-br.json' in text
    assert 'td-mdns-scopes-hap.json' in text
    assert 'td-mdns-scopes-matter.json' in text


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