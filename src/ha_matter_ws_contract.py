"""Versioned Home Assistant Matter WebSocket and Matter model contracts."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Literal, Mapping


DEFAULT_HA_MATTER_WS_URI = "ws://localhost:5580/ws"
COLLECTOR_SCHEMA_VERSION = 12
MIN_SUPPORTED_SERVER_SCHEMA_VERSION = 11

PROTOCOL_SOURCE = (
    "matter-js/matterjs-server packages/ws-client/src/models/model.ts and "
    "docs/websockets_api.md, reviewed 2026-08-30"
)
MATTER_MODEL_SOURCE = (
    "matter-js/matter.js packages/model/src/standard/elements, "
    "Matter cluster revisions Descriptor 3, BasicInformation 6, "
    "GeneralDiagnostics 3, ThreadNetworkDiagnostics 3, reviewed 2026-08-30"
)


class MatterWsContractError(ValueError):
    """Base error for invalid or incompatible Matter WebSocket frames."""


class MatterWsSchemaCompatibilityError(MatterWsContractError):
    """The server and collector schema ranges do not overlap."""


class MatterWsResponseCorrelationError(MatterWsContractError):
    """A command response cannot be correlated uniquely."""


class MatterWsCommandError(MatterWsContractError):
    """A correlated command response contains a server error."""

    def __init__(self, message_id: str, error_code: int, details: str | None) -> None:
        self.message_id = message_id
        self.error_code = error_code
        self.details = details
        message = f"Matter command {message_id!r} failed with error {error_code}"
        if details:
            message += f": {details}"
        super().__init__(message)


@dataclass(frozen=True)
class MatterElement:
    name: str
    data_type: str


@dataclass(frozen=True)
class CorrelatedResponse:
    message_id: str
    result: Any
    server_info: Mapping[str, Any] | None
    events: tuple[Mapping[str, Any], ...]


FrameKind = Literal["server_info", "success", "error", "event"]


def _elements(definitions: Mapping[int, tuple[str, str]]) -> Mapping[int, MatterElement]:
    return MappingProxyType(
        {
            element_id: MatterElement(name, data_type)
            for element_id, (name, data_type) in definitions.items()
        }
    )


CLUSTER_IDS = MappingProxyType(
    {
        "Descriptor": 0x001D,
        "BasicInformation": 0x0028,
        "GeneralDiagnostics": 0x0033,
        "ThreadNetworkDiagnostics": 0x0035,
    }
)

CLUSTER_REVISIONS = MappingProxyType(
    {
        0x001D: 3,
        0x0028: 6,
        0x0033: 3,
        0x0035: 3,
    }
)

DESCRIPTOR_ATTRIBUTES = _elements(
    {
        0x0000: ("DeviceTypeList", "list<DeviceTypeStruct>"),
        0x0001: ("ServerList", "list<cluster-id>"),
        0x0002: ("ClientList", "list<cluster-id>"),
        0x0003: ("PartsList", "list<endpoint-no>"),
        0x0004: ("TagList", "list<SemanticTagStruct>"),
        0x0005: ("EndpointUniqueId", "string"),
        0xFFFC: ("FeatureMap", "FeatureMap"),
        0xFFFD: ("ClusterRevision", "ClusterRevision"),
    }
)

BASIC_INFORMATION_ATTRIBUTES = _elements(
    {
        0x0000: ("DataModelRevision", "uint16"),
        0x0001: ("VendorName", "string"),
        0x0002: ("VendorId", "vendor-id"),
        0x0003: ("ProductName", "string"),
        0x0004: ("ProductId", "uint16"),
        0x0005: ("NodeLabel", "string"),
        0x0006: ("Location", "string"),
        0x0007: ("HardwareVersion", "uint16"),
        0x0008: ("HardwareVersionString", "string"),
        0x0009: ("SoftwareVersion", "uint32"),
        0x000A: ("SoftwareVersionString", "string"),
        0x000B: ("ManufacturingDate", "string"),
        0x000C: ("PartNumber", "string"),
        0x000D: ("ProductUrl", "string"),
        0x000E: ("ProductLabel", "string"),
        0x000F: ("SerialNumber", "string"),
        0x0010: ("LocalConfigDisabled", "bool"),
        0x0011: ("Reachable", "bool"),
        0x0012: ("UniqueId", "string"),
        0x0013: ("CapabilityMinima", "CapabilityMinimaStruct"),
        0x0014: ("ProductAppearance", "ProductAppearanceStruct"),
        0x0015: ("SpecificationVersion", "uint32"),
        0x0016: ("MaxPathsPerInvoke", "uint16"),
        0x0018: ("ConfigurationVersion", "uint32"),
        0xFFFC: ("FeatureMap", "FeatureMap"),
        0xFFFD: ("ClusterRevision", "ClusterRevision"),
    }
)

GENERAL_DIAGNOSTICS_ATTRIBUTES = _elements(
    {
        0x0000: ("NetworkInterfaces", "list<NetworkInterface>"),
        0x0001: ("RebootCount", "uint16"),
        0x0002: ("UpTime", "uint64"),
        0x0003: ("TotalOperationalHours", "uint32"),
        0x0004: ("BootReason", "BootReasonEnum"),
        0x0005: ("ActiveHardwareFaults", "list<HardwareFaultEnum>"),
        0x0006: ("ActiveRadioFaults", "list<RadioFaultEnum>"),
        0x0007: ("ActiveNetworkFaults", "list<NetworkFaultEnum>"),
        0x0008: ("TestEventTriggersEnabled", "bool"),
        0x000A: ("DeviceLoadStatus", "DeviceLoadStruct"),
        0xFFFC: ("FeatureMap", "FeatureMap"),
        0xFFFD: ("ClusterRevision", "ClusterRevision"),
    }
)

NETWORK_INTERFACE_FIELDS = _elements(
    {
        0x00: ("Name", "string"),
        0x01: ("IsOperational", "bool"),
        0x02: ("OffPremiseServicesReachableIPv4", "bool?"),
        0x03: ("OffPremiseServicesReachableIPv6", "bool?"),
        0x04: ("HardwareAddress", "hwadr"),
        0x05: ("IPv4Addresses", "list<ipv4adr>"),
        0x06: ("IPv6Addresses", "list<ipv6adr>"),
        0x07: ("Type", "InterfaceTypeEnum"),
    }
)

INTERFACE_TYPE_ENUM = MappingProxyType(
    {0: "Unspecified", 1: "WiFi", 2: "Ethernet", 3: "Cellular", 4: "Thread"}
)

THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES = _elements(
    {
        0x00: ("Channel", "uint16?"),
        0x01: ("RoutingRole", "RoutingRoleEnum?"),
        0x02: ("NetworkName", "string?"),
        0x03: ("PanId", "uint16?"),
        0x04: ("ExtendedPanId", "uint64?"),
        0x05: ("MeshLocalPrefix", "ipv6pre?"),
        0x06: ("OverrunCount", "uint64"),
        0x07: ("NeighborTable", "list<NeighborTableStruct>"),
        0x08: ("RouteTable", "list<RouteTableStruct>"),
        0x09: ("PartitionId", "uint32?"),
        0x0A: ("Weighting", "uint16?"),
        0x0B: ("DataVersion", "uint16?"),
        0x0C: ("StableDataVersion", "uint16?"),
        0x0D: ("LeaderRouterId", "uint8?"),
        0x0E: ("DetachedRoleCount", "uint16"),
        0x0F: ("ChildRoleCount", "uint16"),
        0x10: ("RouterRoleCount", "uint16"),
        0x11: ("LeaderRoleCount", "uint16"),
        0x12: ("AttachAttemptCount", "uint16"),
        0x13: ("PartitionIdChangeCount", "uint16"),
        0x14: ("BetterPartitionAttachAttemptCount", "uint16"),
        0x15: ("ParentChangeCount", "uint16"),
        0x16: ("TxTotalCount", "uint32"),
        0x17: ("TxUnicastCount", "uint32"),
        0x18: ("TxBroadcastCount", "uint32"),
        0x19: ("TxAckRequestedCount", "uint32"),
        0x1A: ("TxAckedCount", "uint32"),
        0x1B: ("TxNoAckRequestedCount", "uint32"),
        0x1C: ("TxDataCount", "uint32"),
        0x1D: ("TxDataPollCount", "uint32"),
        0x1E: ("TxBeaconCount", "uint32"),
        0x1F: ("TxBeaconRequestCount", "uint32"),
        0x20: ("TxOtherCount", "uint32"),
        0x21: ("TxRetryCount", "uint32"),
        0x22: ("TxDirectMaxRetryExpiryCount", "uint32"),
        0x23: ("TxIndirectMaxRetryExpiryCount", "uint32"),
        0x24: ("TxErrCcaCount", "uint32"),
        0x25: ("TxErrAbortCount", "uint32"),
        0x26: ("TxErrBusyChannelCount", "uint32"),
        0x27: ("RxTotalCount", "uint32"),
        0x28: ("RxUnicastCount", "uint32"),
        0x29: ("RxBroadcastCount", "uint32"),
        0x2A: ("RxDataCount", "uint32"),
        0x2B: ("RxDataPollCount", "uint32"),
        0x2C: ("RxBeaconCount", "uint32"),
        0x2D: ("RxBeaconRequestCount", "uint32"),
        0x2E: ("RxOtherCount", "uint32"),
        0x2F: ("RxAddressFilteredCount", "uint32"),
        0x30: ("RxDestAddrFilteredCount", "uint32"),
        0x31: ("RxDuplicatedCount", "uint32"),
        0x32: ("RxErrNoFrameCount", "uint32"),
        0x33: ("RxErrUnknownNeighborCount", "uint32"),
        0x34: ("RxErrInvalidSrcAddrCount", "uint32"),
        0x35: ("RxErrSecCount", "uint32"),
        0x36: ("RxErrFcsCount", "uint32"),
        0x37: ("RxErrOtherCount", "uint32"),
        0x38: ("ActiveTimestamp", "uint64"),
        0x39: ("PendingTimestamp", "uint64"),
        0x3A: ("Delay", "uint32"),
        0x3B: ("SecurityPolicy", "SecurityPolicy"),
        0x3C: ("ChannelPage0Mask", "octstr"),
        0x3D: ("OperationalDatasetComponents", "OperationalDatasetComponents"),
        0x3E: ("ActiveNetworkFaultsList", "list<NetworkFaultEnum>"),
        0x3F: ("ExtAddress", "uint64?"),
        0x40: ("Rloc16", "uint16?"),
        0xFFFC: ("FeatureMap", "FeatureMap"),
        0xFFFD: ("ClusterRevision", "ClusterRevision"),
    }
)

NEIGHBOR_TABLE_FIELDS = _elements(
    {
        0x00: ("ExtAddress", "uint64"),
        0x01: ("Age", "uint32"),
        0x02: ("Rloc16", "uint16"),
        0x03: ("LinkFrameCounter", "uint32"),
        0x04: ("MleFrameCounter", "uint32"),
        0x05: ("Lqi", "uint8"),
        0x06: ("AverageRssi", "int8?"),
        0x07: ("LastRssi", "int8?"),
        0x08: ("FrameErrorRate", "uint8"),
        0x09: ("MessageErrorRate", "uint8"),
        0x0A: ("RxOnWhenIdle", "bool"),
        0x0B: ("FullThreadDevice", "bool"),
        0x0C: ("FullNetworkData", "bool"),
        0x0D: ("IsChild", "bool"),
    }
)

ROUTE_TABLE_FIELDS = _elements(
    {
        0x00: ("ExtAddress", "uint64"),
        0x01: ("Rloc16", "uint16"),
        0x02: ("RouterId", "uint8"),
        0x03: ("NextHop", "uint8"),
        0x04: ("PathCost", "uint8"),
        0x05: ("LqiIn", "uint8"),
        0x06: ("LqiOut", "uint8"),
        0x07: ("Age", "uint8"),
        0x08: ("Allocated", "bool"),
        0x09: ("LinkEstablished", "bool"),
    }
)

ROUTING_ROLE_ENUM = MappingProxyType(
    {
        0: "Unspecified",
        1: "Unassigned",
        2: "SleepyEndDevice",
        3: "EndDevice",
        4: "Reed",
        5: "Router",
        6: "Leader",
    }
)

CLUSTER_ATTRIBUTES = MappingProxyType(
    {
        0x001D: DESCRIPTOR_ATTRIBUTES,
        0x0028: BASIC_INFORMATION_ATTRIBUTES,
        0x0033: GENERAL_DIAGNOSTICS_ATTRIBUTES,
        0x0035: THREAD_NETWORK_DIAGNOSTICS_ATTRIBUTES,
    }
)


def matter_attribute_path(endpoint_id: int, cluster_id: int, attribute_id: int) -> str:
    """Return the decimal Matter Server attribute path representation."""

    return f"{endpoint_id}/{cluster_id}/{attribute_id}"


def attribute_definition(path: str) -> MatterElement | None:
    """Look up a supported attribute path without guessing unknown elements."""

    parts = path.split("/")
    if len(parts) != 3:
        return None
    try:
        _, cluster_id, attribute_id = (int(part, 10) for part in parts)
    except ValueError:
        return None
    return CLUSTER_ATTRIBUTES.get(cluster_id, {}).get(attribute_id)


def classify_frame(frame: Mapping[str, Any]) -> FrameKind:
    """Classify one server frame and reject ambiguous envelope shapes."""

    has_message_id = isinstance(frame.get("message_id"), str)
    has_event = isinstance(frame.get("event"), str) and "data" in frame
    has_result = "result" in frame
    has_error = isinstance(frame.get("error_code"), int)
    has_server_info = all(
        key in frame
        for key in ("schema_version", "min_supported_schema_version", "sdk_version")
    )

    kinds = []
    if has_server_info and not has_message_id:
        kinds.append("server_info")
    if has_message_id and has_result and not has_error:
        kinds.append("success")
    if has_message_id and has_error and not has_result:
        kinds.append("error")
    if has_event and not has_message_id:
        kinds.append("event")
    if len(kinds) != 1:
        raise MatterWsContractError(f"Unrecognized or ambiguous Matter WebSocket frame: {frame!r}")
    return kinds[0]  # type: ignore[return-value]


def validate_server_info(server_info: Mapping[str, Any]) -> None:
    """Require overlap between the server and collector schema ranges."""

    if classify_frame(server_info) != "server_info":
        raise MatterWsContractError("Expected an initial server-info frame")
    server_schema = server_info.get("schema_version")
    server_minimum = server_info.get("min_supported_schema_version")
    if not isinstance(server_schema, int) or not isinstance(server_minimum, int):
        raise MatterWsContractError("Server schema versions must be integers")
    if server_schema < MIN_SUPPORTED_SERVER_SCHEMA_VERSION:
        raise MatterWsSchemaCompatibilityError(
            f"Server schema {server_schema} is older than supported schema "
            f"{MIN_SUPPORTED_SERVER_SCHEMA_VERSION}"
        )
    if server_minimum > COLLECTOR_SCHEMA_VERSION:
        raise MatterWsSchemaCompatibilityError(
            f"Server requires schema {server_minimum}, collector implements "
            f"schema {COLLECTOR_SCHEMA_VERSION}"
        )


def correlate_response(
    frames: Iterable[Mapping[str, Any]], message_id: str
) -> CorrelatedResponse:
    """Select exactly one response while retaining unrelated server info/events."""

    server_info: Mapping[str, Any] | None = None
    events: list[Mapping[str, Any]] = []
    matched: Mapping[str, Any] | None = None

    for frame in frames:
        kind = classify_frame(frame)
        if kind == "server_info":
            validate_server_info(frame)
            server_info = frame
        elif kind == "event":
            events.append(frame)
        elif frame["message_id"] == message_id:
            if matched is not None:
                raise MatterWsResponseCorrelationError(
                    f"Duplicate response for message_id {message_id!r}"
                )
            matched = frame

    if matched is None:
        raise MatterWsResponseCorrelationError(
            f"No response for message_id {message_id!r}"
        )
    if "error_code" in matched:
        raise MatterWsCommandError(
            message_id,
            matched["error_code"],
            matched.get("details") if isinstance(matched.get("details"), str) else None,
        )
    return CorrelatedResponse(message_id, matched["result"], server_info, tuple(events))