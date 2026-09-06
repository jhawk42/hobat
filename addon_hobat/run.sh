#!/usr/bin/with-contenv bashio
set -Eeuo pipefail

# Define application variables
APP_DIR="${APP_DIR:-/app}"
SCRIPT_NAME="${SCRIPT_NAME:-td_webserver.py}"
HOST="${HOST:-0.0.0.0}"

# Navigate to the application directory
cd "$APP_DIR"

# Verify the Python script exists before running
if [ ! -f "$SCRIPT_NAME" ]; then
    echo "Error: $SCRIPT_NAME not found in $(pwd)" >&2
    exit 1
fi

# Execute Python and replace PID 1 to handle OS signals correctly
exec python3 "$SCRIPT_NAME" --host "$HOST" "$@"
