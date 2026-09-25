# Data Directory Model

Hobat uses one effective data directory for collector output, cached snapshots,
operator-managed inputs, merge output, and device labels.

## Resolution Order

1. `--datadir DIR`
2. `TD_DATA_DIR`
3. `/data` when that directory exists
4. `./data` under the current working directory

`util_data.resolve_data_dir_with_source()` owns this policy. User-supplied paths
are expanded and resolved to absolute paths. The local default is created when
selected; an explicit path or environment path must be usable by the caller.

```bash
# CLI option overrides the environment
TD_DATA_DIR=/tmp/env-data PYTHONPATH=src python3 -m td_cli \
  --datadir /tmp/cli-data otbr-cli router-table

# Environment-selected directory
TD_DATA_DIR=/tmp/td-data PYTHONPATH=src python3 -m td_cli mdns thread

# Standalone web server
PYTHONPATH=src python3 -m td_webserver --datadir ./data
```

`--datadir` is a top-level `td_cli` option and must precede its command. The
OTBR REST wrapper also accepts a forwarded `--datadir` after `otbr-restapi` and
before the REST subcommand.

## File Ownership

- Collectors atomically write final snapshots before returning success.
- Long collectors may update sibling `.partial.json` checkpoints.
- REST topology also writes `.outcome.json` per-device completion summaries.
- Final Thread-source snapshots have sibling `.network.json` instance scopes.
- `merge-dataset` reads selected snapshots and atomically writes its merged
  output and optional report.
- The web server reads the effective directory and invokes `td_cli --datadir`
  with the same path when regeneration is needed.
- Eve layout, Thread Tools diagnostics, and the static label map can be supplied
  by the operator.

Atomic replacement protects readers from partial files. It does not serialize
independent writer processes; concurrent external writes remain last-write-wins.

For `td-<source>-<name>.json`, the sidecar is
`td-<source>-<name>.network.json`. `util_data.save_final_json()` writes it
after the final snapshot, with `extPanId` (16 lowercase hex digits or null),
`networkName`, `provenance` (`observed`, `operator`, or `unknown`), `reason`,
`observedAt`, `sources`, and `snapshotSha256`. The digest binds the scope to
the exact final snapshot bytes. `merge_dataset.py` reads and validates the
sidecar: a mismatch or invalid sidecar excludes that input and reports why;
missing sidecars remain unknown and can still participate. Checkpoints
(`.partial.json`) and REST completion summaries (`.outcome.json`) are separate
files and never establish network identity.

See [Codebase Overview](codebase_overview.md) and [Webpage, Web Server, and Data Flow](codebase_webpage_web_server_data_flow.md).