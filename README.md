# tdash - thread mesh network dashboard and tools

The tdash tools and dashboard enable visualizing and querying a Thread Network using dataset sources like: an Open Thread Border Router (OTBR) and related thread mDNS records. Also visualizes using the Eve app thread layout file.

Jump to: [Overview](#overview) [Getting Started](#getting-started) [help docs](./doc/)

Backstory: For a number of years I have been looking for a detailed thread network dashboard and cli tools to help me better understand and improve my thread network (multiple TBRs, a couple dozen thread devices). I use thread tools like the matterjs-server thread dashboard (like this tool and the direction), Eve app (good thread device view) and the Open Thread Border Router (OTBR) console log and topology view.

I wanted to go the next level of detail (filter by: MAC (radio) and MLE (mesh) counters, Link Quality, decode all the thread mDNS records, etc). So I built tdash dashboard and tools which has helped me better understand and improve my thread network (add more routers in the right areas). Sharing with the community.

My thread environment: 
- Thread Border Routers:
  - Apple TVs & HomePod Minis
  - Openthread OTBR in a Docker container connected to a Home Assistant Connect ZBT-1 via usb. 
  - HA OTBR App running in HAOS connected to a Home Assistant Connect ZBT-2 via usb. 
- Tdash dashboard and tools running inside a Docker container on Debian. Also test directly on the Debian host.
- Mix of Apple HomeKit (HAP) over thread devices and Matter devices from Eve, Aqara, Ikea, Schlage, Govee, Nanoleaf, Third Reality; across device types like smart outlets, climate sensors (temperature, humidity), Room sensors (motion, occupancy, presence), contact sensors, smart water valves, water leak sensors, buttons, etc


Links to related Thread Network tools: [Home Assistant Matter Server](https://github.com/matter-js/matterjs-server) has a great dashboard for Matter over Thread devices; [Eve App](https://www.evehome.com/en-us/eve-app) uses a powered Eve device (smartplug) in the thread network to enable gathering thread device information; [Thread Group - Android: Thread Network Diagnostics app](https://play.google.com/store/apps/details?id=com.threadgroup.otloom&hl=en_US); [Nordic Semiconductor - nRF Thread Topology Monitor](https://www.nordicsemi.com/Products/Development-tools/nRF-Thread-topology-monitor).

Jump to: [Getting Started](#getting-started) [help docs](./doc/) [td_cli](./doc/help_td_cli.md) [td cli rest-api](./doc/help_td_restapi_cli.md) [td_webserver](./doc/help_td_webserver.md) [env vars](./doc/help_env_vars.md) [openthread](https://github.com/openthread/openthread) 

## Overview

At a high level the tdash tools (td_cli) fetch Thread device info from an Open Thread Border Router (OBTR) for a thread network and the thread device info is stored into a local cache in the tdash data directory. The tdash dashboard reads from the data directory cache to visualize the Thread mesh network in both topology and table views. This model helps to reduce traffic on the thread network so thread devices can continue to communicate and also reduces load on the battery powered Sleepy End Devices (SED) when running queries over the thread device info. The tdash dashboard and tools can run diagnostics queries over the thread info for: Node type, Link Quality, MAC (radio) counters and MLE (thread mesh & role time counters). 

The tdash dashboard and tools provide:

### CLI toolkit

CLI toolkit (Python) fetches thread device info from a thread network and then stores into a local cache in the tdash data directory for offline querying and processing. Fetch thread device info from these sources:
- Open Thread Border Router (OTBR): otbr-cli via OTBR ot-ctl tool. 
- Open Thread Border Router (OTBR): otbr-restapi via OTBR REST endpoint.
- Multicast DNS (mDNS) records.
- Eve app thread json format layout file. 

### Dashboard

Dashboard for Thread mesh network in a browser web page (html, javascript) for visualizing and querying thread mesh network info.

Search devices by: rloc16, extaddr, device_label, routerId and a vast number of other fields.

Filter Thread devices by: 
- Thread node types: border router, router, ftd, sed/mtd child nodes etc.
- Thread link quality: LQ3, LQ2, LQ1. Ratio of LQ3 to total links, etc.
- Diagnostics filters to find thread nodes that need attention: MAC counters (packets, frame errors, etc) and MLE counters (partition changes, parent attempt changes, role time durations, etc)

### Python webserver

Python webserver for the hosting the thread dashboard, restapi endpoint for servicing requests from the tdash dashboard for cached data, launching the tdash cli to refetch data from the thread network into the data cache.

### Extended MAC Address (extaddr) to device_label

Labeling for thread devices using a simple JSON file mechanism using a Extended MAC Address (extaddr) to device_label lookup file. See [Device Labeling](#setup-device-labeling) below for details.

## Dataset Sources

### otbr-cli

Fetches otbr-cli info from an OpenThread Border Router (OTBR) instance via ot-ctl commands for thread device info. Note ot-ctl bypasses the OTBR RESTAPI cache. By default use docker exec to call into the "otbr" docker container. Also support calling otbr on the host. Common ot-ctl commands used:
- router table (quick, seconds, summary)
- meshdiag topology (quick, seconds, summary). Optionally also calls these sub commands (long, more detailed info) routerneighbortable, childtable, childip6
- networkdiag (takes time, minutes, detailed). The td_cli networkdiag supports multicast (quick, full thread devices) and fetch-all (all devices including routers, full thread devices, SED/minimal thread devices) 

### otbr-restapi

Fetches otbr-restapi thread device info from the OpenThread Border Router (OTBR) REST API web-server endpoint.
- node: 	     get, state get, state set, dataset active get, dataset active set	Read/mutate local OTBR node and active dataset
- devices:	 list, get, fetch	List, read, or refresh device collection
- diagnostics: list, get, fetch, fetch-all	Read or fetch network diagnostics
- mesh-diagnostics:	children, child-ipv6, router-neighbors, fetch, fetch-all
- actions:	 list, get, enqueue (update-device-collection,get-network-diagnostic). Inspect and enqueue OTBR action tasks
- download:	 download OTBR REST API endpoint snapshots to JSON files
- Notes: It appears the the otbr-agent hosts the devices collection in memory. Have sometimes observed the OTBR REST API's web-server cache only has the OTBR device entry i.e no other devices until the cache is rebuilt. It appears the data in the devices collection remains cached indefinitely until one of three events occurs:
  - A manual refresh request: Issuing an actions enqueue update-device-collection command wipes the old snapshot and builds a fresh one.
  - Service restarts: Because the REST API caches this topology snapshot in the host's volatile memory runtime (otbr-agent), restarting the OTBR system or docker container completely clears the cache.
  - Queue Eviction: The OTBR REST server manages action tasks using a fixed-size queue. If the queue fills up, the oldest historical task states (and their associated cached result payloads) are systematically evicted to free up space. [2, 3] 

### mdns
Fetches mdns thread-related mdns scope records: _meshcop, _hap, _matter for thread device info.
- thread:      All thread scopes _meshcop, _hap, _matter      
- br:          Thread Border Routers in _meshcop scope
- hap:         Apple HomeKit Accessory Protocol (HAP) devices in _hap scope
- matter:      Matter over thread devices in _matter scope

## eve layout
Eve app layout json file: Enhances and visualizes the eve layout file info.
- The Eve app (iOS) supports querying a thread network for devices and sharing device info to a JSON layout file.
- Note: Eve app needs at least one Eve thread device like a smart outlet to collect info as the eve device has diagnostics code in device firmware to collect thread device info.
- Eve app works well with Apple Home (HAP) thread networks.

## Getting Started

The tdash can be run in a docker container or manually run via cli on a host.

### Setup Pull tdash docker container

The tdash docker container hosts the td_cli and web server.

```bash
docker pull ghcr.io/jhawk42/tdash:latest
```

Notes: 
- The tdash docker container automatically starts the td_webserver.py with the dashboard. Default port is 9165.
- The tdash docker container needs access to the docker socket for otbr-cli to call between docker containers so td_cli in the tdash container to call into the otbr container to execute ot-ctl commands via: docker exec -it otbr /usr/sbin/ot-ctl to fetch thread device info.
- See [Environment Variables](./doc/help_env_vars.md) for changing the:
  - td_webserver.py http access to Dashboard : HOST, PORT 
  - otbr-restapi access: OT_REST_LISTEN_ADDR, OT_REST_LISTEN_PORT
  - otbr-cli access: OTBR docker container name: TD_OTBR_CONTAINER_NAME
  - data directory: TD_DATA_DIR

### Setup Data Directrory

tdash uses a data directory for:
  - Caching thread device info
  - Extended MAC Address to device label via a side json file
  - Loading eve layout file

Create a data directory and map this directory into the docker container via docker run.

The TD_DATA_DIR environment variable cane used by td tools (cli, webserver, container) to find the data directory. If not specificied, the TD_DATA_DIR will automatically resolve to: 
  - In the docker container to /data directory

```bash
mkdir $PWD/data
export TD_DATA_DIR=$PWD/data
```

### Setup Eve layout file

To use the tdash dashbaord to visualize Eve app layout shared file, copy the 'Eve Thread Network Layout.evethreadlayout' into the data directory. Normal flow is: In Eve app -> Settings -> Thread Network -> wait a couple of minutes for the list to populate -> click the share icon in the upper right -> Save to files -> save to iCloud Drive Download -> PC/Laptop -> use scp to copy to Linux machine tdash data directory running tdash tools.

Copy from PC / Laptop to Linux
```bash
scp "Eve Thread Network Layout.evethreadlayout" user@hostname:/your/directory/here
```

Linux: Copy into the tdash data folder
```bash
cp Eve\ Thread\ Network\ Layout.evethreadlayout $PWD/data
```

### Setup Device Labeling

To do device labeling via a side json file, add a file named td-static-extaddr-device-label.json with the format below into the data directory. Map this directory into the docker container via docker run. See below for example.

The td_cli commands and dash dasboard will use the file if it exists to lookup extaddr (Extended MAC Address) to device_label mapping. The td_cli commands enhance the collect thread device info with the device_label. The thread dashboard will use the extaddr device_label to lookup extaddr to device label mapping.

```
nano $PWD/data/td-static-extaddr-device-label.json
```
Edit the td-static-extaddr-device-label.json as you discover thread devices in the thread network. 
The extaddr is the thread device Extended MAC Address.
The device_label is the name you assign to the thread device.

Sources for names: Matching thread device identities like ipv6 addresses in  mDNS records (_meshcop._udp, _hap._udp) and Eve layout file is a good place to find thread device names.
Note _matter._tcp does not have device names. Try using the 
[Home Assistant Open Home Foundation Matter Server](https://github.com/matter-js/python-matter-server) as it has great Matter over Thread support.

Example format of the td-static-extaddr-device-label.json file.
```JSON
[
    {
        "extaddr": "eeeaffeaffeaffe1",
        "device_label": "Device 1"
    },
    {
        "extaddr": "eeeaffeaffeaffe2",
        "device_label": "Device 2"
    },
    {
        "extaddr": "eeeaffeaffeaffe3",
        "device_label": "Device 3"
    }
]
```

### Setup Start the tdash docker container

Note: Map a local data directory into the tdash docker container data directory.

```bash
docker run --name=tdash -d \
  --network=host \
  --volume $PWD/data:/data \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --restart=unless-stopped \
  tdash:latest 
```


## Open the tdash dashboard in a browser

Open the tdash web dashboard in a browser. 
Default PORT is 9165.

```bash
# localhost
http://localhost:9165/

# ip address
http://<your-host-ip-addr>:9165/
```

Note: The tdash webserver will automatically use td_cli.py to refresh the thread network cached info files:
- When cached info files don't exist.
- When cached info files are stale beyond a certain threshold.

### Dashboard Features

The tdash web dashboard provides comprehensive visualization and querying capabilities:

- **Fetch from Multiple Data Sources:** Supports otbr-cli (meshdiag, networkdiag), otbr-restapi, mDNS, and Eve topology datasets
- **Multiple Views:** Topology view (graph) and Table view for different analysis needs
- **Search:** Search devices by rloc16, extaddr, device_label, routerId, and a number other identity fields
- **Filtering:** Filter by device type (border router, router, FTD, MTD), link quality (LQ3/LQ2/LQ1), and diagnostic criteria
- **Detail Panels:** Click any device to view comprehensive details organized into sections (Keys, Highlights, Connections, Routes & Links)
- **Device Fields:** Supports detailed device information including:
  - Identity: rloc16, extaddr, device_label, routerId, omrIpv6Address
  - Role & Status: type, mode flags, leaderData, border router/leader indicators
  - Connectivity: link quality, connectivity metrics, neighbor/child counts
  - Diagnostics: MLE counters, MAC counters, vendor information
- **Flexible Field Naming:** Automatically handles both snake_case (CLI) and camelCase (REST API) field conventions

For complete field reference and dashboard usage, see [doc/dashboard_ui_fields.md](doc/dashboard_ui_fields.md).

## Setup: Manual on a host

To manually run on a host, git clone this repro onto the host. See details below to manually run td_cli.py and td_webserver.py commands.

## tdash cli examples

See below for additional details for running td_cli.py commands 

Direct on host
```
python3 -m td_cli --help
```

Docker exec into dash docker container cli entry point and run td_cli.py.

```
# docker exec into tdash container: run bash and then td_cli.py commands.

docker exec -it tdash /bin/bash $*

# bash in tdash docker container: td_cli.py examples:
python3 -m td_cli --help

usage: td_cli [-h] [--verbose] [--debug] [--output FILE] [--datadir DIR] {otbr-cli,mdns,otbr-restapi,process-eve,merge-dataset} ...

python3 -m td_cli otbr-cli router-table
```

docker exec into tdash: run td_cli.py commands
```
docker exec -it tdash /usr/local/bin/python3 -m td_cli otbr-cli router-table
docker exec -it tdash /usr/local/bin/python3 -m td_cli --debug otbr-cli router-table
```

## tdash cli commands (docker or direct on host)

These commands can be run inside the tdash docker container.
They can also be run directly on the host if you are running without docker.

```bash
# Help
python3 -m td_cli --help

usage: td_cli [-h] [--verbose] [--debug] [--output FILE] [--datadir DIR] {otbr-cli,mdns,otbr-restapi,process-eve,merge-dataset} ...

# Common commands:

# OTBR CLI
# Note: fetch-all commands take time (minutes) to complete
python3 -m td_cli otbr-cli --help
python3 -m td_cli otbr-cli thread-network-info
python3 -m td_cli otbr-cli router-table
python3 -m td_cli otbr-cli meshdiag topology
python3 -m td_cli otbr-cli meshdiag routerneighbortable
python3 -m td_cli otbr-cli meshdiag childtable
python3 -m td_cli otbr-cli meshdiag childip6
python3 -m td_cli otbr-cli meshdiag all
python3 -m td_cli otbr-cli networkdiag fetch-all
python3 -m td_cli otbr-cli networkdiag multicast-network
python3 -m td_cli otbr-cli networkdiag multicast-neighbors
python3 -m td_cli otbr-cli all

# OTBR REST API
# Note: fetch-all/fetch commands trigger an update device collection action and take time (minutes) to complete
python3 -m td_cli otbr-restapi --help
python3 -m td_cli otbr-restapi devices list
python3 -m td_cli otbr-restapi devices fetch
python3 -m td_cli otbr-restapi diagnostics list
python3 -m td_cli otbr-restapi diagnostics fetch-all
python3 -m td_cli otbr-restapi mesh-diagnostics fetch-all
python3 -m td_cli otbr-restapi download
python3 -m td_cli actions list

# mDNS
python3 -m td_cli mdns --help
python3 -m td_cli mdns thread # includes br, hap, matter
python3 -m td_cli mdns br     # border routers
python3 -m td_cli mdns hap    # Apple HomeKit Accessory Protocol (HAP) thread devices
python3 -m td_cli mdns matter # Matter thread devices

# Eve processing 
# Reads 'Eve Thread Network Layout.evethreadlayout' from data dir, enhances data and outputs td-eve-topology.json
python3 -m td_cli process-eve 

# Dataset merge
# Merge multiple thread topology JSON files into one consolidated file
python3 -m td_cli merge-dataset 
```

## Dashboard Webserver

Note: The tdash docker container automatically runs td_webserver.py when the container starts up.

tdash dashboard webserver commands
```bash
# listen on localhost
python3 -m td_webserver --host localhost --port 9165

# listen on all available network interfaces
python3 -m td_webserver --host 0.0.0.0 --port 9165
```

## Dataset Merge

The dataset merge capability combines multiple Thread topology JSON files from different sources (CLI, REST API, mDNS) into a single consolidated topology file. This enables comprehensive device information by merging complementary data from multiple sources.

### Merge Features

The merge system provides:

- **Identity-Based Merging:** Nodes are matched by `extaddr` (Extended MAC Address), ensuring correct device correlation across sources
- **Field Normalization:** Automatically handles both snake_case (CLI) and camelCase (REST API) field naming conventions
- **Composite Identity Matching:** 
  - Routes merged by `(owner_rloc16, destination_route_id)` composite identity
  - Children merged by `(parent_rloc16, child_extaddr)` composite identity
- **Sequence Number Precedence:** Uses RFC 1982 serial arithmetic for 8-bit sequence numbers with wraparound (0-255)
- **Partition Awareness:** Respects Thread partition boundaries for routing data
- **mDNS Integration:** Merges service discovery data (vendor, model, version) with Thread topology
- **Source Precedence:** REST API (highest) > CLI > mDNS > Eve (lowest) for conflict resolution
- **Conflict Tracking:** Logs all merge conflicts in `_merge_conflicts` field
- **Source Tracking:** Records all contributing files in `_source_files` field

### Running the Merge

```bash
# Basic merge with defaults
python3 -m td_cli merge-dataset

# Specify output file
python3 -m td_cli merge_dataset --output td-merged-topology-all.json

# With merge report
python3 -m td_cli merge_dataset --report-file td-merge-report.json

# With custom options
python3 -m td_cli merge-dataset --datadir /path/to/data --output my-merged.json


# Docker container
docker exec tdash python3 -m td_cli merge-dataset
```

### Input Files

The merge processes these files by default:

**Thread CLI Sources:**
- `td-otbr-cli-router-table.json` - Router table summary
- `td-otbr-cli-meshdiag-topology.json` - Mesh diagnostic topology
- `td-otbr-cli-networkdiag-fetch-all.json` - Network diagnostic data (fetch all device)
- `td-otbr-cli-networkdiag-multicast-network.json` - Multicast network data
- `td-otbr-cli-meshdiag-router-neighbortables.json` - Router neighbor tables

**Thread REST API Sources:**
- `td-otbr-restapi-devices.json` - Device list with detailed information
- `td-otbr-restapi-diagnostics.json` - Device diagnostics data

**mDNS Sources:**
- `td-mdns-scopes-br.json` - Border Router mDNS records (_meshcop._udp)
- `td-mdns-scopes-thread.json` - Thread device mDNS records
- `td-mdns-scopes-hap.json` - HomeKit Accessory Protocol records
- `td-mdns-scopes-matter.json` - Matter device records

**Native Sources:**
- `td-eve-topology.json` - Eve app topology export

### Output Format

The merged output (`td-merged-topology-all.json`) is a JSON array of device records with:

```json
[
  {
    "extaddr": "0011223344556677",
    "rloc16": "0x1400",
    "device_label": "Living Room HomePod",
    "route_data": {
      "id_sequence": 15,
      "route_data": [...]
    },
    "children": [...],
    "service_info": {
      "decoded_properties": {
        "vn": "Apple",
        "mn": "BorderRouter",
        "tv": "1.3.0"
      }
    },
    "_source_files": [
      "td-otbr-cli-networkdiag-fetch-all.json",
      "td-otbr-restapi-diagnostics.json",
      "td-mdns-scopes-br.json"
    ],
    "_merge_conflicts": [...]
  }
]
```

### Merge Behavior

**Identity Matching:**
- Primary identity: `extaddr` (immutable 64-bit EUI-64 address)
- Secondary: `omr_ipv6_addr` (stable OMR IPv6 address)
- Tertiary: `rloc16` (partition-scoped, may change)

**Route Data Merging:**
- Routes matched by `(owner_rloc16, route_id)` - no duplicates
- Highest `id_sequence` wins (with 8-bit wraparound: 5 > 250)
- Partition-aware: routes only valid within same `partition_id`

**Children Array Merging:**
- Children matched by `(parent_rloc16, child_extaddr)`
- `childId` is parent-local only (not globally unique)
- Prevents duplicate children with same extaddr

**mDNS Data Merging:**
- Timestamp precedence: newer `captured_at_epoch` wins
- Event priority: add > update > remove
- Service info deeply merged with nested structure preservation

**Field Conflicts:**
- Non-empty incoming values overwrite empty base values
- For conflicts between non-empty values: base wins, conflict logged
- Special handling for routes, children, and mDNS data

### Troubleshooting

See [doc/merge_thread_device_info.md](doc/merge_thread_device_info.md) for detailed troubleshooting guidance.

**Common Issues:**

1. **Missing input files:** Ensure all required JSON files exist in the data directory
2. **Partition conflicts:** Review `_merge_conflicts` field for partition-related issues
3. **Route duplicates:** Check that `id_sequence` is being set correctly in source data
4. **Performance:** Large networks (100+ nodes) may take 1-2 seconds; this is normal

For more details on merge implementation, see the [plan/](plan/) directory for phase documentation.

end
