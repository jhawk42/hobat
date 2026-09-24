"""Tests for the approved health dataset manifest."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from td_health_manifest import MANIFEST_PATH, HealthManifestError, load_health_manifest


EXPECTED_DATASETS = {
    "otbr_cli_networkdiag_fetch_all",
    "otbr_cli_topology_health",
    "otbr_cli_topology_mdns_health",
    "otbr_restapi_devices_fetch_diagnostics_fetch_all",
    "otbr_restapi_devices_fetch_diagnostics_fetch_all_mesh_diagnostics_fetch_all",
    "otbr_restapi_topology_mdns_health",
    "merged_otbr_topology_mdns_health",
}


def test_manifest_contains_only_approved_datasets() -> None:
    manifest = load_health_manifest()

    assert manifest.schema_version == 2
    assert manifest.roster_policy.digest == "52176e13b7493071e15e53ff713a5cfbc33ff0817f4b00aee47391c97b16cf65"
    assert set(manifest.datasets) == EXPECTED_DATASETS
    assert manifest.dataset("otbr_cli_networkdiag_fetch_all").files == (
        "td-otbr-cli-networkdiag-fetch-all.json",
    )
    networkdiag_profile = manifest.dataset("otbr_cli_networkdiag_fetch_all").health_profile
    assert networkdiag_profile.coverage["resilience"] == "limited"
    assert not networkdiag_profile.topology_authority
    assert networkdiag_profile.border_router_authority
    assert manifest.dataset(
        "otbr_cli_topology_health"
    ).health_profile.border_router_authority
    assert manifest.dataset(
        "otbr_restapi_devices_fetch_diagnostics_fetch_all"
    ).health_profile.border_router_authority
    assert manifest.dataset(
        "otbr_restapi_devices_fetch_diagnostics_fetch_all_mesh_diagnostics_fetch_all"
    ).health_profile.border_router_authority
    assert manifest.dataset("otbr_restapi_topology_mdns_health").health_profile.required_outcomes == (
        "td-otbr-restapi-diagnostics-fetch-all.outcome.json",
        "td-otbr-restapi-mesh-diagnostics-fetch-all.outcome.json",
    )
    merged_profile = manifest.dataset("merged_otbr_topology_mdns_health").health_profile
    assert merged_profile.identity_file == "td-otbr-cli-thread-network-info.json"
    assert merged_profile.profile_id == "merged-otbr-topology-diagnostics-mdns-v1"
    matter_topology = manifest.ineligible_datasets["ha_matter_ws_merge_topology"]
    assert matter_topology.datasource_id == "ha-matter-ws"
    assert "separate stable identity context" in matter_topology.reason
    assert matter_topology.required_evidence == (
        "A dedicated cached identity file with one canonical extPanId and networkName",
        "Processor-owned normalization of native topology nodes and connections into canonical devices and relationships",
        "A merge outcome proving all required Matter inputs were collected successfully for one observation",
    )
    assert "ha_matter_ws_merge_topology" not in manifest.datasets


def test_manifest_rejects_unknown_dataset() -> None:
    with pytest.raises(HealthManifestError, match="not health eligible"):
        load_health_manifest().dataset("unsupported")


def test_schema_two_keeps_health_subset_and_roster_digest(tmp_path: Path) -> None:
    baseline = load_health_manifest()
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    raw["schemaVersion"] = 2
    extra = next(entry for entry in raw["datasets"] if entry["source"] == "mdns").copy()
    extra["value"] = "mdns_scopes_test"
    extra.pop("mergeGroups", None)
    extra.pop("mergeInputs", None)
    raw["datasets"].append(extra)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    expanded = load_health_manifest(path)

    assert expanded.schema_version == 2
    assert expanded.datasets == baseline.datasets
    assert expanded.roster_policy.digest == baseline.roster_policy.digest


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