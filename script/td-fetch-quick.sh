#!/usr/bin/env bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || exit 1
exec bash "$SCRIPT_DIR/td-fetch.sh" --quick "$@"
