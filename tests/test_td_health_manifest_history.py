"""Independent reviewed fixtures for the immutable manifest-history contract."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import MappingProxyType

import pytest

import td_health_manifest_history as history
from td_health_manifest import MANIFEST_PATH, HealthManifestError, load_health_manifest
from td_health_manifest_history import (
    HISTORY_PATH,
    ManifestHistoryError,
    canonical_digest,
    canonical_json,
    health_projection,
    load_manifest_history,
    parse_json,
    profile_declaration,
    retained_replay_contract,
    retained_replay_digest,
    target_contract,
    target_contract_digest,
)


# Original vectors approved independently in SX-48 Sections 9/9.2.
# Later captures are pinned independently, not derived from production helpers.
EXPECTED = (
    ("70f38e09b2964d02b0b716d5a1339ce370a2d4fe",
     "894ddf08935e76d50e1dea396d098fafc2fd187cfae187b099e91119e5f4fe26",
     "ee247c20406a18fbfa811f8db85b4a520b5c2988ab4c3e6e1993f4ead2b4f3a8"),
    ("70a56307c10d2fa254d6fc3ba26c771adebbc07a",
     "1d1829d4c4195c8401ad653062374e3f669b903c603c952dc6ed566681e7bbdf",
     "fb637e8a2700697a139e53083bd9d888c3cd70a480715b508ecbc9e1dac18ff3"),
    ("261c2f260310ff7da152543102677e6df32b51d0",
     "098425c1750a3e2f07aeaee36dae0b477cda5937094006eda259fe08d7b2f8d6",
     "57a33543ba2851854bb040887f3e050d9430383baf2aabdbd8962c6d1b9d238d"),
    ("c41ea11d2b511980d48b56410f8432bc834d5c26",
     "4df64fa0175b516c93ce397a45629896f69d9d91d7ad5fe0345f0451ef745e35",
     "bdbae6d46d403f4507f531258df2cfdf841859e57986d918790e77615c8cf855"),
    ("51562564d45cfe2cf80bc95290a43fb29bc1ed29",
     "aa4a7fc9f796b35724a92e2540801f412bf3d54afbd3d1dddf86f8dc50dda7de",
     "bdbae6d46d403f4507f531258df2cfdf841859e57986d918790e77615c8cf855"),
    ("d3c43672a071546202e2f2a4335232a174f45f3c",
     "0c7160769a97af622b0c6de44bc2597cc9f39d98595a9ced01bc32dc30aab126",
     "9570b2ba2bbfbede7ea027a814f96b1fdfb58b9e93035390f542c0ee4f2aa3d4"),
    ("ad84665894c57d8ee0bd926fcf07b99fecb186da",
     "942167cc426ff3415f8c7394ac4920cc82559571a81ce731f0ebd69ab6bf6ad1",
     "ac01bbe73e42b967978248779f4ff6cbaad2006c9ad041cacadc06b84f1d3c4e"),
    ("9f7776c376fb138930e7a18911f161905ce55129",
     "50b5a9f2e71c734a9fe5b8615d0fe7ee3e2a22f3965bd616af6bf1a2c3e05598",
     "1bc43240ac6373968f9b1886d3a4832dce2cc4496f786e5b3ad32e7eabce3023"),
    (None,
     "9ec1668fbd091746f82c6783b219e6e447e29a2ee81b6817f8e3c2aa8c2c9e28",
     "1ada0cf541485a694313097000a9c9a65416511d0ecd1ad58e0b5c9beffb30f4"),
    (None,
     "5a981ad569a13253c809d36cf0c3a0668a127a9f4b20b0d8d82b8f54e2ce6752",
     "1ada0cf541485a694313097000a9c9a65416511d0ecd1ad58e0b5c9beffb30f4"),
    (None,
     "73e911ff0385d0de5f06bbb870dccb50467e78f64cec906bab18527125046b3e",
     "1ada0cf541485a694313097000a9c9a65416511d0ecd1ad58e0b5c9beffb30f4"),
    (None,
     "88ac93a9e81380ad7c02542c23e8cfe58f469cb180c589df89acc7f61b19349e",
     "1ada0cf541485a694313097000a9c9a65416511d0ecd1ad58e0b5c9beffb30f4"),
    (None,
     "d369ccc7cca9e30cd2016ac33213039343ef94d9d224ea73d2ffd2dbcb548dd6",
     "1a99aac03615857a4d0c33019c227b9c732a867e473fd1624c4d938e122a8f09"),
    ("65fb5c69690040bddc0af3fbeb10618c8a1760c2",
     "c74eca00bf7ba2175c2ae1df84e485e025a2fa27cb1c220a505d4bc484bb6011",
     "1a99aac03615857a4d0c33019c227b9c732a867e473fd1624c4d938e122a8f09"),
)
DATASET_ID = "otbr_cli_networkdiag_fetch_all"
CURRENT_DATASET_ID = "otbr_cli_diagnostics_fetch"
PROFILE_ID = "otbr-cli-networkdiag-v1"
SAMPLE_CONTRACT = "comparison-v1-route64"
REPLAY_DIGEST = "6b4998e26a5827de22d3307fab41e14b08ec0f82a773c9f3d9b99023018d0e33"
TARGET_DIGEST = "6acb08a03f22626c135eb470a6acb6c7c2778889f74febb658f16f0544807b57"
POLICY_ARGS = {
    "evaluator_version": "snapshot-v14", "policy_version": "test-policy-v1",
    "policy_digest": "0" * 64,
}


@pytest.fixture
def resolver():
    return load_manifest_history()


@pytest.fixture
def archive():
    return json.loads(HISTORY_PATH.read_text())


def _write_archive(tmp_path, archive):
    path = tmp_path / "history.json"
    path.write_text(json.dumps(archive))
    return path


def _resign(entry):
    entry["manifestDigest"] = canonical_digest(entry["manifest"])
    entry["revisionId"] = "manifest-sha256:" + entry["manifestDigest"]
    entry["healthContractDigest"] = canonical_digest(health_projection(entry["manifest"]))


def _resolve(resolver, dataset_id=DATASET_ID, **kwargs):
    return resolver.resolve_source(dataset_id, "otbr-cli", PROFILE_ID, SAMPLE_CONTRACT, **kwargs)


def test_all_fourteen_exact_snapshots_and_original_policy_metadata(resolver):
    assert len(resolver.revisions) == 14
    assert len(resolver.declared_dataset_ids) == 23
    for revision, (commit, snapshot, projection) in zip(resolver.revisions, EXPECTED, strict=True):
        assert revision.commit == commit
        assert revision.manifest_digest == snapshot
        assert revision.health_contract_digest == projection
        assert revision.revision_id == "manifest-sha256:" + snapshot
        assert revision.manifest_path == "src/td-dataset-manifest.json"
        assert not revision.is_current
        assert canonical_digest(revision.manifest) == snapshot
        assert canonical_digest(health_projection(revision.manifest)) == projection
        assert all(item.dataset_id == key for key, item in revision.datasets.items())
    for revision in resolver.revisions[:5]:
        assert "rosterPolicy" not in revision.manifest
    for revision in resolver.revisions[5:7]:
        policy = revision.manifest["rosterPolicy"]
        assert policy["version"] == "roster-v1"
        assert "eui64" in policy["fields"]
        assert "eui" not in policy["fields"]
        assert not hasattr(revision, "roster_policy")
    assert resolver.revisions[7].manifest["rosterPolicy"]["version"] == "roster-v2"
    for captured in resolver.revisions[8:13]:
        assert captured.capture_kind == "worktree"
        assert captured.commit is None and captured.committed_at is None
        assert captured.captured_at
    assert all(revision.capture_kind is None for revision in resolver.revisions[:8])
    assert resolver.revisions[13].capture_kind is None
    assert resolver.revisions[3].manifest_digest != resolver.revisions[4].manifest_digest
    assert resolver.revisions[3].health_contract_digest == resolver.revisions[4].health_contract_digest
    assert resolver.current.is_current
    resolver.verify_snapshot()


@pytest.mark.parametrize(("dataset_id", "replay_digest", "target_digest"), [
    ("otbr_cli_unified", "3026fda74c8081a19cc22719a354661e9c529caea816c7a85f129b21ee7587d1",
     "811394db7e9feebd4a918cc213de0fe659eaa4649423ae3a6364f537e2a02038"),
    ("otbr_restapi_unified", "e7691352bc45a63fb7c050b40cbf4df714e37eb1c7ddac8dd7d661809313947d",
     "b4b2cf49be55ec5a98a887565b589d4398d925843bf1c2897c690676667a865b"),
    ("ha_matter_ws_unified", "a985537b14f1b1616ab8d0f73bba0fdf1a9345281ff7b4e14297b386c4d9d869",
     "b78c74da5ff3ba851a8ad490034e61b474443ac60a6b6d036375285044e86d9c"),
    ("multi_source_unified", "d09b7cd76af43b27fd1b8c301d0d8ebdefb0cac44fb0d76ad43ef6b78491420c",
     "dca01c09f6bf85dc487f614b6c76458fb3e957596eb309c8a43a3dd6ad25ac7d"),
])
def test_unified_exact_current_support_and_independent_vectors(resolver, dataset_id, replay_digest, target_digest):
    dataset = resolver.current_target(dataset_id)
    assert retained_replay_digest(dataset, "comparison-v1-unified") == replay_digest
    assert target_contract_digest(
        dataset, "comparison-v1-unified", **{**POLICY_ARGS, "evaluator_version": "snapshot-v15"},
    ) == target_digest
    resolution = resolver.resolve_source(
        dataset_id, dataset.datasource_id, dataset.health_profile.profile_id, "comparison-v1-unified",
    )
    assert resolution.dataset == dataset
    assert resolution.source_revision_ids == (
        resolver.current.revision_id,
        "manifest-sha256:c74eca00bf7ba2175c2ae1df84e485e025a2fa27cb1c220a505d4bc484bb6011",
        "manifest-sha256:d369ccc7cca9e30cd2016ac33213039343ef94d9d224ea73d2ffd2dbcb548dd6",
    )
    assert resolver.resolve_target(resolution, "comparison-v1-unified").reason is None
    for version in ("comparison-v1", "comparison-v1-route64"):
        assert not resolver.matching_candidates(
            dataset_id, dataset.datasource_id, dataset.health_profile.profile_id, version,
        )


def test_source_label_change_preserves_displaced_manifest_and_exact_contracts(resolver):
    prior = resolver.revisions[-1]
    presentation = json.loads(canonical_json(prior.manifest))
    assert presentation["datasources"][5]["label"] == "Multi-source"
    presentation["datasources"][5]["label"] = "multi-source"
    assert presentation == json.loads(canonical_json(resolver.current.manifest))
    assert prior.health_contract_digest == resolver.current.health_contract_digest
    for dataset_id, dataset in prior.datasets.items():
        sample = "comparison-v1-unified" if dataset_id.endswith("_unified") else (
            "comparison-v1-route64" if dataset_id == CURRENT_DATASET_ID else "comparison-v1"
        )
        source = resolver.resolve_source(
            dataset_id, dataset.datasource_id, dataset.health_profile.profile_id, sample,
            revision_id=prior.revision_id,
        )
        assert source.status == "historical-contract"
        assert source.source_revision_ids == (prior.revision_id,)
        current = resolver.current_target(dataset_id)
        assert current is not None
        assert source.source_contract_digest == retained_replay_digest(current, sample)
        assert target_contract_digest(dataset, sample, **POLICY_ARGS) == target_contract_digest(
            current, sample, **POLICY_ARGS,
        )
        assert resolver.resolve_target(source, sample).reason is None


@pytest.mark.parametrize("index", range(8))
def test_historical_acceptance_never_relaxes_native_loader(tmp_path, archive, index):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(archive["revisions"][index]["manifest"]))
    with pytest.raises(HealthManifestError, match="rosterPolicy|Invalid dataset identifier"):
        load_health_manifest(path)


def test_revision_and_nested_values_are_immutable(resolver):
    revision = resolver.revisions[-1]
    with pytest.raises(FrozenInstanceError):
        revision.commit = "changed"
    with pytest.raises(TypeError):
        revision.manifest["schemaVersion"] = 1
    with pytest.raises(TypeError):
        revision.manifest["datasets"][0]["files"][0] = "changed"
    with pytest.raises(TypeError):
        revision.datasets[CURRENT_DATASET_ID].health_profile.coverage["availability"] = "missing"
    candidate = _resolve(resolver).candidates[0]
    with pytest.raises(TypeError):
        candidate.replay_contract["profile"]["coverage"]["availability"] = "missing"


@pytest.mark.parametrize("text", [
    '{"a":1,"a":2}', '{"nested":{"a":1,"a":2}}',
    '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e9999}',
])
def test_strict_json_rejects_duplicate_keys_and_all_nonfinite_numbers(text):
    with pytest.raises(ManifestHistoryError, match="Duplicate|Non-finite"):
        parse_json(text)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_canonicalization_rejects_nonfinite_values(value):
    with pytest.raises(ManifestHistoryError, match="canonical JSON"):
        canonical_digest({"x": value})


def test_canonicalization_preserves_unicode_booleans_arrays_and_order():
    value = {"z": False, "a": ["é", True, []]}
    assert canonical_json(value) == b'{"a":["\\u00e9",true,[]],"z":false}'
    assert canonical_digest(value) == hashlib.sha256(canonical_json(value)).hexdigest()
    assert canonical_digest({"a": [1, 2]}) != canonical_digest({"a": [2, 1]})
    assert canonical_digest({"a": True}) != canonical_digest({"a": 1})


def test_formatting_and_presentation_do_not_change_replay_or_projection(tmp_path, archive, resolver):
    path = _write_archive(tmp_path, archive)
    reformatted = load_manifest_history(history_path=path)
    assert [item.manifest_digest for item in reformatted.revisions] == [
        item.manifest_digest for item in resolver.revisions]
    assert reformatted.snapshot_digest != resolver.snapshot_digest
    raw = json.loads(MANIFEST_PATH.read_text())
    before = canonical_digest(health_projection(raw))
    next(item for item in raw["datasets"] if item["value"] == CURRENT_DATASET_ID)["label"] = "A new label"
    assert canonical_digest(health_projection(raw)) == before
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(raw, sort_keys=True, indent=3))
    changed = load_manifest_history(manifest_path=path)
    assert changed.current.manifest_digest != resolver.current.manifest_digest
    assert changed.current.health_contract_digest == resolver.current.health_contract_digest
    assert _resolve(changed).source_contract_digest == REPLAY_DIGEST
    assert changed.current_target(DATASET_ID) is None


def test_exact_golden_replay_and_target_vectors(resolver):
    dataset = resolver.revisions[7].datasets[DATASET_ID]
    replay = retained_replay_contract(dataset, SAMPLE_CONTRACT)
    assert set(replay) == {"contractVersion", "dataset", "profile", "sampleContractVersion"}
    assert replay["profile"]["requiredOutcomes"] == []
    assert replay["profile"]["topologyAuthority"] is False
    assert replay["profile"]["borderRouterAuthority"] is True
    assert retained_replay_digest(dataset, SAMPLE_CONTRACT) == REPLAY_DIGEST
    assert canonical_digest(parse_json(json.dumps(replay, indent=4))) == REPLAY_DIGEST
    target = target_contract(dataset, SAMPLE_CONTRACT, **POLICY_ARGS)
    assert set(target) == {"contractVersion", "replayContract", "evaluatorVersion", "policyVersion",
                           "policyDigest", "inputAvailabilityVersion", "adapterId"}
    assert target["replayContract"] == replay
    assert target_contract_digest(dataset, SAMPLE_CONTRACT, **POLICY_ARGS) == TARGET_DIGEST
    changed = replace(dataset, health_profile=replace(dataset.health_profile, border_router_authority=False))
    assert retained_replay_digest(changed, SAMPLE_CONTRACT) != REPLAY_DIGEST
    assert target_contract_digest(changed, SAMPLE_CONTRACT, **POLICY_ARGS) != TARGET_DIGEST
    assert canonical_digest(health_projection(resolver.revisions[0].manifest)) != resolver.current.health_contract_digest


def test_identifier_cutover_has_distinct_current_vectors_and_no_cross_id_replay(resolver):
    current = resolver.current_target(CURRENT_DATASET_ID)
    assert retained_replay_digest(current, SAMPLE_CONTRACT) == (
        "d6fb43cc5e83abb0f026c71f207d183fad2bf2486ef6535118bfeb40991337e4")
    assert target_contract_digest(current, SAMPLE_CONTRACT, **POLICY_ARGS) == (
        "0293a718d4c504994ccdc6ef9cacce1771f51f307326aac6953dfa6333252e05")
    source = _resolve(resolver, dataset_id=CURRENT_DATASET_ID, revision_id=resolver.current.revision_id)
    assert source.status == "current-contract"
    assert source.source_revision_ids == (resolver.current.revision_id,)
    assert resolver.resolve_target(source, SAMPLE_CONTRACT).adapter_id == "retained-equivalent-v1"
    historical = _resolve(resolver)
    assert historical.source_contract_digest == REPLAY_DIGEST
    assert resolver.resolve_target(historical, SAMPLE_CONTRACT).reason == "no-current-health-target"
    for candidate in historical.candidates:
        assert candidate.dataset.dataset_id == DATASET_ID
        assert candidate.dataset.datasource_id == "otbr-cli"


def test_retained_store_resolves_original_recipes_without_aliases(resolver):
    import sqlite3
    from td_health_sqlite import SQLiteHealthStore

    for dataset_id, dataset in resolver.revisions[7].datasets.items():
        sample = SAMPLE_CONTRACT if dataset_id == DATASET_ID else "comparison-v1"
        assert SQLiteHealthStore._retained_dataset(
            dataset_id, dataset.datasource_id, dataset.health_profile.profile_id, sample,
        ) == dataset
        with pytest.raises(sqlite3.DatabaseError, match="Unsupported retained"):
            SQLiteHealthStore._retained_dataset(
                dataset_id, "wrong-source", dataset.health_profile.profile_id, sample,
            )
        with pytest.raises(sqlite3.DatabaseError, match="Unsupported retained"):
            SQLiteHealthStore._retained_dataset(
                dataset_id, dataset.datasource_id, dataset.health_profile.profile_id, "legacy-unknown",
            )

@pytest.mark.parametrize("field", [
    "datasource_id", "dataset_id", "files", "merge_strategy", "row_extractor", "adaptor", "health_profile",
])
def test_null_required_dataset_fields_cannot_be_fingerprinted(resolver, field):
    dataset = replace(resolver.current_target(CURRENT_DATASET_ID), **{field: None})
    with pytest.raises(ManifestHistoryError):
        retained_replay_contract(dataset, SAMPLE_CONTRACT)


@pytest.mark.parametrize("field", [
    "profile_id", "identity_file", "required_outcomes", "coverage", "topology_authority", "border_router_authority",
])
def test_null_required_profile_fields_cannot_be_fingerprinted(resolver, field):
    dataset = resolver.current_target(CURRENT_DATASET_ID)
    changed = replace(dataset, health_profile=replace(dataset.health_profile, **{field: None}))
    with pytest.raises(ManifestHistoryError):
        retained_replay_contract(changed, SAMPLE_CONTRACT)


@pytest.mark.parametrize("field", ["evaluator_version", "policy_version", "policy_digest"])
def test_null_target_identity_fields_are_invalid(resolver, field):
    with pytest.raises(ManifestHistoryError):
        target_contract_digest(resolver.current_target(CURRENT_DATASET_ID), SAMPLE_CONTRACT,
                               **{**POLICY_ARGS, field: None})


def test_target_policy_identity_preserves_existing_opaque_digest_contract(resolver):
    dataset = resolver.current_target(CURRENT_DATASET_ID)
    contract = target_contract(dataset, SAMPLE_CONTRACT,
                               **{**POLICY_ARGS, "policy_digest": "test-policy-p2"})
    assert contract["policyDigest"] == "test-policy-p2"
    assert canonical_digest(contract) != TARGET_DIGEST
    with pytest.raises(ManifestHistoryError):
        target_contract(dataset, SAMPLE_CONTRACT, **{**POLICY_ARGS, "policy_digest": ""})


@pytest.mark.parametrize("value", [None, "", False])
def test_sample_contract_is_never_synthesized(resolver, value):
    with pytest.raises(ManifestHistoryError):
        retained_replay_contract(resolver.current_target(CURRENT_DATASET_ID), value)


def test_producer_allowlist_excludes_all_old_profiles_before_ambiguity(resolver):
    source = _resolve(resolver)
    assert source.status == "equivalent-contracts"
    assert source.reason is None
    assert source.source_contract_digest == REPLAY_DIGEST
    assert source.source_revision_ids == tuple(sorted([
        resolver.revisions[5].revision_id, resolver.revisions[6].revision_id, resolver.revisions[7].revision_id,
    ]))
    assert len(source.candidates) == 3
    assert {candidate.revision.commit for candidate in source.candidates} == {
        EXPECTED[5][0], EXPECTED[6][0], EXPECTED[7][0],
    }
    assert resolver.resolve_target(source, SAMPLE_CONTRACT).adapter_id is None
    assert resolver.resolve_target(source, SAMPLE_CONTRACT).reason == "no-current-health-target"
    for dataset in resolver.revisions[7].datasets.values():
        sample = SAMPLE_CONTRACT if dataset.dataset_id == DATASET_ID else "comparison-v1"
        assert len(resolver.matching_candidates(
            dataset.dataset_id, dataset.datasource_id, dataset.health_profile.profile_id, sample)) == 3
        for revision in resolver.revisions[3:8]:
            assert retained_replay_digest(revision.datasets[dataset.dataset_id], sample) == (
                retained_replay_digest(dataset, sample))


def test_health_projection_changes_for_authority_not_presentation(resolver):
    raw = json.loads(MANIFEST_PATH.read_text())
    raw["healthProfiles"][PROFILE_ID]["borderRouterAuthority"] = False
    assert canonical_digest(health_projection(raw)) != resolver.current.health_contract_digest


@pytest.mark.parametrize("index", range(5))
def test_explicit_old_revision_cannot_fall_back_to_new_producer(resolver, index):
    with pytest.raises(ManifestHistoryError) as caught:
        _resolve(resolver, revision_id=resolver.revisions[index].revision_id)
    assert caught.value.reason == "unsupported-sample-contract"


@pytest.mark.parametrize("revision_index,status", [(None, "current-contract"), (5, "historical-contract")])
def test_exact_revision_identity_and_profile_mapping(resolver, revision_index, status):
    revision = resolver.current if revision_index is None else resolver.revisions[revision_index]
    dataset_id = CURRENT_DATASET_ID if revision_index is None else DATASET_ID
    source = _resolve(resolver, dataset_id=dataset_id, revision_id=revision.revision_id,
                      source_profile=profile_declaration(revision.datasets[dataset_id].health_profile))
    assert source.status == status
    assert source.source_revision_ids == (revision.revision_id,)


@pytest.mark.parametrize("field,value", [("datasource_id", "wrong-source"), ("profile_id", "wrong-profile")])
def test_exact_ids_never_alias(resolver, field, value):
    args = dict(dataset_id=DATASET_ID, datasource_id="otbr-cli", profile_id=PROFILE_ID,
                sample_contract_version=SAMPLE_CONTRACT)
    args[field] = value
    assert resolver.matching_candidates(**args) == ()
    with pytest.raises(ManifestHistoryError) as caught:
        resolver.matching_candidates(**args, revision_id=resolver.current.revision_id)
    assert caught.value.reason == "conflicting-manifest-revision"


def test_unknown_revision_and_legacy_contract_remain_explicit(resolver):
    with pytest.raises(ManifestHistoryError) as caught:
        _resolve(resolver, revision_id="manifest-sha256:" + "0" * 64)
    assert caught.value.reason == "unknown-manifest-revision"
    source = resolver.resolve_source(DATASET_ID, "otbr-cli", PROFILE_ID, "legacy-unknown")
    assert source.status == "unresolved"
    assert source.reason == "unsupported-sample-contract"
    assert source.dataset is None


def test_saved_historical_capabilities_do_not_upgrade_to_current(resolver):
    old = resolver.revisions[0].datasets[DATASET_ID]
    assert old.health_profile != resolver.current.datasets[CURRENT_DATASET_ID].health_profile
    source = _resolve(resolver, source_profile=old.health_profile)
    assert source.status == "unresolved"
    assert source.reason == "unsupported-profile"
    malformed = profile_declaration(old.health_profile)
    malformed["borderRouterAuthority"] = 1
    with pytest.raises(ManifestHistoryError, match="authority"):
        _resolve(resolver, source_profile=malformed)


def test_removed_and_renamed_ids_remain_declared_without_current_targets(resolver):
    removed = set(resolver.declared_dataset_ids) - set(resolver.current.datasets)
    assert len(removed) == 12
    for dataset_id in removed:
        assert resolver.current_target(dataset_id) is None
    original = next(iter(resolver.revisions[0].datasets.values()))
    assert resolver.current_target("unknown") is None
    assert original.dataset_id in resolver.declared_dataset_ids


def test_material_ambiguity_is_not_resolved_by_order_or_date(resolver, monkeypatch):
    # A synthetic reviewed producer proves the ambiguity path without blessing old producers.
    old = resolver.revisions[0]
    support = {**history.PRODUCER_SAMPLE_SUPPORT,
               old.manifest_digest: {DATASET_ID: SAMPLE_CONTRACT}}
    monkeypatch.setattr(history, "PRODUCER_SAMPLE_SUPPORT", support)
    source = _resolve(resolver)
    assert source.status == "ambiguous"
    assert source.reason == "ambiguous-historical-contract"
    assert source.dataset is None
    assert source.source_contract_digest is None
    historical = _resolve(resolver, revision_id=old.revision_id)
    target = resolver.resolve_target(historical, SAMPLE_CONTRACT)
    assert target.reason == "no-current-health-target"
    assert target.adapter_id is None
    assert _resolve(replace(resolver, revisions=tuple(reversed(resolver.revisions)))).status == "ambiguous"


def test_missing_target_has_typed_failure(resolver):
    source = _resolve(resolver)
    current = replace(resolver.current, datasets=MappingProxyType({}))
    target = replace(resolver, current=current).resolve_target(source, SAMPLE_CONTRACT)
    assert target.reason == "no-current-health-target"
    assert target.dataset is None
    assert target.adapter_id is None


@pytest.mark.parametrize("change,match", [
    (lambda a: a.update(schemaVersion=2), "wrapper"),
    (lambda a: a.update(schemaVersion=True), "wrapper"),
    (lambda a: a.update(projectionVersion="health-manifest-v2"), "wrapper"),
    (lambda a: a.update(extra=True), "wrapper"),
    (lambda a: a["revisions"].append(copy.deepcopy(a["revisions"][0])), "Duplicate revision"),
    (lambda a: a["revisions"][0].update(revisionId="wrong"), "Revision ID"),
    (lambda a: a["revisions"][0].update(manifestDigest="0" * 64, revisionId="manifest-sha256:" + "0" * 64), "digest mismatch"),
    (lambda a: a["revisions"][0].update(healthContractDigest="0" * 64), "projection digest"),
    (lambda a: a["revisions"][0].update(manifestPath="../manifest.json"), "manifestPath"),
    (lambda a: a["revisions"][0].update(commit="short"), "commit"),
    (lambda a: a["revisions"][0].update(committedAt="2026-09-01"), "committedAt"),
    (lambda a: a["revisions"][0].update(executable="import code"), "revision fields"),
])
def test_archive_wrapper_and_integrity_fail_explicitly(tmp_path, archive, change, match):
    change(archive)
    with pytest.raises(ManifestHistoryError, match=match):
        load_manifest_history(history_path=_write_archive(tmp_path, archive))


@pytest.mark.parametrize("mutate,match", [
    (lambda m: m.update(schemaVersion=True), "schemaVersion"),
    (lambda m: m["datasets"].append(copy.deepcopy(m["datasets"][0])), "Duplicate dataset"),
    (lambda m: m["datasets"][0]["files"].append(m["datasets"][0]["files"][0]), "Duplicate filenames"),
    (lambda m: m["datasets"][0].update(files=["../secret.json"]), "path-safe"),
    (lambda m: m["datasets"][0].update(files=["C:\\secret.json"]), "path-safe"),
    (lambda m: m["datasets"][0].update(mergeStrategy="execute"), "mergeStrategy"),
    (lambda m: m["datasets"][0].update(healthProfile="unknown"), "healthProfile"),
    (lambda m: m["healthProfiles"][PROFILE_ID].update(borderRouterAuthority=1), "authority"),
    (lambda m: m["healthProfiles"][PROFILE_ID]["coverage"].update(availability="unknown"), "coverage"),
    (lambda m: m["healthProfiles"][PROFILE_ID].update(identityFile="../identity.json"), "path-safe"),
    (lambda m: m["healthProfiles"][PROFILE_ID]["requiredOutcomes"].extend(["same.json", "same.json"]), "Duplicate filenames"),
    (lambda m: m.update(rosterPolicy=None), "Missing historical"),
])
def test_historical_field_validation_is_not_just_digest_validation(tmp_path, archive, mutate, match):
    entry = archive["revisions"][0]
    mutate(entry["manifest"])
    entry["manifestDigest"] = canonical_digest(entry["manifest"])
    entry["revisionId"] = "manifest-sha256:" + entry["manifestDigest"]
    with pytest.raises(ManifestHistoryError, match=match):
        load_manifest_history(history_path=_write_archive(tmp_path, archive))


def test_current_snapshot_cannot_be_archived_again(tmp_path, archive, resolver):
    entry = copy.deepcopy(archive["revisions"][7])
    entry["manifest"] = json.loads(MANIFEST_PATH.read_text())
    entry["commit"] = "f" * 40
    _resign(entry)
    archive["revisions"].append(entry)
    with pytest.raises(ManifestHistoryError, match="must not be duplicated"):
        load_manifest_history(history_path=_write_archive(tmp_path, archive))


def test_exact_worktree_capture_retains_current_ids_without_cross_id_replay(resolver):
    captured = resolver.revisions[8]
    source = _resolve(resolver, dataset_id=CURRENT_DATASET_ID, revision_id=captured.revision_id)
    assert source.status == "historical-contract"
    assert source.source_contract_digest == retained_replay_digest(
        resolver.current_target(CURRENT_DATASET_ID), SAMPLE_CONTRACT)
    assert resolver.resolve_target(source, SAMPLE_CONTRACT).adapter_id == "retained-equivalent-v1"
    assert resolver.resolve_target(_resolve(resolver), SAMPLE_CONTRACT).reason == "no-current-health-target"


@pytest.mark.parametrize("changes", [
    {"captureKind": "commit"}, {"commit": "f" * 40}, {"committedAt": "2026-10-27T00:00:00Z"},
    {"capturedAt": "not-a-time"}, {"capturedAt": "2026-10-27"},
])
def test_worktree_capture_cannot_fabricate_commit_provenance(tmp_path, archive, changes):
    archive["revisions"][8].update(changes)
    with pytest.raises(ManifestHistoryError):
        load_manifest_history(history_path=_write_archive(tmp_path, archive))


@pytest.mark.parametrize("which", ["manifest", "history"])
def test_changed_file_bytes_refuse_stale_snapshot(tmp_path, which):
    manifest = tmp_path / "manifest.json"
    archive = tmp_path / "history.json"
    manifest.write_bytes(MANIFEST_PATH.read_bytes())
    archive.write_bytes(HISTORY_PATH.read_bytes())
    resolver = load_manifest_history(manifest, archive)
    path = manifest if which == "manifest" else archive
    original = path.read_bytes()
    path.write_bytes(original + b"\n")
    with pytest.raises(ManifestHistoryError) as caught:
        resolver.verify_snapshot()
    assert caught.value.reason == "stale-resolver-snapshot"
    path.write_bytes(original)
    resolver.verify_snapshot()


@pytest.mark.parametrize("which", ["manifest", "history"])
def test_missing_required_file_has_no_current_only_fallback(tmp_path, which):
    with pytest.raises(ManifestHistoryError, match="Cannot read required"):
        load_manifest_history(
            tmp_path / "missing.json" if which == "manifest" else MANIFEST_PATH,
            tmp_path / "missing.json" if which == "history" else HISTORY_PATH)


def test_change_during_load_is_detected(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(MANIFEST_PATH.read_bytes())
    native_loader = history.load_health_manifest

    def changing_loader(path):
        result = native_loader(path)
        path.write_bytes(path.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(history, "load_health_manifest", changing_loader)
    with pytest.raises(ManifestHistoryError) as caught:
        load_manifest_history(manifest)
    assert caught.value.reason == "stale-resolver-snapshot"


def test_change_during_individual_read_is_detected(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(MANIFEST_PATH.read_bytes())
    original_read = Path.read_bytes

    def changing_read(path):
        result = original_read(path)
        if path == manifest:
            path.write_bytes(result + b"\n")
        return result

    monkeypatch.setattr(Path, "read_bytes", changing_read)
    with pytest.raises(ManifestHistoryError) as caught:
        load_manifest_history(manifest)
    assert caught.value.reason == "stale-resolver-snapshot"


def test_exact_docker_exception_preserves_broad_cache_exclusion():
    lines = (Path(__file__).resolve().parents[1] / ".dockerignore").read_text().splitlines()
    assert "**/td-*.json" in lines
    index = lines.index("!src/td-dataset-manifest.json")
    assert lines[index + 1] == "!src/td-dataset-manifest-history.json"
