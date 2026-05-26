| module name | environment variable name | default value | description of what the env var does |
| --- | --- | --- | --- |
| `mdns_thread_scopes.py` | `TD_MDNS_BROWSE_TIMEOUT` | `5` | Sets the default idle browse timeout (seconds) used by the mDNS scope browser when `--browse-timeout` is not provided. |
| `util_data.py` | `TD_DATA_DIR` | Unset by default; falls back to `--datadir`, then `/data` (if present), else `./data` | Sets the data directory path used for reading/writing tdash JSON data files. |
| `util_ot_ctl.py` | `TD_OT_CTL_TIMEOUT` | `30` | Sets the timeout (seconds) for `ot-ctl` subprocess execution. |
| `util_ot_ctl.py` | `TD_OTBR_CONTAINER_NAME` | `otbr` | Overrides the OTBR Docker container name used when running `ot-ctl` via `docker exec`. |
| `util_ot_ctl.py` | `TD_OTBR_CONTAINER_USE` | `1` | Controls whether to use Docker container execution for `ot-ctl` (`1` = use container, `0` = run locally without `docker exec`). |
| `td_webserver.py` | `HOST` | `""` (bind all interfaces) | Sets the default host/interface that the web server binds to when `--host` is not passed. |
| `td_webserver.py` | `PORT` | `9165` | Sets the default web server port when `--port` is not passed. |
