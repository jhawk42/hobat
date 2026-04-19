# Thread Mesh Network Dashboard

Thread Mesh Network Dashboard (tdash) is a Python toolkit and browser-based dashboard for visualizing and monitoring [Thread](https://github.com/openthread/openthread) mesh networks.  It collects network data from several sources (OTBR, mDNS, Eve), normalizes and merges that data, and renders it as an interactive topology graph and table in HTML dashboard page.

## Dataset Sources
The tool collects data from various dataset sources including:
- otbr-cli: OpenThread OTBR cli. Executes ot-ctl command line tool against an OTBR instance to scan for information on thread devices. 
- otbr-restapi: OpenThread OTBR restapi. Web calls to OTBR instance restapi to collect information on thread devices.
- mDNS: Multicast DNS allows devices on a local network to discover each other and services
- Eve app: The native Eve JSON file has useful information for Apple Home thread mesh networks. This tool enhances the native Eve app JSON file with RLOC16 in hex format, etc

## Getting Started

Pipeline steps:

{scan|web} -> {process|merge} -> web-server -> dashboard

```
python3 tdash.py --help
```

Command line options for scan otbr-cli for thread node information
```
python3 tdash.py scan otbr-cli --help

python3 tdash.py scan otbr-cli meshdiag topology
python3 tdash.py scan otbr-cli networkdiag topology
python3 tdash.py scan otbr-cli all
```
Command line options for web otbr-restapi
```
python3 tdash.py web otbr-restapi --help

python3 tdash.py web otbr-restapi download
```

Start web server that hosts the dashboard HTML page.
```
python3 tdash.py web-server 
```

Docker container
```
TODO 
```

## tdash.py --help
```
usage: tdash [-h] [--verbose] [--debug] [--output FILE] {scan,web,process,merge,web-server} ...

Thread Network Topology Dashboard CLI

Options:
  -h, --help            show this help message and exit
  --verbose, -v         Enable verbose (INFO) logging
  --debug, -d           Enable debug logging
  --output FILE, -o FILE
                        Write command output to FILE

These are the high level commands:
  {scan,web,process,merge,web-server}
    scan                Scan (otbr-cli or mdns) for thread device details
    web                 Web call to OTBR REST API for thread device details
    process             Process (eve) raw data files
    merge               Merge datasets (otbr-cli, otbr-restapi, eve, mdns)
    web-server          Start the web dashboard server

Commands usage:
  scan
    usage: tdash scan [-h] {otbr-cli,mdns} ...
    scan otbr-cli       Scan otbr-cli commands
    scan mdns           Scan Thread-related mDNS scopes

  web
    usage: tdash web [-h] {otbr-restapi} ...
    web otbr-restapi    otbr-restapi sub commands

  process
    usage: tdash process [-h] {eve} ...
    process eve         Parse and enhance an Eve Thread layout file

  merge
    usage: tdash merge [-h] {dataset,data} ...
    dataset             Merge Thread (otbr-cli, otbr-restapi, eve, mdns) sources into one cache file

  web-server
    usage: tdash web-server [-h] [--host HOST] [--port PORT]
    options:
        --host HOST  Host to bind to (default: localhost)
        --port PORT  Port to listen on (default: 8087)
```

## Notes
TODO

-eof