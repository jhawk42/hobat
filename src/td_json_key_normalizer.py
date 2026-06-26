"""JSON key normalization helpers for canonical camelCase output.

This module centralizes key conversion so collectors can keep internal parsing
logic unchanged while writing a consistent camelCase JSON schema to disk.
"""

from __future__ import annotations

import re
from typing import Any


# Explicit mappings for keys that do not follow simple snake_case -> camelCase.
EXPLICIT_KEY_MAP: dict[str, str] = {
    # Core identity / topology fields.
    "extaddr": "extAddress",
    "ext_addr": "extAddress",
    "omr_ipv6_addr": "omrIpv6Address",
    "ipv6_addrs": "ipv6Addresses",
    "ip6_addrs": "ipv6Addresses",
    "route_data": "routeData",
    "leader_data": "leaderData",
    "router_neighbor_table": "routerNeighbors",
    "router_neighbor_table_count": "routerNeighborsCount",
    "router_child_table": "childTable",
    "router_child_table_count": "childTableCount",
    "router_child_ip6_table": "childIp6Table",
    "router_child_ip6_table_count": "childIp6TableCount",
    "child_rloc16": "childRloc16",
    "ip6_addr_count": "ip6AddressCount",
    "responder_ipv6": "responderIpv6",

    # Connectivity / route / counters.
    "rss_ave": "averageRssi",
    "rss_last": "lastRssi",
    "rss_margin": "linkMargin",
    "q_msg": "queuedMessageCount",
    "route_id": "routeId",
    "route_cost": "routeCost",
    "link_quality": "linkQuality",
    "link_quality_in": "linkQualityIn",
    "link_quality_out": "linkQualityOut",
    "link_quality_1": "linkQuality1",
    "link_quality_2": "linkQuality2",
    "link_quality_3": "linkQuality3",
    "id_sequence": "idSequence",
    "active_routers": "activeRouters",
    "leader_cost": "leaderCost",
    "parent_priority": "parentPriority",
    "sed_buffer_size": "sedBufferSize",
    "sed_datagram_count": "sedDatagramCount",
    "ifinunknownprotos": "ifInUnknownProtos",
    "ifinerrors": "ifInErrors",
    "ifouterrors": "ifOutErrors",
    "ifinucastpkts": "ifInUcastPkts",
    "ifinbroadcastpkts": "ifInBroadcastPkts",
    "ifindiscards": "ifInDiscards",
    "ifoutucastpkts": "ifOutUcastPkts",
    "ifoutbroadcastpkts": "ifOutBroadcastPkts",
    "ifoutdiscards": "ifOutDiscards",
    "disabledrole": "disabledRole",
    "detachedrole": "detachedRole",
    "childrole": "childRole",
    "routerrole": "routerRole",
    "leaderrole": "leaderRole",
    "attachattempts": "attachAttempts",
    "partitionidchanges": "partitionIdChanges",
    "betterpartitionattachattempts": "betterPartitionAttachAttempts",
    "parentchanges": "parentChanges",
    "totalparentpartitionchanges": "totalParentPartitionChanges",

    # Role / mode flags.
    "is_router": "isRouter",
    "is_border_router": "isBorderRouter",
    "thread_version": "threadVersion",
    "thread_stack_version": "threadStackVersion",
    "device_label": "deviceLabel",
    "device_type": "deviceType",
    "network_data": "networkData",
    "rx_on": "rxOnWhenIdle",
    "rx_on_when_idle": "rxOnWhenIdle",
    "ver": "version",
    "full_net": "fullNetworkData",
    "tlv_values": "tlvValues",

    # Network dataset fields.
    "active_timestamp": "activeTimestamp",
    "wake_up_channel": "wakeUpChannel",
    "channel_mask": "channelMask",
    "ext_pan_id": "extPanId",
    "mesh_local_prefix": "meshLocalPrefix",
    "network_key": "networkKey",
    "network_name": "networkName",
    "pan_id": "panId",
    "security_policy": "securityPolicy",
    "prefix_meshlocal": "prefixMeshLocal",
    "prefix_meshlocal_ipv6addr_prefix": "prefixMeshLocalIpv6AddrPrefix",
    "prefix_omr": "prefixOmr",
    "prefix_omr_ipv6addr_prefix": "prefixOmrIpv6AddrPrefix",

    # Link arrays / summary.
    "total_children": "totalChildren",
    "total_links": "totalLinks",
    "total_link_3": "totalLink3",
    "total_link_2": "totalLink2",
    "total_link_1": "totalLink1",
    "3_links": "links3",
    "2_links": "links2",
    "1_links": "links1",

    # Child-table details.
    "conn_time": "connectionTime",
    "supvn": "supervisorVersionNumber",
    "full_netdata": "fullNetdata",
    "full_thread_device": "fullThreadDevice",
    "csl_sync": "cslSync",
    "csl_period": "cslPeriod",
    "csl_timeout": "cslTimeout",
    "csl_channel": "cslChannel",

    # Vendor fields.
    "vendor_name": "vendorName",
    "vendor_model": "vendorModel",
    "vendor_sw_version": "vendorSwVersion",

    # EVE-specific fields.
    "rloc16_hex": "rloc16Hex",
    "rloc16_hexshort": "rloc16HexShort",
    "rloc16_decimal": "rloc16Decimal",
    "node_name_eve": "nodeNameEve",
    "node_id_eve": "nodeIdEve",

    # mDNS / enriched metadata fields.
    "record_key": "recordKey",
    "captured_at_epoch": "capturedAtEpoch",
    "captured_at_iso": "capturedAtIso",
    "service_info": "serviceInfo",
    "FabricID": "fabricId",
    "FabricID_compressed": "fabricIdCompressed",
    "NodeID": "nodeId",
    "full_name": "fullName",
    "int_value": "intValue",
    "hex_value": "hexValue",
    "individual_bits": "individualBits",
    "supported_features": "supportedFeatures",
    "category_name": "categoryName",
    "milliseconds": "milliseconds",

    # Error-rate and percentage fields.
    "err_rate_frame_pct": "frameErrorRate",
    "err_rate_msg_pct": "messageErrorRate",
    "ifintotalpkts": "ifInTotalPkts",
    "ifouttotalpkts": "ifOutTotalPkts",
    "iftotalpkts": "ifTotalPkts",
    "iftotalerrors": "ifTotalErrors",
    "iftotaldiscards": "ifTotalDiscards",
    "iftotal_inerrdiscs": "ifTotalInErrDiscs",
    "iftotal_outerrdiscs": "ifTotalOutErrDiscs",
    "iftotal_errdiscs": "ifTotalErrDiscs",
    "ifinerrors_totalinerrdiscs_ratio": "ifInErrorsTotalInErrDiscsRatio",
    "ifindiscards_totalinerrdiscs_ratio": "ifInDiscardsTotalInErrDiscsRatio",
    "ifouterrors_totalouterrdiscs_ratio": "ifOutErrorsTotalOutErrDiscsRatio",
    "ifoutdiscards_totalouterrdiscs_ratio": "ifOutDiscardsTotalOutErrDiscsRatio",
    "iftotalerrors_totalerrdiscs_ratio": "ifTotalErrorsTotalErrDiscsRatio",
    "iftotaldiscards_totalerrdiscs_ratio": "ifTotalDiscardsTotalErrDiscsRatio",
    "ifinerrors_intotalpkts_ratio": "ifInErrorsInTotalPktsRatio",
    "ifindiscards_intotalpkts_ratio": "ifInDiscardsInTotalPktsRatio",
    "ifouterrors_outtotalpkts_ratio": "ifOutErrorsOutTotalPktsRatio",
    "ifoutdiscards_outtotalpkts_ratio": "ifOutDiscardsOutTotalPktsRatio",
    "iftotalerrors_totalpkts_ratio": "ifTotalErrorsTotalPktsRatio",
    "iftotaldiscards_totalpkts_ratio": "ifTotalDiscardsTotalPktsRatio",
    "ifinerrors_totalerrors_pct": "ifInErrorsPercentage",
    "ifouterrors_totalerrors_pct": "ifOutErrorsPercentage",
    "ifindiscards_totaldiscards_pct": "ifInDiscardsPercentage",
    "ifoutdiscards_totaldiscards_pct": "ifOutDiscardsPercentage",
    "ifinerrorsTotalinerrdiscsRatio": "ifInErrorsTotalInErrDiscsRatio",
    "ifindiscardsTotalinerrdiscsRatio": "ifInDiscardsTotalInErrDiscsRatio",
    "ifouterrorsTotalouterrdiscsRatio": "ifOutErrorsTotalOutErrDiscsRatio",
    "ifoutdiscardsTotalouterrdiscsRatio": "ifOutDiscardsTotalOutErrDiscsRatio",
    "iftotalerrorsTotalerrdiscsRatio": "ifTotalErrorsTotalErrDiscsRatio",
    "iftotaldiscardsTotalerrdiscsRatio": "ifTotalDiscardsTotalErrDiscsRatio",
    "ifinerrorsIntotalpktsRatio": "ifInErrorsInTotalPktsRatio",
    "ifindiscardsIntotalpktsRatio": "ifInDiscardsInTotalPktsRatio",
    "ifouterrorsOuttotalpktsRatio": "ifOutErrorsOutTotalPktsRatio",
    "ifoutdiscardsOuttotalpktsRatio": "ifOutDiscardsOutTotalPktsRatio",
    "iftotalerrorsTotalpktsRatio": "ifTotalErrorsTotalPktsRatio",
    "iftotaldiscardsTotalpktsRatio": "ifTotalDiscardsTotalPktsRatio",

    # Router-table header names.
    "ID": "id",
    "RLOC16": "rloc16",
    "Next Hop": "nextHop",
    "Path Cost": "pathCost",
    "LQ In": "linkQualityIn",
    "LQ Out": "linkQualityOut",
    "Age": "age",
    "Extended MAC": "extAddress",
    "Link": "link",

    # Legacy metadata.
    "_error": "error",
}


_SNAKE_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)+$")


def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def canonical_camel_key(key: str) -> str:
    """Convert a single key into canonical camelCase form."""
    if key in EXPLICIT_KEY_MAP:
        return EXPLICIT_KEY_MAP[key]

    if _SNAKE_RE.fullmatch(key):
        return _snake_to_camel(key)

    return key


def convert_keys_to_camel_case(payload: Any) -> Any:
    """Recursively convert dict keys in payload to canonical camelCase."""
    if isinstance(payload, list):
        return [convert_keys_to_camel_case(item) for item in payload]

    if isinstance(payload, dict):
        converted: dict[Any, Any] = {}
        for raw_key, value in payload.items():
            new_key = canonical_camel_key(raw_key) if isinstance(raw_key, str) else raw_key
            converted[new_key] = convert_keys_to_camel_case(value)
        return converted

    return payload
