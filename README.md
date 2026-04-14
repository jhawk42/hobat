# Thread Network Topology Dashboard


A set of tools to collect and display a thread mesh network in both a network topology view and table view. 

The tool collects dats from various dataset sources:
- Open Thread OTBR cli 
- Open Thread OTBR restapi
- Eve app
- mDNS

There are a number of existing useful Thread Dashboards and tools:
- Open Thread - OTBR 
- Home Assistant - Matter Server -JS
- Eve App as a list 


# Getting Started
docker container 
Python

# Details

Merge strategy notes

The dashboard and Python merge pipeline now support canonical identity matching across these fields:

- `rloc16`
- `extaddr`, `extAddress`, and `Extended MAC` as one canonical `extaddr` identity
- `omrIpv6Address`

Supported dashboard merge strategies:

- `none`: pass loaded JSON through without dashboard row merging
- `by-rloc16`: merge rows only when `rloc16` matches
- `by-identity`: merge rows when any canonical identity matches in this order of use: `rloc16`, canonical `extaddr`, `omrIpv6Address`

Merge normalization rules:

- identity values are trimmed and compared case-insensitively
- empty identifiers are ignored
- non-empty existing values are preserved during merge; conflicting incoming non-empty values are recorded as merge conflicts instead of overwriting the existing value
- merged rows and merged Python records retain source provenance in `_source_files`

-eof