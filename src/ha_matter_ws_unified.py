"""Pure conversion of cached HA Matter inventory and native topology products."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Mapping

from ha_matter_ws_contract import (
    CLUSTER_IDS,
    INTERFACE_TYPE_ENUM,
    MatterWsContractError,
)
from ha_matter_ws_native_topology import MAX_SAFE_JSON_INTEGER, validate_native_topology
from ha_matter_ws_roles import ROLE_FIELDS, ROLE_INPUT_FIELDS, normalize_ha_matter_roles
from ha_matter_ws_snapshots import (
    DASHBOARD_SCHEMA_VERSION,
    NATIVE_SNAPSHOT_SCHEMA_VERSION,
    assert_snapshot_safe,
    build_device_snapshot,
)
from ha_matter_ws_thread import validate_border_router_entries
from ha_matter_ws_topology import _rloc16, _topology_id
from td_device_fields import (
    get_canonical_ext_address,
    get_matter_fabric_node_identity,
    is_placeholder_ext_address,
    normalize_input_record,
)
from td_const import (
    HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME,
    HA_MATTER_WS_DASHBOARD_FILENAME,
    HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME,
    HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_NETWORK_TOPOLOGY_FILENAME,
    HA_MATTER_WS_NETWORK_TOPOLOGY_OUTCOME_FILENAME,
    HA_MATTER_WS_THREAD_BORDER_ROUTERS_FILENAME,
    HA_MATTER_WS_THREAD_BORDER_ROUTERS_OUTCOME_FILENAME,
    HA_MATTER_WS_TOPOLOGY_FILENAME,
)
from td_network_identity import canonical_ext_pan_id
from td_record_merge import append_merge_conflict


HaTransportKind = Literal["thread", "non-thread", "unknown", "conflicting"]


@dataclass(frozen=True)
class HaTransportEvidence:
    source: str
    observation: str
    endpoint_id: int | None = None
    cluster_id: int | None = None
    attribute_id: int | None = None
    interface_type: str | None = None
    network_type: str | None = None


@dataclass(frozen=True)
class HaTransportClassification:
    classification: HaTransportKind
    reason_codes: tuple[str, ...]
    evidence: tuple[HaTransportEvidence, ...]


_NON_THREAD_INTERFACE_TYPES = frozenset({"WiFi", "Ethernet", "Cellular"})
_KNOWN_INTERFACE_TYPES = frozenset(INTERFACE_TYPE_ENUM.values())
_NETWORK_INTERFACES_CLUSTER_ID = CLUSTER_IDS["GeneralDiagnostics"]
_THREAD_DIAGNOSTICS_CLUSTER_ID = CLUSTER_IDS["ThreadNetworkDiagnostics"]
_WIFI_DIAGNOSTICS_CLUSTER_ID = CLUSTER_IDS["WiFiNetworkDiagnostics"]
_ETHERNET_DIAGNOSTICS_CLUSTER_ID = CLUSTER_IDS["EthernetNetworkDiagnostics"]
_DESCRIPTOR_CLUSTER_ID = CLUSTER_IDS["Descriptor"]


def _transport_result(
    classification: HaTransportKind,
    reason_codes: Iterable[str],
    evidence: Iterable[HaTransportEvidence],
) -> HaTransportClassification:
    return HaTransportClassification(
        classification=classification,
        reason_codes=tuple(sorted(set(reason_codes))),
        evidence=tuple(
            sorted(
                set(evidence),
                key=lambda item: (
                    item.source,
                    item.observation,
                    -1 if item.endpoint_id is None else item.endpoint_id,
                    -1 if item.cluster_id is None else item.cluster_id,
                    -1 if item.attribute_id is None else item.attribute_id,
                    item.interface_type or "",
                    item.network_type or "",
                ),
            )
        ),
    )


def _interface_coverage_state(record: Mapping[str, Any]) -> str | None:
    coverage = record.get("diagnosticCoverage")
    general = coverage.get("generalDiagnostics") if isinstance(coverage, Mapping) else None
    attributes = general.get("attributes") if isinstance(general, Mapping) else None
    state = (
        attributes.get("networkInterfaces")
        if isinstance(attributes, Mapping)
        else None
    )
    return state if isinstance(state, str) else None


def _root_server_clusters(record: Mapping[str, Any]) -> set[int] | None:
    endpoints = record.get("endpoints")
    if not isinstance(endpoints, list):
        return None
    roots = [
        endpoint
        for endpoint in endpoints
        if isinstance(endpoint, Mapping)
        and type(endpoint.get("endpointId")) is int
        and endpoint["endpointId"] == 0
    ]
    if len(roots) != 1:
        return None
    clusters = roots[0].get("serverClusters")
    if (
        not isinstance(clusters, list)
        or not clusters
        or any(type(cluster_id) is not int or cluster_id < 0 for cluster_id in clusters)
        or len(clusters) != len(set(clusters))
        or _DESCRIPTOR_CLUSTER_ID not in clusters
    ):
        return None
    coverage = record.get("diagnosticCoverage")
    general = coverage.get("generalDiagnostics") if isinstance(coverage, Mapping) else None
    invalid_values = (
        general.get("invalidValues") if isinstance(general, Mapping) else None
    )
    if isinstance(invalid_values, Mapping) and "0/29/1" in invalid_values:
        return None
    return set(clusters)


def _thread_diagnostic_paths(record: Mapping[str, Any]) -> tuple[bool, bool]:
    thread = record.get("thread")
    details = thread.get("diagnosticsDetail") if isinstance(thread, Mapping) else None
    if not isinstance(details, Mapping):
        details = record.get("diagnosticsDetail")
    if not isinstance(details, Mapping):
        return False, False
    values = details.get("threadNetworkDiagnostics")
    has_observation = isinstance(values, Mapping) and bool(values)
    unknown_values = details.get("unknownAttributes")
    if isinstance(unknown_values, Mapping):
        has_observation = has_observation or any(
            re.fullmatch(r"0/53/[0-9]+", path) is not None
            for path in unknown_values
            if isinstance(path, str)
        )
    errors = details.get("readErrors")
    has_read_error = isinstance(errors, Mapping) and any(
        re.fullmatch(r"0/53/[0-9]+", path) is not None
        for path in errors
        if isinstance(path, str)
    )
    return has_observation, has_read_error


def _interface_views(record: Mapping[str, Any]) -> tuple[list[Any] | None, list[Any] | None]:
    primary = record.get("networkInterfaces")
    general = record.get("generalDiagnostics")
    nested = general.get("networkInterfaces") if isinstance(general, Mapping) else None
    return (
        primary if isinstance(primary, list) else None,
        nested if isinstance(nested, list) else None,
    )


def classify_ha_transport(
    record: Mapping[str, Any], *, source: str = "record"
) -> HaTransportClassification:
    """Classify cached transport evidence without changing the source record."""

    if not isinstance(record, Mapping):
        raise MatterWsContractError("Expected a normalized HA transport record")
    evidence: list[HaTransportEvidence] = []
    thread_reasons: set[str] = set()
    non_thread_reasons: set[str] = set()
    unresolved = False
    read_error = False

    def add(
        observation: str,
        *,
        endpoint_id: int | None = None,
        cluster_id: int | None = None,
        attribute_id: int | None = None,
        interface_type: str | None = None,
        network_type: str | None = None,
    ) -> None:
        evidence.append(
            HaTransportEvidence(
                source=source if isinstance(source, str) and source else "record",
                observation=observation,
                endpoint_id=endpoint_id,
                cluster_id=cluster_id,
                attribute_id=attribute_id,
                interface_type=interface_type,
                network_type=network_type,
            )
        )

    root_clusters = _root_server_clusters(record)
    if root_clusters is not None:
        if _THREAD_DIAGNOSTICS_CLUSTER_ID in root_clusters:
            thread_reasons.add("thread-diagnostics-present")
            add(
                "root-server-list",
                endpoint_id=0,
                cluster_id=_THREAD_DIAGNOSTICS_CLUSTER_ID,
            )
        if (
            _WIFI_DIAGNOSTICS_CLUSTER_ID in root_clusters
            or _ETHERNET_DIAGNOSTICS_CLUSTER_ID in root_clusters
        ):
            if _THREAD_DIAGNOSTICS_CLUSTER_ID not in root_clusters:
                non_thread_reasons.add("non-thread-root-clusters-only")
            for cluster_id in (_WIFI_DIAGNOSTICS_CLUSTER_ID, _ETHERNET_DIAGNOSTICS_CLUSTER_ID):
                if cluster_id in root_clusters:
                    add(
                        "root-server-list",
                        endpoint_id=0,
                        cluster_id=cluster_id,
                    )

    has_thread_diagnostics, has_thread_read_error = _thread_diagnostic_paths(record)
    if has_thread_diagnostics:
        thread_reasons.add("thread-diagnostics-present")
        add(
            "thread-diagnostics",
            endpoint_id=0,
            cluster_id=_THREAD_DIAGNOSTICS_CLUSTER_ID,
        )
    if has_thread_read_error:
        unresolved = True
        read_error = True
        add(
            "thread-diagnostics-read-error",
            endpoint_id=0,
            cluster_id=_THREAD_DIAGNOSTICS_CLUSTER_ID,
        )

    state = _interface_coverage_state(record)
    primary_interfaces, nested_interfaces = _interface_views(record)
    if (
        primary_interfaces is not None
        and nested_interfaces is not None
        and primary_interfaces != nested_interfaces
        and state in {"populated", "implementedEmpty"}
    ):
        add(
            "inconsistent-interface-projections",
            cluster_id=_NETWORK_INTERFACES_CLUSTER_ID,
            attribute_id=0,
        )
        return _transport_result(
            "conflicting", ("transport-evidence-conflict",), evidence
        )

    interfaces = primary_interfaces if primary_interfaces is not None else nested_interfaces
    if state == "readError":
        unresolved = True
        read_error = True
        add(
            "network-interface-read-error",
            endpoint_id=0,
            cluster_id=_NETWORK_INTERFACES_CLUSTER_ID,
            attribute_id=0,
        )
    elif state in {"null", "invalidValue", "attributeUnsupported"}:
        unresolved = True
        add(
            "network-interface-incomplete",
            endpoint_id=0,
            cluster_id=_NETWORK_INTERFACES_CLUSTER_ID,
            attribute_id=0,
        )
    elif state in {"populated", "implementedEmpty"} and interfaces is None:
        unresolved = True
    elif state in {"populated", "implementedEmpty"} and interfaces is not None:
        add(
            "network-interface-list",
            endpoint_id=0,
            cluster_id=_NETWORK_INTERFACES_CLUSTER_ID,
            attribute_id=0,
        )
        interface_types: list[str] = []
        valid_entries = True
        for interface in interfaces:
            if not isinstance(interface, Mapping):
                valid_entries = False
                continue
            interface_type = interface.get("interfaceType")
            if type(interface_type) is not str or interface_type not in _KNOWN_INTERFACE_TYPES:
                valid_entries = False
                continue
            interface_types.append(interface_type)
            add(
                "network-interface",
                endpoint_id=0,
                cluster_id=_NETWORK_INTERFACES_CLUSTER_ID,
                attribute_id=0,
                interface_type=interface_type,
            )
        if "Thread" in interface_types:
            thread_reasons.add("thread-interface-present")
        if (
            interfaces
            and valid_entries
            and interface_types
            and all(value in _NON_THREAD_INTERFACE_TYPES for value in interface_types)
        ):
            non_thread_reasons.add("non-thread-interfaces-only")
        elif not valid_entries:
            unresolved = True
    elif interfaces is not None:
        unresolved = True
        if interfaces:
            add("network-interface-unqualified", endpoint_id=0,
                cluster_id=_NETWORK_INTERFACES_CLUSTER_ID, attribute_id=0)

    details = record.get("diagnosticsDetail")
    native_br = details.get("nativeBorderRouter") if isinstance(details, Mapping) else None
    if isinstance(native_br, Mapping) and native_br:
        thread_reasons.add("native-thread-node")
        add("native-border-router", network_type="thread")

    native_topology = details.get("nativeTopology") if isinstance(details, Mapping) else None
    native_node = (
        native_topology.get("node")
        if isinstance(native_topology, Mapping)
        else None
    )
    if isinstance(native_node, Mapping):
        network_type = native_node.get("network_type")
        if network_type == "thread":
            thread_reasons.add("native-thread-node")
            add("native-topology-node", network_type="thread")
        elif network_type in {"wifi", "ethernet"}:
            non_thread_reasons.add("native-non-thread-node")
            add("native-topology-node", network_type=network_type)
        else:
            unresolved = True
            add("native-topology-unknown")

    if thread_reasons:
        return _transport_result("thread", thread_reasons, evidence)
    if read_error:
        return _transport_result(
            "unknown", ("transport-read-error",), evidence
        )
    if unresolved:
        return _transport_result(
            "unknown", ("insufficient-transport-evidence",), evidence
        )
    if non_thread_reasons:
        return _transport_result("non-thread", non_thread_reasons, evidence)
    return _transport_result(
        "unknown", ("insufficient-transport-evidence",), evidence
    )


def combine_ha_transport_evidence(
    observations: Iterable[HaTransportClassification],
) -> HaTransportClassification:
    """Combine results only after the caller has correlated their identities."""

    items = tuple(observations)
    evidence = tuple(entry for item in items for entry in item.evidence)
    reasons = {reason for item in items for reason in item.reason_codes}
    classes = {item.classification for item in items}
    if not items:
        return _transport_result(
            "unknown", ("insufficient-transport-evidence",), ()
        )
    if "conflicting" in classes:
        return _transport_result(
            "conflicting", reasons | {"transport-evidence-conflict"}, evidence
        )
    if "thread" in classes:
        return _transport_result("thread", reasons, evidence)
    if "unknown" in classes:
        if not reasons:
            reasons.add("insufficient-transport-evidence")
        return _transport_result("unknown", reasons, evidence)
    return _transport_result("non-thread", reasons, evidence)


HA_TRANSPORT_FILTER_VERSION = "ha-transport-admission-v1"
HA_THREAD_EVIDENCE_FILTER_VERSION = "ha-thread-evidence-admission-v2"


def _thread_topology_evidence(
    inputs: list[tuple[str, list[dict]]],
) -> dict[tuple[str, int], HaTransportEvidence]:
    result: dict[tuple[str, int], HaTransportEvidence] = {}
    for filename, records in inputs:
        if filename != HA_MATTER_WS_TOPOLOGY_FILENAME:
            continue
        by_id: dict[str, list[tuple[int, dict]]] = {}
        for index, record in enumerate(records):
            topology_id = record.get("topologyId")
            if isinstance(topology_id, str) and topology_id:
                by_id.setdefault(topology_id, []).append((index, record))
        for reporter_index, reporter in enumerate(records):
            reporter_id = reporter.get("topologyId")
            matter_id = reporter.get("matterId")
            network = reporter.get("extPanId")
            if (
                not isinstance(reporter_id, str)
                or len(by_id.get(reporter_id, [])) != 1
                or not isinstance(matter_id, str)
                or not matter_id
                or not get_matter_fabric_node_identity(reporter)
                or get_matter_fabric_node_identity(reporter)
                != get_matter_fabric_node_identity({"matterId": matter_id})
                or network is None
                or classify_ha_transport(reporter).classification != "thread"
            ):
                continue
            route = reporter.get("route")
            relationships = [
                *(reporter.get("routerNeighbors") or []),
                *(reporter.get("children") or []),
                *((route.get("routeData") or []) if isinstance(route, dict) else []),
            ]
            for relationship in relationships:
                if not isinstance(relationship, dict) or relationship.get("identityConflicts"):
                    continue
                target_id = relationship.get("targetId")
                targets = by_id.get(target_id, []) if isinstance(target_id, str) else []
                if relationship.get("sourceId") != reporter_id or len(targets) != 1:
                    continue
                target_index, target = targets[0]
                if (
                    target.get("relationshipOnly") is not True
                    or target.get("extPanId") is None
                    or _ext_pan_id(target["extPanId"]) != _ext_pan_id(network)
                ):
                    continue
                target_address = get_canonical_ext_address(target)
                if is_placeholder_ext_address(target_address) or not re.fullmatch(r"[0-9a-f]{16}", target_address):
                    target_address = ""
                target_rloc = _rloc16(target.get("rloc16"))
                if not target_address and not target_rloc:
                    continue
                if target_address and sum(
                    get_canonical_ext_address(node) == target_address
                    and node.get("extPanId") is not None
                    and _ext_pan_id(node["extPanId"]) == _ext_pan_id(network)
                    for node in records
                ) != 1:
                    continue
                observations = relationship.get("observations")
                if not isinstance(observations, list):
                    continue
                for observation in observations:
                    if not isinstance(observation, dict):
                        continue
                    entry = observation.get("entry")
                    if (
                        observation.get("source") not in {
                            "ThreadNetworkDiagnostics.NeighborTable",
                            "ThreadNetworkDiagnostics.RouteTable",
                        }
                        or observation.get("reporterMatterId") != matter_id
                        or observation.get("sourceId") != reporter_id
                        or observation.get("targetId") != target_id
                        or not isinstance(entry, dict)
                        or (observation.get("source") == "ThreadNetworkDiagnostics.RouteTable"
                            and entry.get("allocated") is False)
                    ):
                        continue
                    entry_address = get_canonical_ext_address(entry)
                    if target_address:
                        if entry_address != target_address:
                            continue
                    elif (_rloc16(entry.get("rloc16")) != target_rloc
                          or sum(
                              _rloc16(node.get("rloc16")) == target_rloc
                              and node.get("extPanId") is not None
                              and _ext_pan_id(node["extPanId"]) == _ext_pan_id(network)
                              for node in records
                          ) != 1):
                        continue
                    result[(filename, target_index)] = HaTransportEvidence(
                        source=f"{filename}#{reporter_index}",
                        observation="thread-topology-relationship",
                        network_type="thread",
                    )
                    break
    return result


def _same_ha_device(left: dict, right: dict) -> bool:
    left_network = _ext_pan_id(left["extPanId"]) if left.get("extPanId") is not None else None
    right_network = _ext_pan_id(right["extPanId"]) if right.get("extPanId") is not None else None
    if left_network and right_network and left_network != right_network:
        return False
    left_matter = get_matter_fabric_node_identity(left)
    right_matter = get_matter_fabric_node_identity(right)
    if left_matter and right_matter:
        return left_matter == right_matter
    left_address = get_canonical_ext_address(left)
    right_address = get_canonical_ext_address(right)
    return (
        not is_placeholder_ext_address(left_address)
        and bool(re.fullmatch(r"[0-9a-f]{16}", left_address))
        and left_address == right_address
        and bool(left_network) and left_network == right_network
    )


def admit_ha_records(
    inputs: list[tuple[str, list[dict]]],
    *,
    thread_evidence_only: bool = False,
) -> tuple[dict[str, list[dict]], dict]:
    """Admit source-local observations without altering raw records or inventing identities."""
    assert_snapshot_safe(inputs)
    if len({filename for filename, _ in inputs}) != len(inputs):
        raise MatterWsContractError("Duplicate HA transport input filename")
    flat = [(filename, index, record) for filename, records in inputs
            for index, record in enumerate(records)]
    for _, records in inputs:
        validate_canonical_rows(records)
        for record in records:
            if record.get("extPanId") is not None:
                _ext_pan_id(record["extPanId"])
    classifications = [
        classify_ha_transport(record, source=f"{filename}#{index}")
        for filename, index, record in flat
    ]
    topology_evidence = _thread_topology_evidence(inputs) if thread_evidence_only else {}
    for position, (filename, index, _) in enumerate(flat):
        evidence = topology_evidence.get((filename, index))
        if evidence is not None:
            classifications[position] = combine_ha_transport_evidence((
                classifications[position],
                _transport_result("thread", ("thread-topology-relationship",), (evidence,)),
            ))
    decisions = []
    for position, (_, _, record) in enumerate(flat):
        matches = [index for index, (_, _, candidate) in enumerate(flat)
                   if index == position or _same_ha_device(record, candidate)]
        fabrics = {get_matter_fabric_node_identity(flat[index][2]) for index in matches}
        fabrics.discard("")
        if len(fabrics) > 1:
            matches = [position]
        evidence = [classifications[index] for index in matches
                    if classifications[index].classification != "unknown"
                    or classifications[index].evidence]
        # Sparse projections inherit observed transport, never the absence of evidence.
        decision = combine_ha_transport_evidence(evidence or [classifications[position]])
        addresses = {get_canonical_ext_address(flat[index][2]) for index in matches}
        addresses = {address for address in addresses if not is_placeholder_ext_address(address)}
        if len(addresses) > 1:
            decision = _transport_result(
                "conflicting", (*decision.reason_codes, "transport-identity-conflict"),
                decision.evidence,
            )
        decisions.append(decision)
    def excluded(decision: HaTransportClassification) -> bool:
        return (decision.classification != "thread" if thread_evidence_only
                else decision.classification == "non-thread")

    excluded_native = {
        native_id for (_, _, record), decision in zip(flat, decisions, strict=True)
        if excluded(decision) for native_id in record.get("nativeNodeIds", [])
    }
    excluded_native -= {
        native_id for (_, _, record), decision in zip(flat, decisions, strict=True)
        if not excluded(decision) for native_id in record.get("nativeNodeIds", [])
    }
    admitted: dict[str, list[dict]] = {filename: [] for filename, _ in inputs}
    metadata = {
        filename: {"filename": filename, "recordCount": len(records),
                   "admittedRecordCount": 0, "excludedRecordCount": 0,
                   "unknownRecordCount": 0, "conflictingRecordCount": 0,
                   "decisions": [], "filteredLinks": []}
        for filename, records in inputs
    }
    for (filename, index, original), decision in zip(flat, decisions, strict=True):
        record = deepcopy(original)
        links = []
        for link in record.get("nativeRelationships", []):
            filtered_endpoints = sorted({
                link["nativeSourceId"], link["nativeTargetId"],
            } & excluded_native)
            remove = (
                excluded(decision)
                or link["networkType"] in {"wifi", "ethernet"}
                or record.get("relationshipOnly") is True
                and len(filtered_endpoints) == 2
            )
            if remove or filtered_endpoints:
                metadata[filename]["filteredLinks"].append({
                    "recordIndex": index, "nativeSourceId": link["nativeSourceId"],
                    "nativeTargetId": link["nativeTargetId"], "networkType": link["networkType"],
                    "disposition": "excluded" if remove else "unresolved",
                    "reasonCode": (
                        ("non-thread-relationship" if remove else "filtered-non-thread-endpoint")
                        if not thread_evidence_only else
                        "non-thread-relationship" if link["networkType"] in {"wifi", "ethernet"} else
                        "missing-thread-evidence" if remove else "filtered-endpoint-without-thread-evidence"
                    ),
                })
            if not remove:
                if filtered_endpoints:
                    link["filteredEndpoints"] = filtered_endpoints
                links.append(link)
        if "nativeRelationships" in record:
            record["nativeRelationships"] = links
        if (not thread_evidence_only and record.get("relationshipOnly") is True
                and original.get("nativeRelationships") and not links):
            decision = _transport_result(
                "non-thread", (*decision.reason_codes, "non-thread-relationships-only"),
                decision.evidence,
            )
        info = metadata[filename]
        representative_evidence = {}
        for evidence in decision.evidence:
            key = (evidence.observation, evidence.endpoint_id, evidence.cluster_id,
                   evidence.attribute_id, evidence.interface_type, evidence.network_type)
            representative_evidence.setdefault(key, asdict(evidence))
        decision_record = {
            "recordIndex": index, "classification": decision.classification,
            "reasonCodes": list(decision.reason_codes),
            "evidence": list(representative_evidence.values()),
        }
        if thread_evidence_only:
            decision_record["disposition"] = "excluded" if excluded(decision) else "admitted"
        info["decisions"].append(decision_record)
        if excluded(decision):
            info["excludedRecordCount"] += 1
        else:
            admitted[filename].append(record)
            info["admittedRecordCount"] += 1
        if decision.classification in {"unknown", "conflicting"}:
            info[f"{decision.classification}RecordCount"] += 1
    report = {"contractVersion": (HA_THREAD_EVIDENCE_FILTER_VERSION if thread_evidence_only
                                  else HA_TRANSPORT_FILTER_VERSION),
              "inputs": list(metadata.values())}
    return admitted, report


def validate_ha_transport_filtering(report: Any) -> None:
    if (not isinstance(report, dict)
            or set(report) != {"contractVersion", "inputs"}
            or report["contractVersion"] not in {
                HA_TRANSPORT_FILTER_VERSION, HA_THREAD_EVIDENCE_FILTER_VERSION,
            }
            or not isinstance(report["inputs"], list)):
        raise MatterWsContractError("Invalid HA transport admission report")
    filenames = set()
    for item in report["inputs"]:
        if (not isinstance(item, dict) or set(item) != {
            "filename", "recordCount", "admittedRecordCount", "excludedRecordCount",
            "unknownRecordCount", "conflictingRecordCount", "decisions", "filteredLinks",
        } or not isinstance(item["filename"], str) or item["filename"] in filenames
                or any(type(item[key]) is not int or item[key] < 0 for key in (
                    "recordCount", "admittedRecordCount", "excludedRecordCount",
                    "unknownRecordCount", "conflictingRecordCount",
                ))
                or not isinstance(item["decisions"], list)
                or not isinstance(item["filteredLinks"], list)):
            raise MatterWsContractError("Invalid HA transport input counts")
        filenames.add(item["filename"])
        counts = {kind: 0 for kind in ("thread", "non-thread", "unknown", "conflicting")}
        thread_evidence_only = report["contractVersion"] == HA_THREAD_EVIDENCE_FILTER_VERSION
        for index, decision in enumerate(item["decisions"]):
            if (not isinstance(decision, dict)
                    or set(decision) != ({"recordIndex", "classification", "reasonCodes", "evidence"}
                                         | ({"disposition"} if thread_evidence_only else set()))
                    or type(decision["recordIndex"]) is not int or decision["recordIndex"] != index
                    or not isinstance(decision["classification"], str)
                    or decision["classification"] not in counts
                    or not isinstance(decision["reasonCodes"], list) or not decision["reasonCodes"]
                    or any(not isinstance(reason, str) or not reason for reason in decision["reasonCodes"])
                    or not isinstance(decision["evidence"], list)
                    or any(not isinstance(value, dict) or set(value) != {
                        "source", "observation", "endpoint_id", "cluster_id", "attribute_id",
                        "interface_type", "network_type",
                    } for value in decision["evidence"])):
                raise MatterWsContractError("Invalid HA transport decision")
            if thread_evidence_only and decision["disposition"] != (
                "admitted" if decision["classification"] == "thread" else "excluded"
            ):
                raise MatterWsContractError("Invalid HA transport disposition")
            counts[decision["classification"]] += 1
            for value in decision["evidence"]:
                if (any(not isinstance(value[key], str) or not value[key]
                        for key in ("source", "observation"))
                        or any(value[key] is not None and (
                            type(value[key]) is not int or not 0 <= value[key] <= maximum
                        ) for key, maximum in (
                            ("endpoint_id", 65534), ("cluster_id", 2**32 - 1),
                            ("attribute_id", 2**32 - 1),
                        ))
                        or value["interface_type"] is not None and (
                            not isinstance(value["interface_type"], str)
                            or value["interface_type"] not in _KNOWN_INTERFACE_TYPES
                        )
                        or value["network_type"] is not None and (
                            not isinstance(value["network_type"], str)
                            or value["network_type"] not in {"thread", "wifi", "ethernet"}
                        )):
                    raise MatterWsContractError("Invalid HA transport evidence reference")
        if (len(item["decisions"]) != item["recordCount"]
                or (item["recordCount"] - counts["thread"] if thread_evidence_only
                    else counts["non-thread"]) != item["excludedRecordCount"]
                or (counts["thread"] if thread_evidence_only
                    else item["recordCount"] - counts["non-thread"]) != item["admittedRecordCount"]
                or counts["unknown"] != item["unknownRecordCount"]
                or counts["conflicting"] != item["conflictingRecordCount"]):
            raise MatterWsContractError("HA transport counts do not reconcile")
        for link in item["filteredLinks"]:
            if (not isinstance(link, dict) or set(link) != {
                "recordIndex", "nativeSourceId", "nativeTargetId", "networkType",
                "disposition", "reasonCode",
            } or type(link["recordIndex"]) is not int
                    or not 0 <= link["recordIndex"] < item["recordCount"]
                    or not isinstance(link["disposition"], str)
                    or link["disposition"] not in {"excluded", "unresolved"}
                    or any(not isinstance(link[key], str) or not link[key]
                           for key in ("nativeSourceId", "nativeTargetId", "networkType", "reasonCode"))):
                raise MatterWsContractError("Invalid HA filtered relationship")


def _wrapper(payload: Any, source: str, field: str) -> Any:
    if (not isinstance(payload, dict)
            or payload.get("schemaVersion") != NATIVE_SNAPSHOT_SCHEMA_VERSION
            or payload.get("source") != source or field not in payload):
        raise MatterWsContractError(f"Invalid cached {source} envelope")
    assert_snapshot_safe(payload)
    return payload[field]


def _without_role_conflicts(record: Any) -> Any:
    if not isinstance(record, dict):
        return record
    result = deepcopy(record)
    conflicts = result.pop("_merge_conflicts", [])
    if not isinstance(conflicts, list) or any(
        not isinstance(item, dict) or set(item) != {"path", "current", "incoming"}
        or item["path"] not in ROLE_FIELDS
        or type(item["current"]) is not bool or type(item["incoming"]) is not bool
        for item in conflicts
    ):
        raise MatterWsContractError("Invalid cached native role conflicts")
    return result


def _roles(record: dict, original: dict, *, is_thread: bool,
           border_router: bool = False) -> dict:
    if "_merge_conflicts" in original:
        record["_merge_conflicts"] = deepcopy(original["_merge_conflicts"])
    return normalize_ha_matter_roles(
        record, thread_role=record.get("role"), is_thread=is_thread,
        border_router=border_router,
    )


def _native_id(record: dict, native_id: str) -> str:
    address = get_canonical_ext_address(record)
    if record.get("extPanId") and not is_placeholder_ext_address(address):
        return _topology_id(record)
    return f"ha-native:{native_id}"


def _ext_pan_id(value: Any) -> str:
    try:
        return canonical_ext_pan_id(value)
    except ValueError as exc:
        raise MatterWsContractError(f"Invalid native Thread identity: {exc}") from exc


def normalize_inventory(payload: Any) -> list[dict]:
    """Preserve every commissioned device and its complete safe snapshot fields."""
    if not isinstance(payload, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("matter"), dict)
        or not isinstance(row["matter"].get("matterId"), str)
        or not row["matter"]["matterId"]
        for row in payload
    ):
        raise MatterWsContractError("Expected commissioned Matter device snapshots")
    assert_snapshot_safe(payload)
    records = deepcopy(payload)
    rows = []
    for record in records:
        matter = record["matter"]
        for field in ("endpoints", "deviceTypes", "serverClusters"):
            record.setdefault(field, deepcopy(matter.get(field, [])))
        thread = record.get("thread")
        if isinstance(thread, dict) and thread.get("extendedPanId") is not None:
            observed = _ext_pan_id(thread["extendedPanId"])
            if record.get("extPanId") is not None and _ext_pan_id(record["extPanId"]) != observed:
                raise MatterWsContractError("Inventory Thread identity contradicts its device")
            record["extPanId"] = observed
        normalized = normalize_input_record(record, source="ha-matter-ws")
        derived = build_device_snapshot([normalized])[0]
        row = {**derived, **normalized,
               "matter": {**derived["matter"], **normalized["matter"]}}
        if "_merge_conflicts" in derived:
            row["_merge_conflicts"] = derived["_merge_conflicts"]
        rows.append(row)
    return rows


def normalize_border_routers(payload: Any) -> list[dict]:
    """Map validated native Border Routers without promoting IPv4 to IPv6."""
    entries = _wrapper(payload, "ha-matter-ws-thread-border-routers", "borderRouters")
    if not isinstance(entries, list):
        raise MatterWsContractError("Expected native Border Router entries")
    validated = validate_border_router_entries([_without_role_conflicts(row) for row in entries])
    rows = []
    mapping = {
        "extAddressHex": "extAddress", "extendedPanIdHex": "extPanId",
        "networkName": "networkName", "vendorName": "vendorName",
        "modelName": "vendorModel", "swVersion": "vendorSwVersion",
        "threadVersion": "threadVersion",
    }
    for native, original in zip(validated, entries, strict=True):
        row = {canonical: native[key] for key, canonical in mapping.items() if key in native}
        if "extPanId" in row:
            row["extPanId"] = _ext_pan_id(row["extPanId"])
        row["type"] = "threadDevice"
        row["ipv6Addresses"] = list(dict.fromkeys(
            str(ipaddress.IPv6Address(address)) for address in native["addresses"]
            if ipaddress.ip_address(address).version == 6
        ))
        row["diagnosticsDetail"] = {"nativeBorderRouter": deepcopy(native)}
        for field in ROLE_INPUT_FIELDS:
            if field in native:
                row[field] = native[field]
        row = _roles(row, original, is_thread=True, border_router=True)
        row = normalize_input_record(row, source="ha-matter-ws")
        row["topologyId"] = _native_id(row, f"br:{get_canonical_ext_address(row)}")
        row["id"] = row["topologyId"]
        rows.append(row)
    assert_snapshot_safe(rows)
    return rows


def normalize_native_topology(payload: Any) -> list[dict]:
    """Retain typed native links, including unresolved endpoints, without OTBR tables."""
    graph = _wrapper(payload, "ha-matter-ws-network-topology", "topology")
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        raise MatterWsContractError("Expected native topology graph")
    clean = {**graph, "nodes": [_without_role_conflicts(node) for node in graph["nodes"]]}
    validated = validate_native_topology(clean, allow_dangling_connections=True)
    rows: list[dict] = []
    by_native_id: dict[str, dict] = {}
    mapping = {
        "ext_address": "extAddress", "ext_pan_id": "extPanId",
        "network_name": "networkName", "vendor_name": "vendorName",
        "model_name": "vendorModel", "available": "available", "is_bridge": "isBridge",
    }
    for native, original in zip(validated["nodes"], graph["nodes"], strict=True):
        is_thread = native["network_type"] == "thread"
        row = {canonical: native[key] for key, canonical in mapping.items() if key in native}
        if "extPanId" in row:
            row["extPanId"] = _ext_pan_id(row["extPanId"])
        if "rloc16" in native:
            row["rloc16"] = f"0x{native['rloc16']:04x}"
        if is_thread and "role" in native:
            row["role"] = native["role"]
        for field in ROLE_INPUT_FIELDS:
            if field in native:
                row[field] = native[field]
        row["type"] = "threadDevice" if is_thread else (
            "matterDevice" if native["kind"] == "matter" else "nativeDevice"
        )
        row["nativeNodeIds"] = [native["id"]]
        row["diagnosticsDetail"] = {"nativeTopology": {
            "node": deepcopy(native), "collectedAt": validated["collected_at"],
        }}
        row = _roles(row, original, is_thread=is_thread,
                     border_router=is_thread and native["kind"] == "border_router")
        row = normalize_input_record(row, source="ha-matter-ws")
        row["topologyId"] = _native_id(row, native["id"])
        row["id"] = row["topologyId"]
        row["nativeRelationships"] = []
        rows.append(row)
        by_native_id[native["id"]] = row
    by_canonical_id: dict[str, list[dict]] = {}
    for row in rows:
        by_canonical_id.setdefault(row["topologyId"], []).append(row)
    for candidates in by_canonical_id.values():
        if len(candidates) > 1:
            for row in candidates:
                append_merge_conflict(row, "nativeNodeIds.ambiguousIdentity",
                                      row["topologyId"], row["nativeNodeIds"])
                row["topologyId"] = f"ha-native:{row['nativeNodeIds'][0]}"
                row["id"] = row["topologyId"]
    seen = set()
    for connection in validated["connections"]:
        fingerprint = json.dumps(connection, sort_keys=True, separators=(",", ":"))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        source = by_native_id.get(connection["source"])
        target = by_native_id.get(connection["target"])
        link = {
            "sourceId": source["topologyId"] if source else f"ha-native:{connection['source']}",
            "targetId": target["topologyId"] if target else f"ha-native:{connection['target']}",
            "networkType": connection["network"],
            "nativeSourceId": connection["source"], "nativeTargetId": connection["target"],
            "strength": connection["strength"],
            "observations": [{"source": "nativeTopology", "collectedAt": validated["collected_at"]}],
        }
        for key, canonical in (
            ("source_to_target", "sourceToTarget"), ("target_to_source", "targetToSource"),
            ("via_route_table", "viaRouteTable"), ("path_cost", "pathCost"),
            ("extensions", "extensions"),
        ):
            if key in connection:
                link[canonical] = deepcopy(connection[key])
        unresolved = [connection[key] for key in ("source", "target")
                      if connection[key] not in by_native_id]
        owner = source if source is not None else target
        if owner is None:
            identity = "ha-native-link:" + hashlib.sha256(fingerprint.encode()).hexdigest()
            owner = {"id": identity, "topologyId": identity, "type": "nativeRelationship",
                     "relationshipOnly": True, "nativeNodeIds": [], "nativeRelationships": []}
            rows.append(owner)
        if unresolved:
            link["unresolvedEndpoints"] = unresolved
            append_merge_conflict(owner, "nativeRelationships.unresolvedEndpoints", None, unresolved)
        owner["nativeRelationships"].append(link)
    assert_snapshot_safe(rows)
    return rows


def is_thread_record(record: dict) -> bool:
    if record.get("type") == "threadDevice":
        return True
    if record.get("type") in {"matterDevice", "nativeDevice", "nativeRelationship"}:
        return False
    return bool(record.get("extAddress") or record.get("rloc16") or record.get("extPanId"))


def native_observation_epoch(extractor: str, payload: Any) -> float | None:
    """Use upstream graph/discovery time, never wrapper read time, for native rows."""
    if not isinstance(payload, dict):
        return None
    if extractor == "ha-native-topology":
        graph = payload.get("topology")
        values = [graph.get("collected_at")] if isinstance(graph, dict) else []
    else:
        entries = payload.get("borderRouters")
        if not isinstance(entries, list):
            return None
        if not entries:
            return None
        values = [entry.get("lastSeen") if isinstance(entry, dict) else None for entry in entries]
    if not values or any(type(value) is not int or not 0 < value <= MAX_SAFE_JSON_INTEGER
                         for value in values):
        return None
    return min(values) / 1000


def controller_observation_time(
    payload: Any, *, filename: str, content_digest: str | None,
    outcome: Any, now: datetime,
) -> tuple[str | None, str] | None:
    """Validate controller receipt evidence without making it a measurement time."""
    records = payload if isinstance(payload, list) else [payload]
    if isinstance(payload, dict) and "devices" in payload:
        records = [payload]
        for field in ("devices", "diagnostics", "meshDiagnostics", "topology"):
            values = payload.get(field)
            if not isinstance(values, list):
                raise MatterWsContractError(f"Invalid cached HA dashboard {field}")
            records.extend(values)
    timed = [record for record in records
             if isinstance(record, dict) and record.get("relationshipOnly") is not True]
    bindings = outcome.get("artifactObservations") if isinstance(outcome, dict) else None
    binding = bindings.get(filename) if isinstance(bindings, dict) else None
    explicit = any("sourceObservationKind" in record for record in timed)
    if not explicit and binding is None:
        legacy_keys = {"sourceObservedAt", "observedAt", "capturedAt", "completedAt",
                       "capturedAtEpoch", "captured_at_epoch"}
        if any(legacy_keys.intersection(record) for record in timed) and not all(
            legacy_keys.intersection(record) for record in timed
        ):
            return None, "invalid-source-time"
        return None

    def instant(record: dict) -> datetime:
        if record.get("sourceObservationKind") != "controller-snapshot":
            raise ValueError("Invalid controller observation kind")
        value = record.get("sourceObservedAt")
        if not isinstance(value, str):
            raise ValueError("Missing controller observation time")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or not 0 < parsed.timestamp() <= now.timestamp():
            raise ValueError("Invalid controller observation time")
        return parsed.astimezone(timezone.utc)

    try:
        times = [instant(record) for record in timed]
        if binding is not None:
            if (not isinstance(binding, dict)
                    or set(binding) != {"sha256", "recordCount", "sourceObservedAt",
                                        "sourceObservationKind"}
                    or binding["sha256"] != content_digest
                    or type(binding["recordCount"]) is not int
                    or binding["recordCount"] != len(
                        payload if isinstance(payload, list) else payload["devices"])
                    or not isinstance(outcome, dict)
                    or outcome.get("source") != "ha-matter-ws"
                    or outcome.get("status") not in {"success", "success-with-node-errors"}
                    or filename not in outcome.get("finalFiles", [])):
                raise ValueError("Unbound controller observation")
            observed = instant(binding)
            started = datetime.fromisoformat(outcome["startedAt"].replace("Z", "+00:00"))
            completed = datetime.fromisoformat(outcome["completedAt"].replace("Z", "+00:00"))
            if (started.tzinfo is None or completed.tzinfo is None
                    or not 0 < started.timestamp() <= observed.timestamp()
                    <= completed.timestamp() <= now.timestamp()):
                raise ValueError("Invalid controller collection interval")
            if "sourceObservationKind" in outcome and instant(outcome) != observed:
                raise ValueError("Conflicting controller outcome observation")
            times.append(observed)
        if not times or len(set(times)) != 1:
            raise ValueError("Missing or conflicting controller observations")
        return times[0].isoformat(), "controller-snapshot"
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, OSError):
        return None, "invalid-source-time"


def validate_cached_outcome(filename: str, payload: Any) -> bool:
    """Validate original HA outcomes independently of display materialization."""
    if not isinstance(payload, dict) or payload.get("source") != "ha-matter-ws":
        raise MatterWsContractError("Invalid cached HA collection outcome")
    assert_snapshot_safe(payload)
    if filename == HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME:
        statuses = {"success", "success-with-node-errors", "failed", "cancelled", "partial"}
        files = payload.get("finalFiles")
        errors = payload.get("nodeErrors")
        if (payload.get("status") not in statuses or not isinstance(files, list)
                or any(not isinstance(name, str) for name in files)
                or len(files) != len(set(files)) or not isinstance(errors, list)
                or any(not isinstance(error, dict) for error in errors)
                or any(type(payload.get(key)) is not int or payload[key] < 0
                       for key in ("nodeCount", "normalizedNodeCount"))):
            raise MatterWsContractError("Invalid cached HA inventory outcome")
        if "artifactObservations" in payload:
            observations = payload["artifactObservations"]
            allowed = {
                HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME, HA_MATTER_WS_TOPOLOGY_FILENAME,
                HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME,
                HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME, HA_MATTER_WS_DASHBOARD_FILENAME,
            }
            if (not isinstance(observations, dict) or not observations
                    or not set(observations) <= allowed.intersection(files)
                    or any(not isinstance(item, dict)
                           or set(item) != {"sha256", "recordCount", "sourceObservedAt",
                                            "sourceObservationKind"}
                           or not isinstance(item["sha256"], str)
                           or len(item["sha256"]) != 64
                           or any(char not in "0123456789abcdef" for char in item["sha256"])
                           or type(item["recordCount"]) is not int or item["recordCount"] < 0
                           or not isinstance(item["sourceObservedAt"], str)
                           or item["sourceObservationKind"] != "controller-snapshot"
                           for item in observations.values())):
                raise MatterWsContractError("Invalid cached HA artifact observations")
        return (payload["status"] == "success" and not errors
                and payload["nodeCount"] == payload["normalizedNodeCount"]
                and HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME in files)
    native = {
        HA_MATTER_WS_THREAD_BORDER_ROUTERS_OUTCOME_FILENAME:
            ("get_thread_border_routers", HA_MATTER_WS_THREAD_BORDER_ROUTERS_FILENAME, "itemCount"),
        HA_MATTER_WS_NETWORK_TOPOLOGY_OUTCOME_FILENAME:
            ("get_network_topology", HA_MATTER_WS_NETWORK_TOPOLOGY_FILENAME, "nodeCount"),
    }
    expected = native.get(filename)
    if expected is None:
        raise MatterWsContractError("Unsupported cached HA outcome")
    command, final_file, count = expected
    if (payload.get("status") not in {"complete", "failed", "cancelled", "partial"}
            or payload.get("command") != command or not isinstance(payload.get("finalFile"), str)
            or type(payload.get(count)) is not int or payload[count] < 0
            or any(key in payload and (type(payload[key]) is not int or payload[key] < 0)
                   for key in ("itemCount", "nodeCount", "connectionCount", "responseCount", "eventCount"))):
        raise MatterWsContractError("Invalid cached HA native outcome")
    return payload["status"] == "complete" and payload["finalFile"] == final_file


def assess_cached_outcomes(payloads: dict[str, Any], inputs: list[dict]) -> list[str]:
    """Check outcome association without treating file mtimes as collection proof."""
    metadata = {item["filename"]: item for item in inputs}
    reasons = []
    collection = payloads.get(HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME)
    inventory = payloads.get(HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME)
    if collection is not None and inventory is not None:
        if collection["normalizedNodeCount"] != len(inventory):
            reasons.append("outcome-count-mismatch:" + HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME)
        collection_scope = metadata[HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME].get("observedNetwork")
        if collection_scope is not None and any(
            metadata.get(filename, {}).get("observedNetwork") not in {None, collection_scope}
            for filename in collection.get("artifactObservations", {})
        ):
            reasons.append("outcome-scope-mismatch:" + HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME)
    native = (
        (HA_MATTER_WS_THREAD_BORDER_ROUTERS_OUTCOME_FILENAME,
         HA_MATTER_WS_THREAD_BORDER_ROUTERS_FILENAME, "borderRouters", "itemCount"),
        (HA_MATTER_WS_NETWORK_TOPOLOGY_OUTCOME_FILENAME,
         HA_MATTER_WS_NETWORK_TOPOLOGY_FILENAME, "topology", "nodeCount"),
    )
    for outcome_file, data_file, field, count in native:
        outcome = payloads.get(outcome_file)
        snapshot = payloads.get(data_file)
        if outcome is None or snapshot is None or outcome["status"] != "complete":
            continue
        native_data = snapshot[field]
        expected_count = len(native_data["nodes"]) if field == "topology" else len(native_data)
        if outcome[count] != expected_count or (field == "topology" and
                outcome.get("connectionCount") != len(native_data["connections"])):
            reasons.append("outcome-count-mismatch:" + outcome_file)
        try:
            times = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in
                     (outcome["startedAt"], snapshot["observedAt"], outcome["completedAt"])]
            if any(value.tzinfo is None for value in times) or not times[0] <= times[1] <= times[2]:
                raise ValueError("Unbound native capture time")
        except (KeyError, AttributeError, ValueError, TypeError):
            reasons.append("unbound-outcome-capture:" + outcome_file)
        outcome_scope = metadata[outcome_file].get("observedNetwork")
        snapshot_scope = metadata[data_file].get("observedNetwork")
        if outcome_scope is not None and snapshot_scope is not None and outcome_scope != snapshot_scope:
            reasons.append("outcome-scope-mismatch:" + outcome_file)
    return reasons


def normalize_projection(payload: Any) -> list[dict]:
    """Deduplicate dashboard projections without making them an inventory substitute."""
    if not isinstance(payload, dict) or payload.get("schemaVersion") != DASHBOARD_SCHEMA_VERSION:
        raise MatterWsContractError("Invalid cached HA dashboard projection")
    assert_snapshot_safe(payload)
    rows = normalize_inventory(payload.get("devices"))
    for field in ("diagnostics", "meshDiagnostics", "topology"):
        records = payload.get(field)
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            raise MatterWsContractError(f"Invalid cached HA dashboard {field}")
        rows.extend(normalize_input_record(record, source="ha-matter-ws") for record in records)
    from merge_dataset import merge_cached_records
    grouped: dict[str | None, list[dict]] = {}
    for row in rows:
        network = _ext_pan_id(row["extPanId"]) if row.get("extPanId") is not None else None
        if network is not None:
            row["extPanId"] = network
        grouped.setdefault(network, []).append(row)
    result = []
    for network, records in grouped.items():
        merged, _ = merge_cached_records(
            [(HA_MATTER_WS_DASHBOARD_FILENAME, records)], network,
            preserve_same_file_duplicates=False,
        )
        result.extend(merged)
    return result


def bind_native_relationships(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Bind native endpoints to committed row IDs, never a possibly colliding address."""
    result = deepcopy(rows)
    by_record_id = {row["_unifiedRecordId"]: row for row in result}
    by_native_id: dict[str, list[str]] = {}
    for row in result:
        for native_id in row.get("nativeNodeIds", []):
            by_native_id.setdefault(native_id, []).append(row["_unifiedRecordId"])
    unresolved = []
    for row in result:
        for link in row.get("nativeRelationships", []):
            missing = []
            for endpoint in ("source", "target"):
                native_id = link[f"native{endpoint.title()}Id"]
                candidates = by_native_id.get(native_id, [])
                if len(candidates) == 1:
                    link[f"{endpoint}Id"] = candidates[0]
                else:
                    link[f"{endpoint}Id"] = f"ha-native:{native_id}"
                    missing.append(native_id)
            if not missing and link["networkType"] == "thread":
                source_scope = by_record_id[link["sourceId"]].get("_networkInstance")
                target_scope = by_record_id[link["targetId"]].get("_networkInstance")
                if source_scope is not None and target_scope is not None and source_scope != target_scope:
                    native_id = link["nativeTargetId"]
                    link["targetId"] = f"ha-native:{native_id}"
                    missing.append(native_id)
                    append_merge_conflict(row, "nativeRelationships.networkMismatch",
                                          source_scope, target_scope)
            if missing:
                link["unresolvedEndpoints"] = missing
                append_merge_conflict(row, "nativeRelationships.unresolvedEndpoints", None, missing)
                unresolved.append({key: link[key] for key in
                                   ("sourceId", "targetId", "unresolvedEndpoints")})
            else:
                link.pop("unresolvedEndpoints", None)
    return result, unresolved


def validate_canonical_rows(rows: list[dict]) -> None:
    for row in rows:
        conflicts = row.get("_merge_conflicts", [])
        if not isinstance(conflicts, list) or any(
            not isinstance(conflict, dict) or not isinstance(conflict.get("path"), str)
            or not {"current", "incoming"} <= conflict.keys() for conflict in conflicts
        ):
            raise MatterWsContractError("Invalid cached HA merge conflicts")
        node_ids = row.get("nativeNodeIds", [])
        if not isinstance(node_ids, list) or any(not isinstance(node_id, str) or not node_id
                                                for node_id in node_ids):
            raise MatterWsContractError("Invalid cached HA native node IDs")
        links = row.get("nativeRelationships", [])
        if not isinstance(links, list) or any(
            not isinstance(link, dict) or any(
                not isinstance(link.get(key), str) or not link[key]
                for key in ("sourceId", "targetId", "nativeSourceId", "nativeTargetId", "networkType")
            ) for link in links
        ):
            raise MatterWsContractError("Invalid cached HA native relationships")


def normalize_cached_ha_records(extractor: str, payload: Any) -> list[dict]:
    """Dispatch only explicit source-owned cached converters, never live collection."""
    converters = {
        "ha-inventory": normalize_inventory,
        "ha-border-routers": normalize_border_routers,
        "ha-native-topology": normalize_native_topology,
        "ha-projection": normalize_projection,
    }
    if extractor not in converters:
        raise MatterWsContractError(f"Unsupported cached HA converter: {extractor}")
    return converters[extractor](payload)
