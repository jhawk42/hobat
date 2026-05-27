usage: td_cli [-h] [--verbose] [--debug] [--output FILE]
              {otbr-cli,mdns,otbr-restapi,process-eve,merge-dataset}
              ...

Thread Network Topology Dashboard CLI

Options:
  -h, --help                    show this help message and exit
  --verbose, -v                 Enable verbose (INFO) logging
  --debug, -d                   Enable debug logging
  --output FILE, -o FILE        Write command output to FILE
  --datadir DIR                 Data directory for JSON reads/writes when
                                TD_DATA_DIR is not set. If omitted and
                                TD_DATA_DIR is unset: use /data when present;
                                otherwise create/use ./data under the current
                                run directory.

These are the common commands:
  {otbr-cli,mdns,otbr-restapi,process-eve,merge-dataset}
    otbr-cli                    Scan otbr-cli commands
    mdns                        Scan Thread-related mDNS scopes
    otbr-restapi                Query otbr-restapi sub commands
    process-eve                 Parse and enhance an Eve Thread layout file
    merge-dataset               Merge Thread (otbr-cli, otbr-restapi, eve,
                                mdns) sources into one cache file

Data directory behavior:
    Data directory resolution precedence: 1) TD_DATA_DIR environment variable, 2) --datadir CLI argument, 3) defaults (/data when present, otherwise ./data under the current run directory).

Commands usage:
    otbr-cli
        usage: td_cli otbr-cli [-h] {thread-network-info,router-table,meshdiag,networkdiag,all} ...

    otbr-restapi
        usage: td_cli otbr-restapi [-h] {download,node,devices,diagnostics,actions,mesh-diagnostics,topology} ...

    mdns
        usage: td_cli mdns [-h] [--browse-timeout SECONDS] [--haptcp] [--mattertcpsupported] [SCOPE]

    process-eve
        usage: td_cli process-eve [-h] ...

    merge-dataset
        usage: td_cli merge-dataset [-h] ...

Subcommand help snapshots:
  otbr-cli
    usage: td_cli otbr-cli [-h]
                           {thread-network-info,router-table,meshdiag,networkdiag,all}
                           ...

    positional arguments:
      {thread-network-info,router-table,meshdiag,networkdiag,all}
        thread-network-info        Scan and save thread network info
        router-table                Scan and save router table
        meshdiag                    Mesh diagnostic scans
        networkdiag                 Network diagnostic scans
        all                         Run all otbr-cli scans

  otbr-cli meshdiag
    usage: td_cli otbr-cli meshdiag [-h]
                                    {topology,routerneighbortable,childtable,childip6,all}
                                    ...

    positional arguments:
      {topology,routerneighbortable,childtable,childip6,all}
        topology            Scan meshdiag topology
        routerneighbortable
                            Scan meshdiag router-neighbour table
        childtable          Scan meshdiag child table
        childip6            Scan meshdiag child IPv6 addresses
        all                 Run all meshdiag scans

  otbr-cli networkdiag
    usage: td_cli otbr-cli networkdiag [-h] {fetch-all,multicast-network,multicast-neighbors} ...

    positional arguments:
      {fetch-all,multicast-network,multicast-neighbors}
        fetch-all       Scan and poll networkdiag topology (unicast, router-by-router)
        multicast-network
                            Scan networkdiag topology via multicast to all Thread devices (ff03::1)
        multicast-neighbors
                            Scan networkdiag topology via multicast to one-hop neighbors (ff02::1)

  mdns
    usage: td_cli mdns [-h] [--browse-timeout SECONDS] [--haptcp]
                       [--mattertcpsupported]
                       [SCOPE]

    positional arguments:
      SCOPE                 Scope filter: thread | br | hap | matter (default:
                            thread)

    options:
      -h, --help            show this help message and exit
      --browse-timeout SECONDS
                            Seconds of idle time before auto-exit (default: 10, or
                            TD_MDNS_BROWSE_TIMEOUT env var)
      --haptcp              Also browse _hap._tcp.local. (Wi-Fi HomeKit
                            accessories). Applies when scope is 'thread' or 'hap'.
                            Off by default.
      --mattertcpsupported  Include _matter._tcp records where T=1 (TCP
                            supported). By default those records are excluded.

  otbr-restapi
    usage: td_cli otbr-restapi [-h] [--host HOST] [--port PORT] [--base-url URL]
                               [--timeout SECS] [--accept MIME] [--raw]
                               [--poll-interval FLOAT] [--poll-timeout FLOAT]
                               [--no-progress] [--no-auto-output]
                               {download,node,devices,diagnostics,actions,mesh-diagnostics,topology}
                               ...

    positional arguments:
      {download,node,devices,diagnostics,actions,mesh-diagnostics,topology}
        download            Download OTBR REST API endpoints to JSON files
        node                Read or mutate local OTBR node data
        devices             Read OTBR devices
        diagnostics         Read OTBR network diagnostics
        actions             Read or enqueue OTBR task actions
        mesh-diagnostics    Fetch mesh-diagnostic TLVs (children, childIpv6,
                            routerNeighbors)
        topology            Full topology sweep: devices fetch + diagnostics
                            fetch-all + mesh-diagnostics fetch-all

    options:
      -h, --help            show this help message and exit
      --host HOST           OTBR REST API host (forwarded to otbr_restapi_cli)
      --port PORT           OTBR REST API port (forwarded to otbr_restapi_cli)
      --base-url URL        Override host/port with a full base URL (forwarded)
      --timeout SECS        HTTP request timeout in seconds (forwarded)
      --accept MIME         Default Accept header (forwarded)
      --raw                 Return raw API envelopes instead of flattened output
                            (forwarded)
      --poll-interval FLOAT
                            Seconds between action status polls (forwarded)
      --poll-timeout FLOAT  Max seconds to wait for an action to complete
                            (forwarded)
      --no-progress         Suppress per-device progress output (forwarded)
      --no-auto-output      Disable automatic output file naming (forwarded)

  process-eve
    usage: td_cli process-eve [-h]

  merge-dataset
    usage: td_cli merge-dataset [-h]
