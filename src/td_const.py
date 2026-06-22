"""Shared constants for tdash."""

EXTADDR_DEVICE_LABEL_MAP_FILENAME = "td-static-extaddr-device-label.json"

TD_CHECKPOINT_FILENAME_SUFFIX = ".chkpt.json"


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


