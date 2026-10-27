"""Verified original-evidence and retained Unified health contracts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping

from td_const import OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME, OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME

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


def validate_context(context, dataset, observation=None):
    """Validate retained lineage without consulting today's raw cache."""
    from td_health_manifest import HealthManifestError
    value = context.get("unifiedHealth") if isinstance(context, Mapping) else None
    if (not isinstance(value, Mapping) or value.get("version") != CONTEXT_VERSION
            or value.get("recipe") != plain(dataset.unified_recipe)
            or value.get("recipeContractDigest") != digest(dataset.unified_recipe)
            or value.get("reportContractDigest") not in {digest([
                "unified-v1", builder_contract, dataset.unified_recipe["recipeDigest"],
                dataset.unified_recipe["authorityDigest"],
            ]) for builder_contract in (
                "unified-assembly-v2", "unified-assembly-v3", "unified-assembly-v4", "unified-assembly-v5",
            )}
            or not isinstance(value.get("originalEvidenceFingerprint"), str)
            or not _DIGEST.fullmatch(value["originalEvidenceFingerprint"])
            or not isinstance(value.get("effectiveCoverage"), Mapping)):
        raise HealthManifestError("Invalid retained unifiedHealth context")
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
    witness = value.get("absenceWitness")
    if witness is not None:
        if (not isinstance(witness, Mapping) or set(witness) != {"domain", "key", "sourceObservedAt"}
                or witness["domain"] not in DIAGNOSTICS
                or not isinstance(witness["key"], str) or not _DIGEST.fullmatch(witness["key"])):
            raise HealthManifestError("Invalid retained Unified absence witness")
        timestamp(witness["sourceObservedAt"])
    if observation is not None:
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
