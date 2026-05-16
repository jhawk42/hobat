# Thread Mesh Network Dashboard

Thread Mesh Network Dashboard (tdash) is a Python toolkit for fetching thread device info and a browser dashboard for visualizing and monitoring Thread mesh networks.  [openthread](https://github.com/openthread/openthread) 

It collects thread device info from sources like: otbr-cli, otbr-restapi, mDNS (Multicast DNS) records, and the eve thread json format layout file shared from the Eve app. The td_cli tool can also merge these various sources for enhanced thread info and  visualization.

## Dataset Sources
- otbr-cli: Fetches info from an OpenThread Border Router (OTBR) instance via ot-ctl commands for thread device info. By default calls  "otbr" docker container. Also support calling otbr on the host. Main ot-ctl commands used:
  - router table (quick, seconds, summary)
  - meshdiag topology (quick, seconds, summary). 
    - Optionally also calls these sub commands (long, more detailed info) routerneighbortable, childtable, childip6
  - networkdiag (takes time, minutes, detailed). The td_cli networkdiag supports multicast (quick, ftd) and poll (all devices) 
- otbr-restapi: Fetches info from an OpenThread Border Router REST API for thread device info.
- mdns: Fetches thread-related mdns scope records: _meshcop, _trel, _hap, _matter for thread device info.
- eve layout json file: Enhances and visualizes the eve layout file info. The Eve app (iOS) supports querying a thread network for devices and sharing device info to a JSON layout file. Note: Eve app needs at least one Eve thread device like a smart outlet to collect info as the eve device has diagnostics code in device firmware to collect thread device info. Eve app works well with Apple Home (HAP) thread networks.

## Getting Started

### Setup - docker container

The tdash docker container hosts the td_cli and web server.

```
docker pull ghcr.io/jhawk42/tdash:latest
```

Notes: 
- The tdash docker container needs access to the docker socket for docker exec calls between docker containers for the tdash container to call into otbr container to execute ot-ctl commands.
- The tdash docker container automatically starts the td_webserver.py.

```
docker run --name=tdash -d \
  --network=host \
  --volume $PWD/data:/data \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --restart=unless-stopped \
  tdash:latest 
```

### Connect to TDash dashboard

```
#localhost
http://localhost:8087/

# ip address
http://<your-host-ip-addr>:8087/
```

### tdash cli examples

See below for more direct on host td_cli.py commands 

```
# direct on host
python3 td_cli.py --help
```

The tdash docker container cli entry point is td_cli.py.

```
# docker exec into tdash container, run bash and then td_cli.py commands.

docker exec -it tdash /bin/bash $*

# bash in tdash docker container examples:
python3 td_cli.py --help

usage: td_cli [-h] [--verbose] [--debug] [--output FILE] [--datadir DIR] {otbr-cli,mdns,otbr-restapi,process-eve,merge-dataset} ...

python3 td_cli.py otbr-cli router-table
```

docker exec into tdash and run td_cli.py commands
```
docker exec -it tdash /usr/local/bin/python3 td_cli.py otbr-cli router-table
docker exec -it tdash /usr/local/bin/python3 td_cli.py --debug otbr-cli router-table
```

### tdash cli commands (docker or direct on host)

These commands can be run inside the tdash docker container.
They can also be run directly on the host if you are running without docker.

```bash
# Help
python3 td_cli.py --help

usage: td_cli [-h] [--verbose] [--debug] [--output FILE] [--datadir DIR] {otbr-cli,mdns,otbr-restapi,process-eve,merge-dataset} ...

# Common commands:

# OTBR CLI
python3 -m td_cli otbr-cli --help
python3 -m td_cli otbr-cli network-dataset-info
python3 -m td_cli otbr-cli router-table
python3 -m td_cli otbr-cli meshdiag topology
python3 -m td_cli otbr-cli meshdiag routerneighbortable
python3 -m td_cli otbr-cli meshdiag childtable
python3 -m td_cli otbr-cli meshdiag childip6
python3 -m td_cli otbr-cli meshdiag all
python3 -m td_cli otbr-cli networkdiag topology-poll
python3 -m td_cli otbr-cli networkdiag topology-multicast-network
python3 -m td_cli otbr-cli networkdiag topology-multicast-neighbors
python3 -m td_cli otbr-cli all

# OTBR REST API
python3 -m td_cli otbr-restapi --help
python3 -m td_cli otbr-restapi client diagnostics list
python3 -m td_cli otbr-restapi download

# mDNS
python3 -m td_cli mdns --help
python3 -m td_cli mdns thread # includes br, hap, matter
python3 -m td_cli mdns br     # border routers
python3 -m td_cli mdns hap.   # Apple HomeKit Accessory Protocol (HAP) thread devices
python3 -m td_cli mdns matter # Matter thread devices

# Eve processing 
python3 -m td_cli process-eve # Reads thread-eve-layout.json from data dir, enhances data and outputs td-eve-topology.json

# Dataset merge
python3 -m td_cli merge-dataset # Merge multiple thread topology JSON files into one consolidated merged file.
```

# Dashboard Webserver

Note: The tdash docker container automatically runs td_webserver.py on container startup.

tdash dashboard webserver commands
```bash
# localhost
python3 -m td_webserver --host localhost --port 8087
# listen on all available network interfaces
python3 -m td_webserver --host 0.0.0.0 --port 8087
```

