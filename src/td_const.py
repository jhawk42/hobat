"""Shared constants for tdash."""

from types import MappingProxyType

EXTADDR_DEVICE_LABEL_MAP_FILENAME = "td-static-extaddr-device-label.json"
LEGACY_THREADSTATIC_EXTADDR_FILENAME = "threadstatic-extaddr.json"

MDNS_SCOPES_THREAD_FILENAME = "td-mdns-scopes-thread.json"
MDNS_SCOPES_BR_FILENAME = "td-mdns-scopes-br.json"
MDNS_SCOPES_HAP_FILENAME = "td-mdns-scopes-hap.json"
MDNS_SCOPES_MATTER_FILENAME = "td-mdns-scopes-matter.json"
MDNS_SCOPE_FILENAMES = MappingProxyType({
    "thread": MDNS_SCOPES_THREAD_FILENAME,
    "br": MDNS_SCOPES_BR_FILENAME,
    "hap": MDNS_SCOPES_HAP_FILENAME,
    "matter": MDNS_SCOPES_MATTER_FILENAME,
})

OTBR_CLI_THREAD_NETWORK_INFO_FILENAME = "td-otbr-cli-thread-network-info.json"
OTBR_CLI_ROUTER_TABLE_FILENAME = "td-otbr-cli-router-table.json"
OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME = "td-otbr-cli-meshdiag-topology.json"
OTBR_CLI_MESHDIAG_ROUTER_CHILDIP6_FILENAME = "td-otbr-cli-meshdiag-router-childip6.json"
OTBR_CLI_MESHDIAG_ROUTER_CHILDTABLES_FILENAME = "td-otbr-cli-meshdiag-router-childtables.json"
OTBR_CLI_MESHDIAG_ROUTER_NEIGHBORTABLES_FILENAME = "td-otbr-cli-meshdiag-router-neighbortables.json"
OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME = "td-otbr-cli-networkdiag-fetch-all.json"
OTBR_CLI_NETWORKDIAG_MULTICAST_NETWORK_FILENAME = "td-otbr-cli-networkdiag-multicast-network.json"
OTBR_CLI_NETWORKDIAG_MULTICAST_NEIGHBORS_FILENAME = "td-otbr-cli-networkdiag-multicast-neighbors.json"

OTBR_RESTAPI_DATASET_ACTIVE_FILENAME = "td-otbr-restapi-dataset-active.json"
OTBR_RESTAPI_DEVICES_FILENAME = "td-otbr-restapi-devices.json"
OTBR_RESTAPI_DEVICES_LIST_FILENAME = "td-otbr-restapi-devices-list.json"
OTBR_RESTAPI_DEVICES_FETCH_FILENAME = "td-otbr-restapi-devices-fetch.json"
OTBR_RESTAPI_DIAGNOSTICS_FILENAME = "td-otbr-restapi-diagnostics.json"
OTBR_RESTAPI_DIAGNOSTICS_LIST_FILENAME = "td-otbr-restapi-diagnostics-list.json"
OTBR_RESTAPI_DIAGNOSTICS_FETCH_FILENAME = "td-otbr-restapi-diagnostics-fetch.json"
OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME = "td-otbr-restapi-diagnostics-fetch-all.json"
OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME = "td-otbr-restapi-diagnostics-fetch-all.outcome.json"
OTBR_RESTAPI_ACTIONS_LIST_FILENAME = "td-otbr-restapi-actions-list.json"
OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_FILENAME = "td-otbr-restapi-mesh-diagnostics-fetch.json"
OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME = "td-otbr-restapi-mesh-diagnostics-fetch-all.json"
OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME = "td-otbr-restapi-mesh-diagnostics-fetch-all.outcome.json"
OTBR_RESTAPI_DEVICE_DIAGNOSTIC_FILENAME_TEMPLATE = "td-otbr-restapi-diagnostic-{device_id}.json"

HA_MATTER_WS_SERVER_INFO_FILENAME = "td-ha-matter-ws-server-info.json"
HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME = "td-ha-matter-ws-devices-fetch-all.json"
HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME = "td-ha-matter-ws-diagnostics-fetch-all.json"
HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME = "td-ha-matter-ws-mesh-diagnostics-fetch-all.json"
HA_MATTER_WS_TOPOLOGY_FILENAME = "td-ha-matter-ws-topology.json"
HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME = "td-ha-matter-ws-collection.outcome.json"

EVE_TOPOLOGY_FILENAME = "td-eve-topology.json"
THREAD_TOOLS_DIAGNOSTICS_FILENAME = "diagnostics.json"
MERGED_TOPOLOGY_ALL_FILENAME = "td-merged-topology-all.json"

TD_CHECKPOINT_FILENAME_SUFFIX = ".partial.json"


TD_DATA_DIR_ENV_VAR = "TD_DATA_DIR"
TD_DATA_DIR_ARG = "--datadir"
TD_DATA_DIR_DOCKER_DEFAULT = "/data"
TD_DATA_DIR_LOCAL_DEFAULT = "data"

TD_DATA_DIR_RESOLUTION_SUMMARY = (
    "Data directory resolution precedence: "
    "1) --datadir CLI argument, "
    "2) TD_DATA_DIR environment variable, "
    "3) defaults (/data when present, otherwise ./data under the current run directory)."
)

TD_DATA_DIR_ARG_HELP = (
    "Data directory for JSON reads/writes (takes precedence over TD_DATA_DIR). "
    "If omitted and TD_DATA_DIR is unset: use /data when present; otherwise create/use ./data "
    "under the current run directory."
)

# Thread Multicast Addresses
#
# FTDs (Full Thread Devices): Routers and REEDs (Router Eligible End Devices).
# MEDs (Minimal End Devices): Constantly powered end devices that do not route traffic.
# SEDs (Sleepy End Devices): Not natively targeted by standard ff03::1 due to low power states; they use custom unicast-prefix-based multicast strings. [2, 7] 
#

# One-hop (neighbors) discovery addresses
TD_THREAD_MULTICAST_ADDRESSES_LINK_LOCAL_ALL_FTDS_AND_MEDS = "ff02::1" # One-hop neighbor discovery
TD_THREAD_MULTICAST_ADDRESSES_LINK_LOCAL_ALL_FTDS = "ff02::2" # One-hop router discovery

# Mesh-local (realm/thread network) addresses
TD_THREAD_MULTICAST_ADDRESSES_MESH_LOCAL_ALL_FTDS_AND_MEDS = "ff03::1" # Global diagnostics, network-wide discovery
TD_THREAD_MULTICAST_ADDRESSES_MESH_LOCAL_ALL_FTDS = "ff03::2" # Diagnostic queries intended only for Routers

# Multicast Protocol for Low-Power Networks (MPL) messaging 
TD_THREAD_MULTICAST_ADDRESSES_MESH_LOCAL_ALL_MPL_FORWARDERS = "ff03::fc" # Multicast Protocol for Low-Power Networks (MPL) messaging


