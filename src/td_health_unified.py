"""Verified original-evidence and retained Unified health contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from td_health_manifest import HealthDataset

from td_const import (
    OTBR_CLI_MESHDIAG_ROUTER_CHILDTABLES_FILENAME,
    OTBR_CLI_MESHDIAG_ROUTER_NEIGHBORTABLES_FILENAME,
    OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME,
    OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
)

SAMPLE_CONTRACT = "comparison-v1-unified"
CONTEXT_VERSION = "unified-health-v1"
RECIPE_VERSION = "unified-v1"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
DIAGNOSTICS = {
    "otbr-cli": OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
    "otbr-restapi": OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
}


def digest(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def plain(value):
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


def validate_profile(profile):
    from td_health_manifest import HealthManifestError
    if profile.input_mode == "files" and profile.evidence_report is None:
        return
    if (profile.input_mode != "unified"
            or not isinstance(profile.evidence_report, str)
            or not re.fullmatch(r"td-[a-z0-9-]+\.report\.json", profile.evidence_report)):
        raise HealthManifestError("Invalid Unified health inputMode/evidenceReport")


def validate_recipe(value):
    from td_health_manifest import HealthManifestError
    if (not isinstance(value, Mapping)
            or set(value) != {"version", "recipeDigest", "authorityDigest", "rawInputs"}
            or value["version"] != RECIPE_VERSION
            or any(not isinstance(value[k], str) or not _DIGEST.fullmatch(value[k])
                   for k in ("recipeDigest", "authorityDigest"))
            or not isinstance(value["rawInputs"], (list, tuple)) or not value["rawInputs"]):
        raise HealthManifestError("Invalid retained unifiedRecipe")
    seen = set()
    for item in value["rawInputs"]:
        if (not isinstance(item, Mapping)
                or set(item) != {"file", "role", "required", "extractor", "source"}
                or item["source"] not in {"otbr-cli", "otbr-restapi", "ha-matter-ws", "mdns"}
                or not isinstance(item["file"], str)
                or not re.fullmatch(r"td-(?:otbr-cli|otbr-restapi|ha-matter-ws|mdns-scopes)-[a-z0-9-]+(?:\.outcome)?\.json", item["file"])
                or item["file"] in seen or "unified" in item["file"]
                or item["file"].endswith(("actions-list.json", "server-info.json", "thread-diagnostics.json"))
                or item["role"] not in {"records", "projection", "identity", "outcome"}
                or type(item["required"]) is not bool
                or item["extractor"] not in {"raw-array", "json-api", "identity", "outcome",
                                             "ha-inventory", "ha-border-routers",
                                             "ha-native-topology", "ha-projection"}):
            raise HealthManifestError("Invalid original Unified evidence closure")
        seen.add(item["file"])
        if not item["file"].startswith("td-" + item["source"] + "-"):
            raise HealthManifestError("Unified evidence source/filename mismatch")
    return freeze(plain(value))


def validate_catalog_recipe(raw, entry, profile):
    from td_health_manifest import HealthManifestError
    recipe = entry.get("unified")
    if not isinstance(recipe, dict) or profile.evidence_report != recipe["reportFile"]:
        raise HealthManifestError("Unified evidenceReport must reference its catalog recipe")
    by_file = {d["files"][0]: d for d in raw["datasets"] if "unified" in d}
    dependencies = ([by_file[item["file"]] for item in recipe["inputs"]]
                    if entry["source"] == "multi-source" else [entry])
    expected = [{**item, "source": dependency["source"]}
                for dependency in dependencies for item in dependency["unified"]["inputs"]]
    if plain(entry["unifiedRecipe"]["rawInputs"]) != expected:
        raise HealthManifestError("Retained Unified recipe does not match the catalog raw closure")


def safe_sources(dataset):
    if dataset.unified_recipe is None:
        return set()
    return {item["file"] for item in dataset.unified_recipe["rawInputs"]}


def sample_sources(dataset):
    return {item["file"] for item in dataset.unified_recipe["rawInputs"]
            if item["role"] == "records" and item["source"] != "mdns"}


@dataclass(frozen=True)
class _PreparedContract:
    dataset: HealthDataset
    recipe: dict
    recipe_digest: str
    report_contract_digests: frozenset[str]


def _prepare_contract(dataset: HealthDataset) -> _PreparedContract:
    from td_health_manifest import HealthManifestError
    if dataset.unified_recipe is None:
        raise HealthManifestError("Invalid retained unifiedHealth context")
    recipe = plain(dataset.unified_recipe)
    return _PreparedContract(dataset, recipe, digest(recipe), frozenset(
        digest(["unified-v1", builder_contract, recipe["recipeDigest"], recipe["authorityDigest"]])
        for builder_contract in (
            "unified-assembly-v2", "unified-assembly-v3", "unified-assembly-v4",
            "unified-assembly-v5", "unified-assembly-v6", "unified-assembly-v7", "unified-assembly-v8",
            "unified-assembly-v9", "unified-assembly-v10", "unified-assembly-v11",
        )
    ))


def _source_time_provenance(value, observation=None, *, required=False):
    from td_health_manifest import HealthManifestError

    entries = value.get("sourceTimeProvenance")
    if entries is None:
        if required:
            raise HealthManifestError("Missing retained Unified source-time provenance")
        return ()
    if not isinstance(entries, (list, tuple)):
        raise HealthManifestError("Invalid retained Unified source-time provenance")
    expected_sources = {
        source.filename: source for source in observation.sources
    } if observation is not None else None
    seen = set()
    normalized = []
    allowed_provenance = {
        None, "controller-snapshot", "embedded", "raw-file-mtime",
        "invalid-source-time", "unavailable-source-time", "original-evidence",
    }
    for item in entries:
        keys = {
            "filename", "digest", "kind", "state", "sourceObservedAt",
            "timeProvenance", "sourceObservationKind",
        }
        if not isinstance(item, Mapping) or set(item) != keys:
            raise HealthManifestError("Invalid retained Unified source-time provenance")
        filename = item["filename"]
        if not isinstance(filename, str) or filename in seen:
            raise HealthManifestError("Invalid retained Unified source-time provenance")
        seen.add(filename)
        if (
            not isinstance(item["digest"], str)
            or not isinstance(item["kind"], str)
            or item["kind"] not in {"final", "identity", "scope", "outcome"}
            or not isinstance(item["state"], str)
            or item["state"] not in {"valid", "missing", "invalid", "provisional", "excluded"}
            or item["timeProvenance"] is not None
            and not isinstance(item["timeProvenance"], str)
            or item["timeProvenance"] not in allowed_provenance
            or item["sourceObservationKind"] is not None
            and not isinstance(item["sourceObservationKind"], str)
            or item["sourceObservationKind"] not in {None, "controller-snapshot"}
            or item["sourceObservedAt"] is not None and not isinstance(item["sourceObservedAt"], str)
        ):
            raise HealthManifestError("Invalid retained Unified source-time provenance")
        typed = item["sourceObservationKind"] == "controller-snapshot"
        if typed != (item["timeProvenance"] == "controller-snapshot"):
            raise HealthManifestError("Invalid retained Unified controller provenance")
        if typed:
            if (
                item["kind"] != "final"
                or item["state"] not in {"valid", "provisional"}
                or not item["sourceObservedAt"]
            ):
                raise HealthManifestError("Invalid retained Unified controller provenance")
            try:
                timestamp(item["sourceObservedAt"])
            except (TypeError, AttributeError, ValueError, OverflowError) as exc:
                raise HealthManifestError("Invalid retained Unified controller provenance") from exc
        if item["sourceObservedAt"] is not None:
            try:
                timestamp(item["sourceObservedAt"])
            except (TypeError, AttributeError, ValueError, OverflowError) as exc:
                raise HealthManifestError("Invalid retained Unified source time") from exc
        if expected_sources is not None:
            source = expected_sources.get(filename)
            if source is None or (
                source.digest, source.kind, source.state, source.source_observed_at
            ) != (
                item["digest"], item["kind"], item["state"], item["sourceObservedAt"]
            ):
                raise HealthManifestError("Retained Unified source-time provenance differs from evidence")
        normalized.append(dict(item))
    if normalized != sorted(normalized, key=lambda item: item["filename"]):
        raise HealthManifestError("Invalid retained Unified source-time provenance order")
    if value.get("sourceTimeProvenanceDigest") != digest(normalized):
        raise HealthManifestError("Invalid retained Unified source-time provenance digest")
    if observation is not None and set(seen) != set(expected_sources):
        raise HealthManifestError("Retained Unified source-time provenance is incomplete")
    return tuple(normalized)


def has_typed_ha_observation(context, dataset):
    """Return whether a retained v11 HA contract binds every controller-derived input."""
    value = context.get("unifiedHealth") if isinstance(context, Mapping) else None
    if not isinstance(value, Mapping) or dataset.datasource_id != "ha-matter-ws":
        return False
    builder_digest = digest([
        "unified-v1", "unified-assembly-v11",
        dataset.unified_recipe["recipeDigest"], dataset.unified_recipe["authorityDigest"],
    ])
    if value.get("reportContractDigest") != builder_digest:
        return False
    entries = _source_time_provenance(value, required=True)
    by_name = {item["filename"]: item for item in entries}
    controller_inputs = [
        item for item in dataset.unified_recipe["rawInputs"]
        if item["source"] == "ha-matter-ws"
        and item["extractor"] in {"ha-inventory", "raw-array", "ha-projection"}
    ]
    required_inputs = [item for item in controller_inputs if item["required"]]
    if not required_inputs:
        return False
    for declaration in controller_inputs:
        entry = by_name.get(declaration["file"])
        if entry is None or entry["state"] in {"missing", "excluded"}:
            if declaration["required"]:
                return False
            continue
        if (
            entry["state"] != "valid"
            or entry["timeProvenance"] != "controller-snapshot"
            or entry["sourceObservationKind"] != "controller-snapshot"
            or not entry["sourceObservedAt"]
        ):
            return False
    return True


def validate_context(context, dataset, observation=None, *, prepared: _PreparedContract | None = None):
    """Validate retained lineage without consulting today's raw cache."""
    from td_health_manifest import HealthManifestError
    if prepared is None:
        prepared = _prepare_contract(dataset)
    elif prepared.dataset != dataset:
        raise HealthManifestError("Prepared Unified contract does not match the selected dataset")
    value = context.get("unifiedHealth") if isinstance(context, Mapping) else None
    if (not isinstance(value, Mapping) or value.get("version") != CONTEXT_VERSION
            or value.get("recipe") != prepared.recipe
            or value.get("recipeContractDigest") != prepared.recipe_digest
            or value.get("reportContractDigest") not in prepared.report_contract_digests
            or not isinstance(value.get("originalEvidenceFingerprint"), str)
            or not _DIGEST.fullmatch(value["originalEvidenceFingerprint"])
            or not isinstance(value.get("effectiveCoverage"), Mapping)):
        raise HealthManifestError("Invalid retained unifiedHealth context")
    v11_digest = digest([
        "unified-v1", "unified-assembly-v11",
        dataset.unified_recipe["recipeDigest"], dataset.unified_recipe["authorityDigest"],
    ])
    has_source_time_provenance = (
        "sourceTimeProvenance" in value or "sourceTimeProvenanceDigest" in value
    )
    if has_source_time_provenance and (
        value.get("reportContractDigest") != v11_digest
        or "sourceTimeProvenance" not in value
        or "sourceTimeProvenanceDigest" not in value
    ):
        raise HealthManifestError("Source-time provenance requires the v11 Unified contract")
    retained_source_times = _source_time_provenance(
        value, observation,
        required=value.get("reportContractDigest") == v11_digest,
    )
    typed_files = {
        item["filename"] for item in retained_source_times
        if item["sourceObservationKind"] == "controller-snapshot"
    }
    if typed_files:
        controller_input_files = {
            item["file"] for item in dataset.unified_recipe["rawInputs"]
            if item["source"] == "ha-matter-ws"
            and item["extractor"] in {"ha-inventory", "raw-array", "ha-projection"}
        }
        if (
            dataset.datasource_id not in {"ha-matter-ws", "multi-source"}
            or not typed_files <= controller_input_files
        ):
            raise HealthManifestError("Controller provenance is outside the HA input contract")
    if observation is not None and retained_source_times:
        by_name = {item["filename"]: item for item in retained_source_times}
        fingerprint = []
        for source in observation.sources:
            item = dict(
                filename=source.filename, digest=source.digest, kind=source.kind,
                state=source.state, sourceObservedAt=source.source_observed_at,
            )
            provenance = by_name[source.filename]
            item.update(
                timeProvenance=provenance["timeProvenance"],
                sourceObservationKind=provenance["sourceObservationKind"],
            )
            fingerprint.append(item)
        if digest(fingerprint) != value["originalEvidenceFingerprint"]:
            raise HealthManifestError("Invalid retained Unified original evidence fingerprint")
    maxima = dataset.health_profile.coverage
    ordering = {"missing": 0, "limited": 1, "sufficient": 2}
    if (set(value["effectiveCoverage"]) != set(maxima)
            or any(state not in ordering or ordering[state] > ordering[maxima[pillar]]
                   for pillar, state in value["effectiveCoverage"].items())
            or value.get("reportContractVersion") != "unified-v1"):
        raise HealthManifestError("Unified effective coverage exceeds its declared capability")
    positives = value.get("positiveDeviceIds", [])
    if (not isinstance(positives, list) or len(positives) != len(set(positives))
            or any(not isinstance(item, str) or not re.fullmatch(r"extaddr:[0-9a-f]{16}", item)
                   for item in positives)):
        raise HealthManifestError("Invalid Unified witness presence context")
    if "absenceOrderingAvailable" in value and type(value["absenceOrderingAvailable"]) is not bool:
        raise HealthManifestError("Invalid Unified absence ordering context")
    if "unresolvedRestChildIdentities" in value and value["unresolvedRestChildIdentities"] is not True:
        raise HealthManifestError("Invalid Unified REST child identity context")
    witness = value.get("absenceWitness")
    if witness is not None:
        if (not isinstance(witness, Mapping) or set(witness) != {"domain", "key", "sourceObservedAt"}
                or witness["domain"] not in DIAGNOSTICS
                or not isinstance(witness["key"], str) or not _DIGEST.fullmatch(witness["key"])):
            raise HealthManifestError("Invalid retained Unified absence witness")
        timestamp(witness["sourceObservedAt"])
        if witness["domain"] == "otbr-restapi" and value.get("unresolvedRestChildIdentities"):
            raise HealthManifestError("Unresolved REST children cannot authorize absence")
    child_coverage = value.get("restChildTableCoverage")
    if child_coverage is not None:
        from otbr_cli_util import canonical_router_rloc16
        from td_unified_dataset import REST_CHILD_TABLE_COVERAGE_VERSION

        builder_digests = {
            digest([
                "unified-v1", builder_contract, dataset.unified_recipe["recipeDigest"],
                dataset.unified_recipe["authorityDigest"],
            ])
            for builder_contract in ("unified-assembly-v10", "unified-assembly-v11")
        }
        if (
            dataset.datasource_id != "multi-source"
            or value["reportContractDigest"] not in builder_digests
            or not isinstance(child_coverage, Mapping)
            or set(child_coverage) != {"contractVersion", "networkInstance", "routers"}
            or child_coverage.get("contractVersion") != REST_CHILD_TABLE_COVERAGE_VERSION
            or not isinstance(child_coverage.get("networkInstance"), str)
            or not re.fullmatch(r"extpan:[0-9a-f]{16}", child_coverage["networkInstance"])
            or not isinstance(child_coverage.get("routers"), list)
            or not child_coverage["routers"]
            or witness is not None and witness["domain"] != "otbr-restapi"
        ):
            raise HealthManifestError("Invalid retained REST child-table coverage")
        previous = None
        for router in child_coverage["routers"]:
            keys = {
                "extAddress", "rloc16", "cliFiles", "cliChildTableFile",
                "cliSourceObservedAt", "cliTimeProvenance", "restFile",
                "restDiagnosticId", "restSourceObservedAt", "childCount", "resolvedChildCount",
                "inputDigests", "scopeDigests",
            }
            if (
                not isinstance(router, Mapping) or set(router) != keys
                or not isinstance(router["extAddress"], str)
                or not re.fullmatch(r"[0-9a-f]{16}", router["extAddress"])
                or router["extAddress"] == "0" * 16
                or not isinstance(router["rloc16"], str)
                or canonical_router_rloc16(router["rloc16"]) != router["rloc16"]
                or not isinstance(router["cliFiles"], list)
                or any(not isinstance(item, str) for item in router["cliFiles"])
                or router["cliFiles"] != sorted(set(router["cliFiles"]))
                or OTBR_CLI_MESHDIAG_ROUTER_CHILDTABLES_FILENAME not in router["cliFiles"]
                or not set(router["cliFiles"]) <= {
                    OTBR_CLI_MESHDIAG_ROUTER_CHILDTABLES_FILENAME,
                    OTBR_CLI_MESHDIAG_ROUTER_NEIGHBORTABLES_FILENAME,
                }
                or router["cliChildTableFile"] != OTBR_CLI_MESHDIAG_ROUTER_CHILDTABLES_FILENAME
                or router["restFile"] != OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME
                or router["cliTimeProvenance"] not in {"embedded", "raw-file-mtime"}
                or not isinstance(router["restDiagnosticId"], str)
                or not router["restDiagnosticId"]
                or type(router["childCount"]) is not int or not 0 <= router["childCount"] <= 511
                or type(router["resolvedChildCount"]) is not int
                or not 0 <= router["resolvedChildCount"] <= router["childCount"]
                or not isinstance(router["inputDigests"], Mapping)
                or not isinstance(router["scopeDigests"], Mapping)
            ):
                raise HealthManifestError("Invalid retained REST child-table router")
            order = (router["rloc16"], router["extAddress"])
            if previous is not None and order <= previous:
                raise HealthManifestError("Duplicate or unordered REST child-table routers")
            previous = order
            files = {
                *router["cliFiles"], OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME,
                OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
                OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
                OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
            }
            if (
                set(router["inputDigests"]) != files or set(router["scopeDigests"]) != files
                or any(not isinstance(item, str) or not _DIGEST.fullmatch(item)
                       for item in [*router["inputDigests"].values(), *router["scopeDigests"].values()])
            ):
                raise HealthManifestError("Invalid retained REST child-table provenance")
            try:
                cli_time = timestamp(router["cliSourceObservedAt"])
                rest_time = timestamp(router["restSourceObservedAt"])
            except (TypeError, AttributeError, ValueError) as exc:
                raise HealthManifestError("Invalid retained REST child-table time") from exc
            if abs((rest_time - cli_time).total_seconds()) > 7200:
                raise HealthManifestError("REST child-table observations are too far apart")
            if witness is not None and router["resolvedChildCount"] != router["childCount"]:
                raise HealthManifestError("Unresolved REST children cannot authorize absence")
            if observation is not None:
                by_name = {source.filename: source for source in observation.sources}
                allowed_states = {"valid", "provisional"} if observation.completeness.value == "partial" else {"valid"}
                if (
                    child_coverage["networkInstance"] != observation.network_id
                    or any(name not in by_name or by_name[name].state not in allowed_states
                           or by_name[name].digest != source_digest
                           for name, source_digest in router["inputDigests"].items())
                    or by_name[router["cliChildTableFile"]].source_observed_at
                    != router["cliSourceObservedAt"]
                ):
                    raise HealthManifestError("REST child-table coverage does not bind original evidence")
    if observation is not None:
        if not retained_source_times:
            originals = [dict(filename=s.filename, digest=s.digest, kind=s.kind, state=s.state,
                              sourceObservedAt=s.source_observed_at) for s in observation.sources
                         if s.filename in safe_sources(dataset)]
            if digest(originals) != value["originalEvidenceFingerprint"]:
                raise HealthManifestError("Unified original evidence fingerprint mismatch")
        if witness is not None and witness != witness_for_sources(
                observation.network_id, observation.sources, witness["domain"]):
            raise HealthManifestError("Unified absence witness does not bind original evidence")
        if witness is not None:
            domain = witness["domain"]
            required = [item for item in dataset.unified_recipe["rawInputs"]
                        if item["source"] == domain and (item["required"]
                                                        or item["role"] in {"identity", "outcome"})]
            by_name = {s.filename: s for s in observation.sources}
            if (observation.completeness.value != "complete" or not required
                    or any(item["file"] not in by_name
                           or by_name[item["file"]].state != "valid"
                           or not by_name[item["file"]].source_observed_at for item in required)):
                raise HealthManifestError("Unified absence authority lacks retained complete coverage")
    return value


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Original source time must include a timezone")
    return parsed.astimezone(timezone.utc)


def witness_for_sources(network_id, sources, domain):
    source = next((s for s in sources if s.filename == DIAGNOSTICS[domain]
                   and s.state == "valid" and s.source_observed_at and _DIGEST.fullmatch(s.digest)), None)
    if source is None:
        return None
    time = timestamp(source.source_observed_at).isoformat()
    return {"domain": domain, "key": digest([network_id, source.digest, time]),
            "sourceObservedAt": time}
