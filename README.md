# tdash - Thread mesh dashboard and tools

tdash is a Thread mesh dashboard and toolkit for visualizing topology, diagnosing device health, and managing multi-source network data with low mesh impact. It collects data from OTBR CLI, OTBR REST API, mDNS scopes, and optional Eve exports, then serves an interactive topology and table experience from local cache snapshots. This cache-first approach improves troubleshooting speed while reducing live query load on constrained Thread devices.

Environment: tdash runs on Debian-based Linux in a Docker container or directly on a host. The dashboard is browser-based and works well from desktops and phones. See [tdash backstory](https://github.com/jhawk42/smarthome/blob/main/tdash/tdash_backstory.md) for details.


<a href="https://github.com/jhawk42/smarthome/blob/main/tdash/images/tdash1.jpg?raw=true"> <img src="https://github.com/jhawk42/smarthome/blob/main/tdash/images/tdash1.jpg?raw=true" alt="tdash1" width="200px" >
<a href="https://github.com/jhawk42/smarthome/blob/main/tdash/images/tdash2.jpg?raw=true"> <img src="https://github.com/jhawk42/smarthome/blob/main/tdash/images/tdash2.jpg?raw=true" alt="tdash2" width="200px" >
<a href="https://github.com/jhawk42/smarthome/blob/main/tdash/images/tdash3.jpg?raw=true"> <img src="https://github.com/jhawk42/smarthome/blob/main/tdash/images/tdash3.jpg?raw=true" alt="tdash3"  height="150px" >
<a href="https://github.com/jhawk42/smarthome/blob/main/tdash/images/tdash4.jpg?raw=true"> <img src="https://github.com/jhawk42/smarthome/blob/main/tdash/images/tdash4.jpg?raw=true" alt="tdash4" height="150px" >


Jump to: [Getting Started](#getting-started) [help docs](./doc/) [td_cli](./doc/help_td_cli.md) [td cli rest-api](./doc/help_td_restapi_cli.md) [td_webserver](./doc/help_td_webserver.md) [env vars](./doc/help_env_vars.md) [openthread](https://github.com/openthread/openthread)

## Overview

tdash follows a cache-first operating model: collect Thread data from OTBR and related sources, store normalized snapshots in the local data directory, and run most dashboard analysis from cache.

The dashboard renders both topology and table views and supports diagnostics workflows across node roles, link quality, MAC counters, and MLE counters. You can trigger refresh actions when you need fresh data, while keeping day-to-day analysis low impact on the live mesh.

This model reduces repeated network queries, lowers load on constrained Thread devices (including battery-powered sleepy end devices), and supports predictable operations with scheduled data collection. 

Tip: Run a crontab task to run td_cli.py commands early in the morning during off peak time e.g. 5:15am.

The tdash dashboard and tools provide:

### CLI toolkit

`td_cli` collects Thread device data and writes structured JSON snapshots for offline query and processing. Supported sources include:
- Open Thread Border Router (OTBR): otbr-cli via OTBR ot-ctl commands.
- Open Thread Border Router (OTBR): otbr-restapi via OTBR REST endpoints.
- Multicast DNS (mDNS) records.
- Eve app Thread layout file.

### Dashboard

The `tdash.html` browser dashboard supports topology and table views for visualizing and querying Thread mesh data.

Search fields include rloc16, extAddress, deviceLabel, name, and related identity fields.

Filter capabilities include:
- Thread node roles and types: border router, router, ftd, sed/mtd child nodes, and related classes.
- Thread link quality conditions: LQ3, LQ2, LQ1, plus ratio-oriented link quality checks.
- Diagnostics-focused conditions: MAC counters (packets, frame errors, and related counters) and MLE counters (partition changes, parent attempt changes, and role time durations).

See [Dashboard Features](#dashboard-features)

### Python webserver

`td_webserver` hosts the dashboard UI and provides REST API endpoints used by the dashboard for cached data access and refresh operations. For longer actions, the webserver launches data collection workflows and serves results from the cache model used by tdash.

### Extended MAC Address (extAddress) to deviceLabel

Thread device labeling uses a simple JSON lookup file that maps extAddress (Extended MAC Address) values to operator-friendly device labels. See [Device Labeling](#create-device-labeling-file) below for details.

## Dataset Sources

### otbr-cli

The otbr-cli dataset source fetches Thread device data from an OpenThread Border Router (OTBR) instance via ot-ctl commands. **Note:** ot-ctl bypasses the OTBR RESTAPI cache. By default use docker exec to call into the "otbr" docker container. Common ot-ctl commands used:
- router table (quick, seconds, summary)
- meshdiag topology (quick, seconds, summary). Optionally also calls these sub commands (long, more detailed data) routerneighbortable, childtable, childip6
- networkdiag (takes time, minutes, detailed). The td_cli networkdiag supports multicast (quick, full thread devices) and fetch-all (all devices including routers, full thread devices, SED/minimal thread devices) 

Note: Also supports calling otbr on the host.

### otbr-restapi

The otbr-restapi dataset source fetches Thread device data from the OpenThread Border Router (OTBR) REST API endpoint.

- node: 	     get, state get, state set, dataset active get, dataset active set	Read/mutate local OTBR node and active dataset
- devices:	 list, get, fetch	List, read, or refresh device collection
- diagnostics: list, get, fetch, fetch-all	Read or fetch network diagnostics
- mesh-diagnostics:	children, child-ipv6, router-neighbors, fetch, fetch-all
- actions:	 list, get, enqueue (update-device-collection,get-network-diagnostic). Inspect and enqueue OTBR action tasks
- download:	 download OTBR REST API endpoint snapshots to JSON files

By default otbr-restapi uses `HOST 127.0.0.1` and `PORT 8081`. Command lines option `--host HOST` and `--port PORT` can be used to specify HOST and PORT via the cli.

The same environment varables that the OTBR docker container uses can also be used to specifify HOST `OT_REST_LISTEN_ADDR` and PORT `OT_REST_LISTEN_PORT`.

See [env vars](./doc/help_env_vars.md) for details.

The OTBR device collection is populated asynchronously by `updateDeviceCollectionTask`. Use `devices fetch` rather than assuming a prior `devices list` is complete. Full diagnostic sweeps return structured per-device outcomes and clear the diagnostics collection once by default; use `--preserve-diagnostics` when sharing OTBR with another client. Action POSTs are never retried after an ambiguous response because OTBR does not expose an idempotency key.

See [OTBR REST API CLI](doc/help_td_restapi_cli.md) for timing and output controls and [OTBR REST API validation](doc/otbr_restapi_validation.md) for tested compatibility and the hardware lab procedure.

### mdns
The mdns dataset source fetches thread-related mdns scope records: _meshcop, _hap, _matter for Thread device data.
- thread:      All thread scopes _meshcop, _hap, _matter      
- br:          Thread Border Routers in _meshcop scope
- hap:         Apple HomeKit Accessory Protocol (HAP) devices in _hap scope
- matter:      Matter over thread devices in _matter scope

## eve layout
Eve app layout json file: Enhances and visualizes the eve layout file data.
- The Eve app (iOS) supports querying a thread network for devices and sharing device data to a JSON layout file.
- Note: It appears that the Eve app needs at least one powered Eve thread device (smart plug) to collect data as the eve device has diagnostics code in device firmware to collect Thread device data.
- Eve app works well with Apple Homekit (HAP) thread networks.

## Getting Started

The tdash dashboard and tools can run in a docker container or directly the host.

Note: **Setup: Manual on a host** - To manually run on a host, git clone this repro onto the host. See details below to manually run td_cli.py and td_webserver.py commands.

### Pull tdash docker container

The tdash docker container hosts the td_cli and web server.

```bash
docker pull ghcr.io/jhawk42/tdash:latest
```


### Create Data Directrory

tdash uses a data directory for:
  - Caching Thread device data
  - Extended MAC Address to device label via a side json file
  - Loading eve layout file

Create a data directory and map this directory into the docker container via docker run. See the ***Start the tdash docker container*** section

```bash
mkdir $PWD/data
export TD_DATA_DIR=$PWD/data
```

The TD_DATA_DIR environment variable is used by the tdash tools (cli, webserver, container) to find the data directory. If not specified in the docker container the TD_DATA_DIR will automatically resolve to: /data directory within the docker container.


### Copy Eve layout file (optional)

To use the tdash dashbaord to visualize Eve app layout shared file, copy the 'Eve Thread Network Layout.evethreadlayout' into the data directory. 
Steps: In Eve app -> Settings -> Thread Network -> wait a couple of minutes (5 min+ for larger thread networks) for the list to populate -> click the share icon in the upper right -> Save to files 
- Quick: Save to a usb drive attached top the phone. On the Linux machine copy from usb drive into the tdash data directory.
- Long: Save to iCloud Drive Download -> Desktop -> use scp to copy to Linux machine tdash data directory running tdash tools.

Copy from desktop to Linux
```bash
scp "Eve Thread Network Layout.evethreadlayout" user@hostname:/your/directory/here/tdash/data
```

### Create Device Labeling file

To enable device labeling via the lookup json file, add a file named `td-static-extaddr-device-label.json` with the format below into the data directory. Map this directory into the docker container via docker run. See below for example.

The td_cli commands and dash dasboard will use the file if it exists to lookup extaddress (Extended MAC Address) to deviceLabel mapping. The td_cli commands enhance the collect Thread device data with the deviceLabel. The thread dashboard will use the extAddress deviceLabel to lookup extAddress to device label mapping. 

```
nano $PWD/data/td-static-extaddr-device-label.json
```
Edit the td-static-extaddr-device-label.json as you discover thread devices in the thread network. 
The extAddress is the thread device Extended MAC Address.
The deviceLabel is the name you assign to the thread device.

Sources for device label names: 
- Matching thread device identities like ipv6 addresses in  mDNS records (_meshcop._udp, _hap._udp)
- Eve layout file is a good place to find thread device names.
- **Note:** The td_cli merge-extaddr command can update the lookup file using mdns records for border routers.

Note _matter._tcp does not have device names. Try using the 
[Home Assistant Open Home Foundation Matter Server](https://github.com/matter-js/python-matter-server) as it has great Matter over Thread support.

Example format of the td-static-extaddr-device-label.json file.
```JSON
[
    {
        "extAddress": "eeeaffeaffeaffe1",
        "deviceLabel": "Device 1"
    },
    {
        "extAddress": "eeeaffeaffeaffe2",
        "deviceLabel": "Device 2"
    },
    {
        "extAddress": "eeeaffeaffeaffe3",
        "deviceLabel": "Device 3"
    }
]
```

### Start the tdash docker container

Notes: 
- **Data Directory**: Map a local data directory into the tdash docker container data directory via docker volume.
- **Default PORT**: The tdash docker container automatically starts the td_webserver.py with the dashboard. Default port is 9165.
- **Docker Socket**: The otbr-cli datasetsource requires the tdash docker container to have access to the docker socket to enable td_cli otbr-cli to call between docker containers. This enables td_cli in the tdash container to call into the otbr container to execute ot-ctl commands via: docker exec -it otbr /usr/sbin/ot-ctl to fetch Thread device data.
- **Optional Environment Variables**:
  - data directory: TD_DATA_DIR
  - td_webserver.py: HOST, PORT 
  - otbr-cli access: OTBR docker container name: TD_OTBR_CONTAINER_NAME
  - otbr-restapi access: OTBR instance OT_REST_LISTEN_ADDR, OT_REST_LISTEN_PORT
  - See [Environment Variables](./doc/help_env_vars.md) for more details.

```bash
docker run --name=tdash -d \
  --network=host \
  --volume $PWD/data:/data \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --restart=unless-stopped \
  tdash:latest 
```

## Dashboard Webserver - manual startup

Note: The tdash docker container automatically executes td_webserver.py when the container starts up.

tdash dashboard webserver commands
```bash
# listen on localhost
python3 -m td_webserver --host localhost --port 9165

# listen on all available network interfaces
python3 -m td_webserver --host 0.0.0.0 --port 9165
```


## Open the tdash dashboard web page in a browser

Open the tdash dashboard in a browser. 
Default PORT is 9165.

```
# localhost
http://localhost:9165/

# ip address
http://<your-host-ip-addr>:9165/
```

Note: The tdash webserver will automatically use td_cli.py to discover the thread network and refresh the cached data files:
- When cached data files don't exist.
- When cached data files are stale beyond a certain threshold. See help for details on environment variables.


## Dashboard Features

The tdash web dashboard provides comprehensive visualization and querying capabilities:

- **Fetch from Multiple Data Sources:** Supports otbr-cli (meshdiag, networkdiag), otbr-restapi, mDNS, and Eve topology datasets
- **Multiple Views:** Topology view (graph) and Table view for different analysis needs
- **Search:** Search devices by rloc16, extAddress, deviceLabel, routerId, and a number other identity fields
- **Filtering:** Filter by device type (border router, router, FTD, MTD), link quality (LQ3/LQ2/LQ1), and diagnostic criteria
- **Detail Panels:** Click any device to view comprehensive details organized into sections (Keys, Highlights, Connections, Routes & Links)
- **Device Fields:** Supports detailed device information including:
  - Identity: rloc16, extAddress, deviceLabel, omrIpv6Addr
  - Role & Status: type, mode flags, leaderData, border router/leader indicators
  - Connectivity: link quality, connectivity metrics, neighbor/child counts
  - Diagnostics: MLE counters, MAC counters, vendor information
- **Field Naming:** Canonical merged/dashboard fields are camelCase

For complete field reference and dashboard usage, see [doc/dashboard_ui_fields.md](doc/dashboard_ui_fields.md).



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
# Use -fetch-all sparingly. Consumes MTD/SED battery power.
python3 -m td_cli otbr-cli networkdiag fetch-all
python3 -m td_cli otbr-cli networkdiag multicast-network
python3 -m td_cli otbr-cli networkdiag multicast-neighbors
python3 -m td_cli otbr-cli topology

# OTBR REST API
# Note: fetch-all/fetch commands trigger an update device collection action and take time (minutes) to complete
python3 -m td_cli otbr-restapi --help
python3 -m td_cli otbr-restapi devices list
python3 -m td_cli otbr-restapi devices fetch
python3 -m td_cli otbr-restapi diagnostics list
# Use -fetch-all sparingly. Consumes MTD/SED battery power.
python3 -m td_cli otbr-restapi diagnostics fetch-all
python3 -m td_cli otbr-restapi mesh-diagnostics fetch-all
python3 -m td_cli otbr-restapi actions list
python3 -m td_cli otbr-restapi topology

# mDNS
python3 -m td_cli mdns --help
python3 -m td_cli mdns thread # includes br, hap, matter
python3 -m td_cli mdns br     # border routers
python3 -m td_cli mdns hap    # Apple HomeKit Accessory Protocol (HAP) thread devices
python3 -m td_cli mdns matter # Matter thread devices

# Eve processing 
# Reads 'Eve Thread Network Layout.evethreadlayout' from data dir, enriches data and outputs td-eve-topology.json
python3 -m td_cli process-eve 

# Dataset merge
# Merge multiple thread topology JSON files into one consolidated file
python3 -m td_cli merge-dataset 
```

## Dataset Merge

The dataset merge capability combines multiple Thread topology JSON files from different sources (CLI, REST API, mDNS) into a single consolidated topology file. This enables comprehensive device information by merging complementary data from multiple sources.

### Merge Features

The merge system provides:

- **Identity-Based Merging:** Nodes are matched by `extAddress` (Extended MAC Address), `omrIpv6Address` (Off-Mesh Routable IPv6 address),`rloc16` (Routing Locator 16-bit) ensuring correct device correlation across sources.
- **Field Normalization:** Automatically handles both snake_case (CLI) and camelCase (REST API) field naming conventions
- **Composite Identity Matching:** 
  - Routes merged by `(owner_rloc16, destination_route_id)` composite identity
  - Children merged by `(parent_rloc16, child_extaddr)` composite identity
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

end
