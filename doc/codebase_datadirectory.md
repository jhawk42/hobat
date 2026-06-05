# Data Directory Model

All JSON file reads/writes use one effective data directory (`td_data_directory`) resolved in this order:

1. `--datadir DIR` command line argument
2. `TD_DATA_DIR` environment variable
3. Defaults
   - If `/data` exists, use `/data`
   - Otherwise create and use `./data` under the current run directory

Important behavior:
- `--datadir` takes precedence over `TD_DATA_DIR`.
- User-supplied `TD_DATA_DIR`/`--datadir` paths are resolved to absolute paths.
- Local default `./data` is auto-created when selected.


## Data Directory Usage Examples

```bash
# Highest priority: CLI argument
TD_DATA_DIR=/tmp/td-data python3 -m td_cli --datadir /tmp/cli-data otbr-restapi download

# Environment variable when --datadir is not set
TD_DATA_DIR=/tmp/td-data python3 -m td_cli mdns thread

# CLI argument
python3 -m td_cli --datadir ./data mdns thread

# web-server JSON reads from the effective data directory
python3 -m td_cli --datadir ./data web-server
```

## Data Directory Note

Current behavior uses `td_data_directory` consistently across command families, including web-server JSON responses. This makes docker and non-docker executions deterministic while preserving static dashboard asset serving.