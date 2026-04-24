"""Shared constants for Thread dash scripts."""

EXTADDR_DEVICE_LABEL_MAP_FILENAME = "td-static-extaddr-device-label.json"

TD_DATA_DIR_ENV_VAR = "TD_DATA_DIR"
TD_DATA_DIR_ARG = "--datadir"
TD_DATA_DIR_DOCKER_DEFAULT = "/data"
TD_DATA_DIR_LOCAL_DEFAULT = "data"

TD_DATA_DIR_RESOLUTION_SUMMARY = (
	"Data directory resolution precedence: "
	"1) TD_DATA_DIR environment variable, "
	"2) --datadir CLI argument, "
	"3) defaults (/data when present, otherwise ./data under the current run directory)."
)

TD_DATA_DIR_ARG_HELP = (
	"Data directory for JSON reads/writes when TD_DATA_DIR is not set. "
	"If omitted and TD_DATA_DIR is unset: use /data when present; otherwise create/use ./data "
	"under the current run directory."
)
