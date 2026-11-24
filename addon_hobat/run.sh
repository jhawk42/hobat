#!/usr/bin/with-contenv bashio
set -Eeuo pipefail

# Define application variables
APP_DIR="${APP_DIR:-/app}"
SCRIPT_NAME="${SCRIPT_NAME:-td_webserver.py}"
HOST="${HOST:-0.0.0.0}"
export OT_REST_LISTEN_ADDR="$(bashio::config 'ot_rest_listen_addr')"
export OT_REST_LISTEN_PORT="$(bashio::config 'ot_rest_listen_port')"
export TD_HA_MATTER_WS_HOST="$(bashio::config 'ha_matter_ws_host')"
export TD_HA_MATTER_WS_PORT="$(bashio::config 'ha_matter_ws_port')"
export TD_THREAD_WATCH_HOST="$(bashio::config 'thread_watch_host')"
export TD_THREAD_WATCH_PORT="$(bashio::config 'thread_watch_port')"
export TD_DEVICE_ACTIONS_ENABLED="$(bashio::config 'device_actions_enabled')"
export TD_DEVICE_RESET_ENABLED="$(bashio::config 'device_reset_enabled')"
export TD_SCHEDULER_ENABLED="$(bashio::config 'scheduler_enabled')"
if bashio::config.has_value 'scheduler_start_time'; then
    export TD_SCHEDULER_START_TIME="$(bashio::config 'scheduler_start_time')"
fi
if bashio::config.has_value 'scheduler_keep_days'; then
    export TD_SCHEDULER_KEEP_DAYS="$(bashio::config 'scheduler_keep_days')"
fi
if bashio::config.has_value 'ext_pan_id'; then
    export TD_EXT_PAN_ID="$(bashio::config 'ext_pan_id')"
fi
if bashio::config.has_value 'TD_DEBUG_LEVEL'; then
    export TD_DEBUG_LEVEL="$(bashio::config 'TD_DEBUG_LEVEL')"
fi

# Navigate to the application directory
cd "$APP_DIR"

# Verify the Python script exists before running
if [ ! -f "$SCRIPT_NAME" ]; then
    echo "Error: $SCRIPT_NAME not found in $(pwd)" >&2
    exit 1
fi

# Execute Python and replace PID 1 to handle OS signals correctly
exec python3 "$SCRIPT_NAME" --host "$HOST" "$@"
