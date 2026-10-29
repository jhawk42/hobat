#!/usr/bin/env bash

usage() {
    echo "Usage: td-fetch.sh [--quick] [--help|-h]"
}

quick=0
help=0
for arg in "$@"; do
    case "$arg" in
        --quick) quick=1 ;;
        --help|-h) help=1 ;;
        *)
            echo "Unknown argument: $arg" >&2
            usage >&2
            exit 2
            ;;
    esac
done
if (( help )); then
    usage
    exit 0
fi

set -o pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || exit 1
REPO_DIR="$(dirname -- "$SCRIPT_DIR")"
cd -- "$REPO_DIR" || exit 1
if [[ -f "$SCRIPT_DIR/py-activate.sh" ]]; then
    source "$SCRIPT_DIR/py-activate.sh" || exit 1
elif [[ -f "$REPO_DIR/.venv/bin/activate" ]]; then
    source "$REPO_DIR/.venv/bin/activate" || exit 1
fi
export PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
export TD_DATA_DIR="$REPO_DIR/data"
mkdir -p -- "$TD_DATA_DIR" || exit 1
start=$SECONDS
status=0

record_failure() {
    if (( status < 1 )); then status=1; fi
}

collect() {
    python3 -m td_cli "$@"
    local result=$?
    if (( result )); then
        echo "Collection command failed: $* (exit $result)." >&2
        source_failed=1
        record_failure
    fi
    return "$result"
}

preflight() {
    python3 -m td_cli source-probe --source "$1" --json
    local result=$?
    if (( result )); then
        echo "Source $1 unavailable; retaining cached snapshots." >&2
        if (( result == 1 )); then
            echo "Collection: $1=skipped"
            record_failure
        else
            echo "Collection: $1=failed"
            status=2
        fi
    fi
    return "$result"
}

summarize() {
    if (( source_failed )); then
        echo "Collection: $1=failed"
    else
        echo "Collection: $1=collected"
    fi
}

if preflight otbr-cli; then
    source_failed=0
    collect otbr-cli thread-network-info
    collect otbr-cli bbr
    collect otbr-cli router-table
    if (( ! quick )); then
        collect otbr-cli meshdiag routerneighbortable
        collect otbr-cli meshdiag childtable
        collect otbr-cli meshdiag childip6
        collect otbr-cli networkdiag fetch-all
    else
        collect otbr-cli networkdiag fetch-all -cno
    fi
    summarize otbr-cli
fi

if preflight otbr-restapi; then
    source_failed=0
    if collect otbr-restapi --raw node dataset active get && python3 -c '
import json, os, sys
from pathlib import Path
from td_const import OTBR_CLI_THREAD_NETWORK_INFO_FILENAME, OTBR_RESTAPI_DATASET_ACTIVE_FILENAME
from td_network_identity import canonical_ext_pan_id, resolve_network_scope
try:
    directory = Path(os.environ["TD_DATA_DIR"])
    rest = directory / OTBR_RESTAPI_DATASET_ACTIVE_FILENAME
    observed = resolve_network_scope(rest, json.loads(rest.read_text())).ext_pan_id
    configured = os.environ.get("TD_EXT_PAN_ID")
    if configured:
        expected = canonical_ext_pan_id(configured)
    else:
        cli = directory / OTBR_CLI_THREAD_NETWORK_INFO_FILENAME
        expected = resolve_network_scope(cli, json.loads(cli.read_text())).ext_pan_id
    sys.exit(0 if observed and expected and observed == expected else 1)
except (OSError, ValueError):
    sys.exit(1)
'; then
        collect otbr-restapi devices fetch
        if (( ! quick )); then
            collect otbr-restapi diagnostics fetch-all --items-only --no-update-devices --no-basic-fallback
            collect otbr-restapi mesh-diagnostics fetch-all --routers-only --items-only --no-update-devices --preserve-diagnostics --no-fallback
        fi
    else
        echo "REST network identity unavailable or mismatched; skipping REST collection and continuing with HA Matter." >&2
        source_failed=1
        record_failure
    fi
    summarize otbr-restapi
fi

if preflight ha-matter-ws; then
    source_failed=0
    collect ha-matter-ws server-info
    collect ha-matter-ws devices fetch-all
    summarize ha-matter-ws
fi

source_failed=0
collect mdns thread --write-scope-snapshots
summarize mdns
collect process-eve
collect merge-dataset

# Unified materialization uses cached snapshots only.
unified_status=0
network_args=()
datasets=(otbr_cli_unified otbr_restapi_unified ha_matter_ws_unified mdns_unified multi_source_unified)
if [[ -n "${TD_EXT_PAN_ID:-}" ]]; then
    if network=$(python3 -c '
import sys
from td_network_identity import network_id_from_ext_pan_id
try:
    print(network_id_from_ext_pan_id(sys.argv[1]))
except ValueError:
    sys.exit(1)
' "$TD_EXT_PAN_ID"); then
        network_args=(--network "$network")
    else
        echo "Unified build failed: invalid TD_EXT_PAN_ID." >&2
        unified_status=1
        datasets=()
    fi
fi
for dataset in "${datasets[@]}"; do
    if [[ "$dataset" == multi_source_unified ]] && (( unified_status )); then
        break
    fi
    dataset_network=("${network_args[@]}")
    if [[ "$dataset" == mdns_unified ]]; then dataset_network=(); fi
    python3 -m td_cli --datadir "$TD_DATA_DIR" unify-dataset \
        --dataset "$dataset" "${dataset_network[@]}" --allow-partial --json
    result=$?
    if (( result )); then
        echo "Unified build failed: $dataset (exit $result)." >&2
        unified_status=1
    fi
done

# process health
if (( unified_status )); then
    echo "Skipping health processing because Unified materialization failed." >&2
    record_failure
else
    python3 -m td_cli health process-dataset --dataset all --allow-partial
    result=$?
    if (( result )); then
        echo "Health processing failed (exit $result)." >&2
        record_failure
    fi
fi

if (( ! quick )); then
    jq -r '.[] | [.extAddress, .rloc16, .deviceRole, .deviceLabel] | @tsv' \
        "$TD_DATA_DIR/td-merged-topology-all.json" |
        column -t -s $'\t' > "$TD_DATA_DIR/td-jq-devices.txt" || record_failure
    jq -r '.[] | [.extAddress, .omrIpv6Address, .hostname] | @tsv' \
        "$TD_DATA_DIR/td-merged-topology-all.json" |
        column -t -s $'\t' > "$TD_DATA_DIR/td-jq-addresses.txt" || record_failure
fi
echo "Time taken: $(( SECONDS - start )) seconds"
exit "$status"
