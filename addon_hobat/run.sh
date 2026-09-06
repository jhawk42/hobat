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

# Navigate to the application directory
cd "$APP_DIR"

# Verify the Python script exists before running
if [ ! -f "$SCRIPT_NAME" ]; then
    echo "Error: $SCRIPT_NAME not found in $(pwd)" >&2
    exit 1
fi

# Execute Python and replace PID 1 to handle OS signals correctly
exec python3 "$SCRIPT_NAME" --host "$HOST" "$@"
