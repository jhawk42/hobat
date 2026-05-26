# Dashboard UI Fields Reference

This document describes the device record fields available in the tdash web dashboard UI.

## Overview

The tdash dashboard displays Thread network device information from multiple data sources (CLI, REST API, mDNS, Eve topology). Device records can contain 77+ fields organized by priority for optimal visibility and usability.

## Field Organization

Fields are organized into 5 priority tiers that determine their display order in both table columns and detail panels:

### TIER 1: Primary Identity
Core device identifiers that appear first in the UI:
- `rloc16` - Router/Child Location (16-bit identifier)
- `extaddr`, `extAddress` - Extended MAC address (64-bit)
- `device_label` - User-assigned device label
- `name` - Device name
- `routerId`, `router_id` - Router ID (for router-capable devices)
- `eui64` - EUI-64 identifier
- `id`, `ID` - Generic device ID

### TIER 2: Secondary Identity
Additional identification fields:
- `omr_ipv6_addr`, `omrIpv6Address` - Off-Mesh Routable IPv6 address
- `mlEidIid` - ML-EID Interface Identifier
- `room` - Room assignment (from Eve topology)
- `Extended MAC` - Extended MAC (alternative field name)
- Link quality fields: `Next Hop`, `Path Cost`, `LQ In`, `LQ Out`, `Age`

### TIER 3: Device Role & Status
Device type, role, and operational mode:
- `type` - Device type (e.g., router, child, border-router)
- `Role` - Computed role field
- `br`, `isBorderRouter` - Border router flag
- `leader`, `isLeader` - Leader flag
- `is_router` - Router capability flag
- `mode.*` - Device mode flags:
  - `mode.deviceTypeFTD` - Full Thread Device
  - `mode.rxOnWhenIdle` - Receiver always on
  - `mode.secureDataRequest` - Secure data request enabled
  - `mode.networkData` - Network data type
  - `mode.device` - Device mode summary
- `isPrimaryBBR` - Primary Backbone Router flag
- `has_children` - Has child devices

### TIER 4: Topology & Connectivity
Network topology, link quality, and connectivity metrics:
- `total_children`, `total_routers`, `total_links` - Topology counts
- `neighbors`, `children`, `routes` - Relationship arrays
- `child_count`, `router_count`, `neighbor_count` - Alternative count fields
- `ipAddressList` - Complete list of IPv6 addresses
- `connectivity.*` - Connectivity metrics:
  - `parentPriority`, `linkQuality3`, `linkQuality2`, `linkQuality1`
  - `leaderCost`, `idSequence`, `activeRouters`
  - `sedBufferSize`, `sedDatagramCount`
- `leaderData.*` - Leader data fields:
  - `partitionId`, `weighting`, `dataVersion`, `stableDataVersion`, `leaderRouterId`

### TIER 5: Advanced/Diagnostic
Detailed diagnostics, counters, and vendor information:
- `vendor_name`, `vendor_model`, `vendor_sw_version`, `vendor_oui` - Vendor identification
- `ver`, `version`, `thread_version`, `thread_stack_version`, `threadStackVersion` - Version info
- `mleCounters.*` - MLE (Mesh Link Establishment) counters
- `macCounters.*` - MAC layer counters
- `route_data.route_data` - Routing table data
- `scope`, `status` - Dataset-specific fields
- Internal fields: `_source`, `_dataset_type`, `_merge_conflicts`

## Searchable Fields

The dashboard search feature (normal mode) searches the following 28 fields:

**Identity & Addresses:**
- `rloc16`, `extaddr`, `extAddress`, `eui64`
- `device_label`, `name`, `room`
- `ID`, `Extended MAC`
- `routerId`, `router_id`
- `omr_ipv6_addr`, `omrIpv6Address`, `mlEidIid`

**Device Type & Role:**
- `type`, `Role`
- `br`, `isBorderRouter`
- `leader`, `isLeader`

**Versions:**
- `ver`, `version`
- `thread_version`, `thread_stack_version`, `threadStackVersion`

**Other:**
- `mode.device`, `scope`, `status`

**Advanced Mode:** When "Advanced" mode is enabled, all fields in the device record become searchable.

## Field Naming Conventions

The dashboard supports both naming conventions to accommodate different data sources:

- **snake_case** (CLI datasets): `extaddr`, `omr_ipv6_addr`, `thread_stack_version`, `router_id`
- **camelCase** (REST API datasets): `extAddress`, `omrIpv6Address`, `threadStackVersion`, `routerId`

Both variants can appear in the same dataset. The UI displays whichever variant is present in the data. Search works with both naming conventions.

## Dataset Type Compatibility

Different dataset types provide different sets of fields:

| Dataset Type | Primary Fields | Naming Convention |
|-------------|----------------|-------------------|
| **CLI - meshdiag** | rloc16, extaddr, omr_ipv6_addr, thread_version, type, neighbors, children | snake_case |
| **CLI - networkdiag** | rloc16, extaddr, connectivity.*, mleCounters.*, macCounters.* | snake_case |
| **CLI - router table** | rloc16, router_id, Next Hop, Path Cost, LQ In, LQ Out, Age | snake_case |
| **REST API - devices** | rloc16, extAddress, routerId, omrIpv6Address, mlEidIid, type | camelCase |
| **REST API - diagnostics** | extAddress, routerId, mode.*, leaderData.*, connectivity.*, mleCounters.* | camelCase |
| **Eve topology** | extaddr, device_label, room, type, total_children, total_links | mixed |
| **MDNS records** | extaddr, name, type, vendor_* fields | mixed |

## Field Display Behavior

- **Missing Fields:** Fields not present in the dataset are automatically hidden (no errors)
- **Empty Values:** Fields with empty/null values may be hidden or shown as "(not available)"
- **Nested Objects:** Fields like `mode.*`, `connectivity.*`, `leaderData.*` appear as expandable groups in detail panels
- **Table Columns:** In table view, columns appear left-to-right in priority order
- **Detail Panels:** Fields are organized into sections (Keys, Highlights, Connections, Routes & Links) with priority ordering within each section

## Detail Panel Sections

**Keys Section (Identity):**
- Primary identifiers: rloc16, extaddr, device_label, routerId, id, omrIpv6Address, mlEidIid

**Highlights Section (Role & Status):**
- Device type, role, mode flags, leaderData, vendor info, version

**Connections Section (Topology):**
- Connectivity metrics, link quality, neighbor counts, ipAddressList

**Routes & Links Section:**
- Routing data, route_data field, link relationships

## Example Device Records

**CLI meshdiag device:**
```json
{
  "rloc16": "0x4400",
  "extaddr": "1a7fbf0434e4f043",
  "device_label": "Device 1",
  "type": "router",
  "omr_ipv6_addr": "fd00:1234::1",
  "thread_version": "4",
  "total_children": 3,
  "neighbors": ["0x4800", "0x4c00"]
}
```

**REST API diagnostics device:**
```json
{
  "rloc16": "0x4400",
  "extAddress": "1a7fbf0434e4f043",
  "routerId": 17,
  "omrIpv6Address": "fd00:1234::1",
  "mlEidIid": "0000000000000001",
  "type": "threadBorderRouter",
  "mode": {
    "deviceTypeFTD": true,
    "rxOnWhenIdle": true,
    "secureDataRequest": true,
    "networkData": "full"
  },
  "leaderData": {
    "partitionId": 123456,
    "weighting": 64,
    "leaderRouterId": 17
  }
}
```

## Tips for Users

1. **Use Search for Quick Lookup:** Type any identifier (rloc16, extaddr, device label) to quickly find devices
2. **Enable Advanced Mode:** To search diagnostic fields (counters, connectivity metrics), enable Advanced mode
3. **Check Multiple Sources:** Load multiple dataset types (CLI + REST API) for comprehensive device information
4. **Use Table View:** For comparing many devices, switch to Table view and sort by any column
5. **Expand Detail Panels:** Click devices to see full field lists organized by section
6. **Missing Fields:** If a field isn't shown, it's not present in the current dataset - try a different data source

## References

- **Code:** Field lists defined in `src/js/tdash-constants.js`, `tdash-search.js`, `tdash-utils.js`
- **HTML:** Detail panel sections defined in `src/tdash.html`
- **Dataset Formats:** See `data/` folder for example JSON files from each source type
