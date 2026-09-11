# Environment Variables

Command-line options take precedence over environment variables. Data-directory
defaults are selected only when neither `--datadir` nor `TD_DATA_DIR` is set.

| module name | environment variable name | default value | description of what the env var does |
| --- | --- | --- | --- |
| `util_data.py` | `TD_DATA_DIR` | Unset by default; used when `--datadir` is not provided, then `/data` (if present), else `./data` | Sets the data directory path used for reading/writing tdash JSON data files, including composite CLI workflows such as `td_cli otbr-cli topology`. |
| `td_webserver.py` | `HOST` | `""` (bind all interfaces) | Sets the default host/interface that the web server binds to when `--host` is not passed. |
| `td_webserver.py` | `PORT` | `9165` | Sets the default web server port when `--port` is not passed. |
| `td_webserver.py` | `TD_FILE_CACHE_MAX_AGE` | `86400` | Sets the default max-age (seconds) used for data file cache headers and freshness checks when `--file-cache-max-age` is not passed. |
| `td_webserver.py` | `TD_DEVICE_ACTIONS_ENABLED` | Disabled | Enables active Device Diagnostics Ping actions when set to a true value. `--enable-device-actions` takes precedence. |
| `td_webserver.py` | `TD_DEVICE_RESET_ENABLED` | Disabled | Enables destructive OTBR Reset Counters actions when set to a true value and device actions are also enabled. `--enable-device-reset` takes precedence. |
| `otbr_restapi_util.py` | `OT_REST_LISTEN_ADDR` | `127.0.0.1` | Sets the default OTBR REST API host used by the OTBR REST CLI/client when `--host` is not provided. Empty values fall back to `127.0.0.1`. |
| `otbr_restapi_util.py` | `OT_REST_LISTEN_PORT` | `8081` | Sets the default OTBR REST API port used by the OTBR REST CLI/client when `--port` is not provided. Invalid or empty values fall back to `8081`. |
| `ha_matter_ws_contract.py` | `TD_HA_MATTER_WS_HOST` | `localhost` | Sets the default Home Assistant Matter WebSocket host when `--host` is not provided. Empty values fall back to `localhost`; `--uri` overrides the complete endpoint. |
| `ha_matter_ws_contract.py` | `TD_HA_MATTER_WS_PORT` | `5580` | Sets the default Home Assistant Matter WebSocket port when `--port` is not provided. Invalid or empty values fall back to `5580`; `--uri` overrides the complete endpoint. |
| `util_ot_ctl.py` | `TD_OTBR_CONTAINER_NAME` | `otbr` | Overrides the OTBR Docker container name used when running `ot-ctl` via `docker exec`, including composite otbr-cli workflows. |
| `util_ot_ctl.py` | `TD_OTBR_CONTAINER_USE` | `1` | Controls whether to use Docker container execution for `ot-ctl` (`1` = use container, `0` = run locally without `docker exec`) across all otbr-cli commands, including `td_cli otbr-cli topology`. |
| `util_ot_ctl.py` | `TD_OT_CTL_TIMEOUT` | `30` | Sets the timeout (seconds) for each `ot-ctl` subprocess execution. A timeout is returned as a command error; `util_ot_ctl.py` does not retry it. |
| `mdns_thread_scopes.py` | `TD_MDNS_BROWSE_TIMEOUT` | `3` | Sets the idle browse timeout (seconds) when `--browse-timeout` is not provided. |

`OT_REST_LISTEN_ADDR` and `OT_REST_LISTEN_PORT` use the same names as OTBR's
container configuration, but here they select the client destination. Use
`--base-url` to override both host and port with a complete URL.
