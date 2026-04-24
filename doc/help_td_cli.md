usage: td_cli [-h] [--verbose] [--debug] [--output FILE]
              {otbr-cli,mdns,otbr-restapi,process-eve,merge-dataset,web-server}
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
  {otbr-cli,mdns,otbr-restapi,process-eve,merge-dataset,web-server}
    otbr-cli                    Scan otbr-cli commands
    mdns                        Scan Thread-related mDNS scopes
    otbr-restapi                Query otbr-restapi sub commands
    process-eve                 Parse and enhance an Eve Thread layout file
    merge-dataset               Merge Thread (otbr-cli, otbr-restapi, eve,
                                mdns) sources into one cache file
    web-server                  Start the web dashboard server

Data directory behavior:
    Data directory resolution precedence: 1) TD_DATA_DIR environment variable, 2) --datadir CLI argument, 3) defaults (/data when present, otherwise ./data under the current run directory).

Commands usage:
    otbr-cli
        usage: td_cli otbr-cli [-h] {network-dataset-info,router-table,meshdiag,networkdiag,all} ...

    otbr-restapi
        usage: td_cli otbr-restapi [-h] {download,client,rawclient} ...

    mdns
        usage: td_cli mdns [-h] [--browse-timeout SECONDS] [--haptcp] [--mattertcpsupported] [SCOPE]

    process-eve
        usage: td_cli process-eve [-h] ...

    merge-dataset
        usage: td_cli merge-dataset [-h] ...

    web-server
        usage: td_cli web-server [-h] [--host HOST] [--port PORT]
        options:
                --host HOST  Host to bind to (default: localhost)
                --port PORT  Port to listen on (default: 8087)

Subcommand help snapshots:
  otbr-cli
    usage: td_cli otbr-cli [-h]
                           {network-dataset-info,router-table,meshdiag,networkdiag,all}
                           ...

    positional arguments:
      {network-dataset-info,router-table,meshdiag,networkdiag,all}
        network-dataset-info        Scan and save network dataset info
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
    usage: td_cli otbr-cli networkdiag [-h] {topology} ...

    positional arguments:
      {topology}
        topology  Scan networkdiag topology

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
    usage: td_cli otbr-restapi [-h] {download,client,rawclient} ...

    positional arguments:
      {download,client,rawclient}
        download            Download OTBR REST API endpoints to JSON files
        client              Call OTBR REST API client commands (flattened output)
        rawclient           Call OTBR REST API client commands (raw envelopes)

  process-eve
    usage: td_cli process-eve [-h]

  merge-dataset
    usage: td_cli merge-dataset [-h]

  web-server
    usage: td_cli web-server [-h] [--host HOST] [--port PORT]

    options:
      -h, --help   show this help message and exit
      --host HOST  Host to bind to (default: localhost)
      --port PORT  Port to listen on (default: 8087)
