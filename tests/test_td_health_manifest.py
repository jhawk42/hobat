"""Tests for the approved health dataset manifest."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from td_health_manifest import HealthManifestError, load_health_manifest


EXPECTED_DATASETS = {
    "otbr_cli_networkdiag_fetch_all",
    "otbr_cli_meshdiag_topology_networkdiag_fetch_all_mdns_scopes_thread",
    "otbr_cli_topology_mdns_health",
    "otbr_restapi_diagnostics_fetch_all",
    "otbr_restapi_devices_fetch_diagnostics_fetch_all",
    "otbr_restapi_mesh_diagnostics_fetch_all",
    "otbr_restapi_devices_fetch_diagnostics_fetch_all_mesh_diagnostics_fetch_all",
    "otbr_restapi_topology_mdns_health",
}


def test_manifest_contains_only_approved_datasets() -> None:
    manifest = load_health_manifest()

    assert manifest.schema_version == 1
    assert set(manifest.datasets) == EXPECTED_DATASETS
    assert manifest.dataset("otbr_cli_networkdiag_fetch_all").files == (
        "td-otbr-cli-networkdiag-fetch-all.json",
    )
    networkdiag_profile = manifest.dataset("otbr_cli_networkdiag_fetch_all").health_profile
    assert networkdiag_profile.coverage["resilience"] == "missing"
    assert not networkdiag_profile.topology_authority
    assert manifest.dataset(
        "otbr_cli_meshdiag_topology_networkdiag_fetch_all_mdns_scopes_thread"
    ).health_profile.identity_file == "td-otbr-cli-thread-network-info.json"
    assert manifest.dataset(
        "otbr_restapi_devices_fetch_diagnostics_fetch_all"
    ).health_profile.coverage["resilience"] == "missing"
    assert not manifest.dataset(
        "otbr_restapi_mesh_diagnostics_fetch_all"
    ).health_profile.topology_authority
    assert manifest.dataset(
        "otbr_restapi_devices_fetch_diagnostics_fetch_all_mesh_diagnostics_fetch_all"
    ).health_profile.coverage["externalRouting"] == "missing"
    assert manifest.dataset("otbr_restapi_topology_mdns_health").health_profile.required_outcomes == (
        "td-otbr-restapi-diagnostics-fetch-all.outcome.json",
        "td-otbr-restapi-mesh-diagnostics-fetch-all.outcome.json",
    )


def test_manifest_rejects_unknown_dataset() -> None:
    with pytest.raises(HealthManifestError, match="not health eligible"):
        load_health_manifest().dataset("unsupported")


def test_manifest_rejects_unsafe_filename(tmp_path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "datasets": [
                    {
                        "source": "otbr-cli",
                        "value": "unsafe",
                        "files": ["../secret.json"],
                        "mergeStrategy": "none",
                        "rowExtractor": "raw-array",
                        "adaptor": "raw-array",
                        "healthEligible": True,
                        "healthProfile": "profile-v1",
                    }
                ],
                "healthProfiles": {
                    "profile-v1": {
                        "identityFile": "identity.json",
                        "requiredOutcomes": [],
                            "coverage": {
                                "availability": "sufficient",
                                "connectivity": "limited",
                                "delivery": "sufficient",
                                "resilience": "missing",
                                "externalRouting": "missing",
                            },
                            "topologyAuthority": False,
                            "borderRouterAuthority": False,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(HealthManifestError, match="path-safe"):
        load_health_manifest(manifest_path)


def test_browser_registry_health_metadata_matches_shared_manifest() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            "node",
            str(root / "tests/js/run-health-manifest-contract.mjs"),
            str(root / "src/td-dataset-manifest.json"),
        ],
        check=True,
        cwd=root,
    )