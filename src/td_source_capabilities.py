"""Cache-first dashboard capabilities and explicit live collection preflights."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, Literal, TypedDict
from urllib.parse import urlsplit

from ha_matter_ws_client import HaMatterWsClient, MatterWsTransportError
from ha_matter_ws_contract import MatterWsContractError, resolve_default_ha_matter_ws_uri
from otbr_restapi_util import (
    OTBRConnectionError,
    OTBRHTTPError,
    OTBRInvalidResponseError,
    OTBRRestApiClient,
    OTBRUsageError,
    resolve_default_rest_host,
    resolve_default_rest_port,
)
from td_const import (
    EXTADDR_DEVICE_LABEL_MAP_FILENAME,
    EVE_TOPOLOGY_FILENAME,
    HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME,
    HA_MATTER_WS_DASHBOARD_FILENAME,
    HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME,
    HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_NETWORK_TOPOLOGY_FILENAME,
    HA_MATTER_WS_SERVER_INFO_FILENAME,
    HA_MATTER_WS_THREAD_BORDER_ROUTERS_FILENAME,
    HA_MATTER_WS_TOPOLOGY_FILENAME,
    MDNS_SCOPES_BR_FILENAME,
    MDNS_SCOPES_HAP_FILENAME,
    MDNS_SCOPES_MATTER_FILENAME,
    MDNS_SCOPES_THREAD_FILENAME,
    MERGED_TOPOLOGY_ALL_FILENAME,
    OTBR_CLI_MESHDIAG_ROUTER_CHILDIP6_FILENAME,
    OTBR_CLI_MESHDIAG_ROUTER_CHILDTABLES_FILENAME,
    OTBR_CLI_MESHDIAG_ROUTER_NEIGHBORTABLES_FILENAME,
    OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME,
    OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
    OTBR_CLI_NETWORKDIAG_MULTICAST_NEIGHBORS_FILENAME,
    OTBR_CLI_NETWORKDIAG_MULTICAST_NETWORK_FILENAME,
    OTBR_CLI_ROUTER_TABLE_FILENAME,
    OTBR_CLI_THREAD_NETWORK_INFO_FILENAME,
    OTBR_RESTAPI_ACTIONS_LIST_FILENAME,
    OTBR_RESTAPI_DATASET_ACTIVE_FILENAME,
    OTBR_RESTAPI_DEVICES_FETCH_FILENAME,
    OTBR_RESTAPI_DEVICES_FILENAME,
    OTBR_RESTAPI_DEVICES_LIST_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_LIST_FILENAME,
    OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    THREAD_TOOLS_DIAGNOSTICS_FILENAME,
)
from util_ot_ctl import (
    TD_OTBR_CONTAINER_NAME_DEFAULT,
    TD_OTBR_CONTAINER_NAME_ENV,
    TD_OTBR_CONTAINER_USE_DEFAULT,
    TD_OTBR_CONTAINER_USE_ENV,
)
from util_data import network_scope_path, read_network_scope
from td_dataset_catalog import load_dataset_catalog
from td_unified_dataset import UnifiedDatasetError, inspect_unified_cache


PROBE_TIMEOUT_SECONDS = 2.0
PROBE_TTL_SECONDS = 60.0
ALWAYS_AVAILABLE_SOURCES = frozenset({"mdns", "system"})
OTBR_CLI_STATES = frozenset({"child", "router", "leader", "detached", "disabled"})

SOURCE_FILES = {
    "otbr-cli": (
        OTBR_CLI_THREAD_NETWORK_INFO_FILENAME,
        OTBR_CLI_ROUTER_TABLE_FILENAME,
        OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME,
        OTBR_CLI_MESHDIAG_ROUTER_CHILDIP6_FILENAME,
        OTBR_CLI_MESHDIAG_ROUTER_CHILDTABLES_FILENAME,
        OTBR_CLI_MESHDIAG_ROUTER_NEIGHBORTABLES_FILENAME,
        OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
        OTBR_CLI_NETWORKDIAG_MULTICAST_NETWORK_FILENAME,
        OTBR_CLI_NETWORKDIAG_MULTICAST_NEIGHBORS_FILENAME,
    ),
    "otbr-restapi": (
        OTBR_RESTAPI_DATASET_ACTIVE_FILENAME,
        OTBR_RESTAPI_DEVICES_FILENAME,
        OTBR_RESTAPI_DEVICES_LIST_FILENAME,
        OTBR_RESTAPI_DEVICES_FETCH_FILENAME,
        OTBR_RESTAPI_DIAGNOSTICS_FILENAME,
        OTBR_RESTAPI_DIAGNOSTICS_LIST_FILENAME,
        OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
        OTBR_RESTAPI_ACTIONS_LIST_FILENAME,
        OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    ),
    "ha-matter-ws": (
        HA_MATTER_WS_SERVER_INFO_FILENAME,
        HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME,
        HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME,
        HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
        HA_MATTER_WS_TOPOLOGY_FILENAME,
        HA_MATTER_WS_DASHBOARD_FILENAME,
        HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME,
        HA_MATTER_WS_THREAD_BORDER_ROUTERS_FILENAME,
        HA_MATTER_WS_NETWORK_TOPOLOGY_FILENAME,
    ),
    "eve": ("Eve Thread Network Layout.evethreadlayout", EVE_TOPOLOGY_FILENAME),
    "thread-tools": (THREAD_TOOLS_DIAGNOSTICS_FILENAME,),
    "mdns": (
        MDNS_SCOPES_THREAD_FILENAME,
        MDNS_SCOPES_BR_FILENAME,
        MDNS_SCOPES_HAP_FILENAME,
        MDNS_SCOPES_MATTER_FILENAME,
    ),
    "multi-source": (MERGED_TOPOLOGY_ALL_FILENAME,),
    "system": (EXTADDR_DEVICE_LABEL_MAP_FILENAME,),
}

FILE_SOURCES = {
    filename: source for source, filenames in SOURCE_FILES.items() for filename in filenames
}
Probe = Callable[[], Awaitable[str | None]]
FileSignature = tuple[tuple[str, tuple[int, ...] | None], ...]


def _file_signature(data_dir: Path, filenames: set[str]) -> FileSignature:
    signature = []
    for filename in sorted(filenames):
        try:
            stat = (data_dir / filename).stat()
        except FileNotFoundError:
            signature.append((filename, None))
        else:
            signature.append((filename, (
                stat.st_dev, stat.st_ino, stat.st_mode, stat.st_size,
                stat.st_mtime_ns, stat.st_ctime_ns,
            )))
    return tuple(signature)


async def _probe_otbr_cli() -> str | None:
    container_use = os.environ.get(TD_OTBR_CONTAINER_USE_ENV)
    use_container = (
        TD_OTBR_CONTAINER_USE_DEFAULT
        if container_use is None
        else int(container_use)
    )
    if use_container:
        container = os.environ.get(TD_OTBR_CONTAINER_NAME_ENV, TD_OTBR_CONTAINER_NAME_DEFAULT)
        command = ["docker", "exec", "-i", container, "ot-ctl", "state"]
    else:
        executable = shutil.which("ot-ctl")
        if executable is None:
            return "executable-unavailable"
        command = [executable, "state"]
    try:
        completed = await asyncio.wait_for(
            asyncio.to_thread(
                subprocess.run,
                command,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=PROBE_TIMEOUT_SECONDS,
            ),
            timeout=PROBE_TIMEOUT_SECONDS + 0.25,
        )
    except (OSError, subprocess.TimeoutExpired, asyncio.TimeoutError):
        return "unreachable"
    if completed.returncode != 0:
        stderr = completed.stderr.decode(errors="replace").lower()
        if use_container and ("docker api" in stderr or "docker.sock" in stderr):
            return "docker-unavailable"
        return "command-failed"
    state = completed.stdout.decode(errors="replace").strip().lower()
    return None if state in OTBR_CLI_STATES else "invalid-response"


async def _probe_otbr_restapi() -> str | None:
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                OTBRRestApiClient(timeout=2, retries=0).get_node_state
            ),
            timeout=PROBE_TIMEOUT_SECONDS + 0.25,
        )
    except (OTBRConnectionError, OTBRHTTPError, OSError, asyncio.TimeoutError):
        return "unreachable"
    except OTBRInvalidResponseError:
        return "invalid-response"
    return None


async def _probe_ha_matter_ws() -> str | None:
    try:
        async with HaMatterWsClient(
            resolve_default_ha_matter_ws_uri(),
            connect_timeout=PROBE_TIMEOUT_SECONDS,
            request_timeout=PROBE_TIMEOUT_SECONDS,
            max_frame_size=16 * 1024,
            max_frames=2,
        ):
            pass
    except (MatterWsTransportError, OSError, asyncio.TimeoutError):
        return "unreachable"
    except MatterWsContractError:
        return "invalid-response"
    return None


DEFAULT_PROBES: dict[str, Probe] = {
    "otbr-cli": _probe_otbr_cli,
    "otbr-restapi": _probe_otbr_restapi,
    "ha-matter-ws": _probe_ha_matter_ws,
}


class LiveProbeResult(TypedDict):
    source: str
    state: Literal["live", "probe-failed", "probe-error"]
    probe: dict[str, str]


class ProbeConfigurationError(ValueError):
    """Invalid preflight configuration with a safe operator-facing message."""


def _validate_probe_configuration(source: str) -> None:
    if source == "otbr-cli":
        container_use = os.environ.get(TD_OTBR_CONTAINER_USE_ENV)
        if container_use is not None and container_use not in {"0", "1"}:
            raise ProbeConfigurationError(f"{TD_OTBR_CONTAINER_USE_ENV} must be 0 or 1")
        if (container_use is None and TD_OTBR_CONTAINER_USE_DEFAULT) or container_use == "1":
            container = os.environ.get(TD_OTBR_CONTAINER_NAME_ENV, TD_OTBR_CONTAINER_NAME_DEFAULT)
            if not container.strip():
                raise ProbeConfigurationError(f"{TD_OTBR_CONTAINER_NAME_ENV} must not be blank")
    port_variable = {
        "otbr-restapi": "OT_REST_LISTEN_PORT",
        "ha-matter-ws": "TD_HA_MATTER_WS_PORT",
    }.get(source)
    if port_variable is not None:
        port = os.environ.get(port_variable, "").strip()
        if port and (
            len(port) > 5 or not port.isascii() or not port.isdecimal()
            or not 1 <= int(port) <= 65535
        ):
            raise ProbeConfigurationError(f"{port_variable} must be an integer between 1 and 65535")
    if source == "otbr-cli":
        return
    endpoint = (
        f"http://{resolve_default_rest_host()}:{resolve_default_rest_port()}"
        if source == "otbr-restapi" else resolve_default_ha_matter_ws_uri()
    )
    try:
        parsed = urlsplit(endpoint)
        valid = (
            parsed.hostname is not None
            and not any(character.isspace() for character in parsed.hostname)
            and parsed.port is not None
            and parsed.username is None and parsed.password is None
            and parsed.path == ("" if source == "otbr-restapi" else "/ws")
            and not parsed.query and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise ProbeConfigurationError(f"Invalid host/port configuration for {source}")


async def probe_source(source: str) -> LiveProbeResult:
    """Run a fresh bounded probe without consulting files, TTLs, or inflight results."""
    if source not in DEFAULT_PROBES:
        raise ValueError("Source does not support a live probe")
    _validate_probe_configuration(source)
    try:
        reason = await asyncio.wait_for(
            DEFAULT_PROBES[source](), timeout=2 * PROBE_TIMEOUT_SECONDS + 0.5
        )
    except asyncio.TimeoutError:
        reason = "unreachable"
    if reason is not None and (not isinstance(reason, str) or not reason):
        raise TypeError("Source probe must return None or a nonempty failure reason")
    if reason is None:
        return {"source": source, "state": "live", "probe": {"state": "success"}}
    return {
        "source": source,
        "state": "probe-failed",
        "probe": {"state": "failed", "reason": reason},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe live source readiness without reading or writing caches.")
    parser.add_argument("--source", required=True, choices=tuple(DEFAULT_PROBES))
    parser.add_argument("--json", action="store_true", help="Write one JSON result to stdout")
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(probe_source(args.source))
    except ProbeConfigurationError as exc:
        logging.error("Invalid source-probe configuration for %s: %s.", args.source, exc)
        result = {
            "source": args.source, "state": "probe-error",
            "probe": {"state": "error", "reason": "invalid-configuration"},
        }
    except (ValueError, RuntimeError, TypeError, OSError, OTBRUsageError) as exc:
        logging.error("Source probe execution failed for %s (%s).", args.source, type(exc).__name__)
        result = {
            "source": args.source, "state": "probe-error",
            "probe": {"state": "error", "reason": "probe-execution-error"},
        }
    status = {"live": 0, "probe-failed": 1, "probe-error": 2}[result["state"]]
    if args.json:
        print(json.dumps(result))
    else:
        reason = result["probe"].get("reason", "success")
        print(f"{result['source']}: {result['state']}; {reason}")
    if status == 1:
        logging.warning("Source unavailable: %s (%s).", args.source, result["probe"]["reason"])
    return status


class SourceCapabilityService:
    """Inspect cached source evidence and deduplicate bounded live probes."""

    def __init__(
        self,
        *,
        probes: dict[str, Probe] | None = None,
        probe_ttl_seconds: float = PROBE_TTL_SECONDS,
    ) -> None:
        self._probes = dict(DEFAULT_PROBES if probes is None else probes)
        self._probe_ttl_seconds = probe_ttl_seconds
        self._probe_cache: dict[str, tuple[float, str | None]] = {}
        self._inflight: dict[str, asyncio.Task[str | None]] = {}
        self._inspection_inflight: dict[Path, asyncio.Task[dict]] = {}
        self._inspection_cache: dict[Path, tuple[dict, FileSignature, dict]] = {}

    def _inspect_files(self, data_dir: Path) -> dict:
        catalog = load_dataset_catalog()
        file_sources = dict(FILE_SOURCES)
        filenames = set(file_sources)
        for entry in catalog["datasets"]:
            if "unified" in entry:
                file_sources[entry["files"][0]] = entry["source"]
                recipe = entry["unified"]
                filenames.update(entry["files"])
                filenames.update(item["file"] for item in recipe["inputs"])
                filenames.update(recipe[key] for key in ("reportFile", "identityFile", "outcomeFile")
                                 if recipe[key] is not None)
        filenames.update(network_scope_path(name).name for name in tuple(filenames))
        for _ in range(3):
            before = _file_signature(data_dir, filenames)
            cached = self._inspection_cache.get(data_dir)
            if cached is not None and cached[0] == catalog and cached[1] == before:
                return cached[2]
            files = self._read_files(data_dir, catalog, file_sources)
            if catalog != load_dataset_catalog():
                raise UnifiedDatasetError("Capability catalog changed during inspection; retry the request")
            if before == _file_signature(data_dir, filenames):
                self._inspection_cache[data_dir] = (catalog, before, files)
                return files
        raise UnifiedDatasetError("Cached capability inputs changed during inspection; retry the request")

    @staticmethod
    def _read_files(data_dir: Path, catalog: dict, file_sources: dict[str, str]) -> dict:
        files = {
            filename: {"cached": (data_dir / filename).is_file(), "source": source}
            for filename, source in file_sources.items()
        }
        for filename, file_info in files.items():
            if file_info["cached"]:
                scope, _ = read_network_scope(data_dir / filename)
                if scope is not None:
                    file_info["networkInstance"] = scope
        inspections: dict[str, dict] = {}
        for entry in catalog["datasets"]:
            if "unified" in entry:
                files[entry["files"][0]].update(inspect_unified_cache(
                    data_dir, entry, catalog=catalog, inspections=inspections))
        return files

    async def capabilities(self, data_dir: Path) -> dict[str, object]:
        data_dir = data_dir.resolve()
        task = self._inspection_inflight.get(data_dir)
        if task is None:
            task = asyncio.create_task(asyncio.to_thread(self._inspect_files, data_dir))
            self._inspection_inflight[data_dir] = task
            task.add_done_callback(lambda completed: self._inspection_inflight.pop(data_dir, None))
        files = deepcopy(await asyncio.shield(task))
        sources: dict[str, object] = {}
        for source, filenames in SOURCE_FILES.items():
            cached = any(files[filename]["cached"] for filename in filenames)
            cached = cached or any(info["source"] == source and info["cached"] for info in files.values())
            if source in ALWAYS_AVAILABLE_SOURCES:
                sources[source] = self._source_result(source, "available", cached, "not-applicable")
                continue
            if cached:
                sources[source] = self._source_result(source, "cached", True, "not-run")
                continue
            probe = self._probes.get(source)
            if probe is None:
                sources[source] = self._source_result(source, "unavailable", False, "not-applicable")
                continue
            error = await self._run_probe(source, probe)
            state = "live" if error is None else "probe-failed"
            sources[source] = self._source_result(source, state, False, "success" if error is None else "failed", error)
        return {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sources": sources,
            "files": files,
        }

    def _source_result(
        self, source: str, state: str, cached: bool, probe_state: str, reason: str | None = None
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "state": state,
            "cached": cached,
            "configured": source in self._probes,
            "probe": {"state": probe_state},
        }
        if reason is not None:
            result["probe"]["reason"] = reason
        return result

    async def _run_probe(self, source: str, probe: Probe) -> str | None:
        now = asyncio.get_running_loop().time()
        cached = self._probe_cache.get(source)
        if cached is not None and cached[0] > now:
            return cached[1]
        task = self._inflight.get(source)
        if task is None:
            task = asyncio.create_task(probe())
            self._inflight[source] = task
        try:
            result = await task
        finally:
            if task.done():
                self._inflight.pop(source, None)
        self._probe_cache[source] = (now + self._probe_ttl_seconds, result)
        return result


if __name__ == "__main__":
    raise SystemExit(main())