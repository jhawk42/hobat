# tdash - thread mesh network dashboard

This tdash repo has a Python cli toolkit that fetches thread device info from a thread network and a browser dashboard for visualizing and monitoring Thread mesh networks.  [openthread](https://github.com/openthread/openthread) 


It fetches thread device info from sources like: otbr-cli, otbr-restapi, mDNS (Multicast DNS) records and the eve thread json format layout file shared from the Eve app. The td_cli tool can also merge these various sources for consolidated thread info and visualization. It also provides a device labeling mechanism using a extaddr (Extended MAC Address) to device_label lookup file. See below for details.

## Dataset Sources
- otbr-cli: Fetches info from an OpenThread Border Router (OTBR) instance via ot-ctl commands for thread device info. By default use docker exec to call into the "otbr" docker container. Also support calling otbr on the host. Common ot-ctl commands used:
  - router table (quick, seconds, summary)
  - meshdiag topology (quick, seconds, summary). 
    - Optionally also calls these sub commands (long, more detailed info) routerneighbortable, childtable, childip6
  - networkdiag (takes time, minutes, detailed). The td_cli networkdiag supports multicast (quick, full thread devices) and poll (all devices including routes, full thread devices, minimal thread devices) 
- otbr-restapi: Fetches info from an OpenThread Border Router REST API for thread device info.
- mdns: Fetches thread-related mdns scope records: _meshcop, _trel, _hap, _matter for thread device info.
- eve layout json file: Enhances and visualizes the eve layout file info. The Eve app (iOS) supports querying a thread network for devices and sharing device info to a JSON layout file. Note: Eve app needs at least one Eve thread device like a smart outlet to collect info as the eve device has diagnostics code in device firmware to collect thread device info. Eve app works well with Apple Home (HAP) thread networks.

## Getting Started

The tdash can be run in a docker container or manually run on a host.

### Setup - manual on a host

To run manually on the host, git clone this repro onto the host. Details below to manually run td_cli.py and td_webserver.py commands.

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

### Open the tdash web dashboard in a browser

Open the tdash web dashboard in a browser

```
# localhost
http://localhost:9165/

# ip address
http://<your-host-ip-addr>:9165/
```

Note: The tdash webserver will automatically use td_cli.py to refresh the thread network cached info files:
- When cached info files don't exist.
- When cached info files are stale beyond a certain threshold.

### tdash cli examples

See below for additional manual run on host td_cli.py commands 

```
# direct on host
python3 td_cli.py --help
```

The tdash docker container cli entry point is td_cli.py.

```
# docker exec into tdash container: run bash and then td_cli.py commands.

docker exec -it tdash /bin/bash $*

# bash in tdash docker container: td_cli.py examples:
python3 td_cli.py --help

usage: td_cli [-h] [--verbose] [--debug] [--output FILE] [--datadir DIR] {otbr-cli,mdns,otbr-restapi,process-eve,merge-dataset} ...

python3 td_cli.py otbr-cli router-table
```

docker exec into tdash: run td_cli.py commands
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
python3 -m td_cli otbr-cli thread-network-info
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
python3 -m td_cli otbr-restapi diagnostics list
python3 -m td_cli otbr-restapi download

# mDNS
python3 -m td_cli mdns --help
python3 -m td_cli mdns thread # includes br, hap, matter
python3 -m td_cli mdns br     # border routers
python3 -m td_cli mdns hap    # Apple HomeKit Accessory Protocol (HAP) thread devices
python3 -m td_cli mdns matter # Matter thread devices

# Eve processing 
# Reads thread-eve-layout.json from data dir, enhances data and outputs td-eve-topology.json
python3 -m td_cli process-eve 

# Dataset merge
# Merge multiple thread topology JSON files into one consolidated file
python3 -m td_cli merge-dataset 
```

# Dashboard Webserver

Note: The tdash docker container automatically runs td_webserver.py when the on container starts up.

tdash dashboard webserver commands
```bash
# localhost
python3 -m td_webserver --host localhost --port 9165
# listen on all available network interfaces
python3 -m td_webserver --host 0.0.0.0 --port 9165
```

# Device Labeling

To do manual device labeling, add a file named td-static-extaddr-device-label.json with the format below into the data directory.

The td_cli commands will use the file to lookip extaddr (Extended MAC Address) per device and enhance the collect thread device info. It is also used in the thread dashboard to lookup human readable device labels.

```
#td-static-extaddr-device-label.json

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
end