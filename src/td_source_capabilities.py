"""Cache-first source capability inspection for the dashboard."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

from ha_matter_ws_client import HaMatterWsClient
from ha_matter_ws_contract import resolve_default_ha_matter_ws_uri
from otbr_restapi_util import OTBRRestApiClient
from td_const import (
    EXTADDR_DEVICE_LABEL_MAP_FILENAME,
    EVE_TOPOLOGY_FILENAME,
    HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME,
    HA_MATTER_WS_DASHBOARD_FILENAME,
    HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME,
    HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_SERVER_INFO_FILENAME,
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


PROBE_TIMEOUT_SECONDS = 2.0
PROBE_TTL_SECONDS = 60.0
ALWAYS_AVAILABLE_SOURCES = frozenset({"mdns", "system"})

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
    ),
    "eve": ("Eve Thread Network Layout.evethreadlayout", EVE_TOPOLOGY_FILENAME),
    "thread-tools": (THREAD_TOOLS_DIAGNOSTICS_FILENAME,),
    "mdns": (
        MDNS_SCOPES_THREAD_FILENAME,
        MDNS_SCOPES_BR_FILENAME,
        MDNS_SCOPES_HAP_FILENAME,
        MDNS_SCOPES_MATTER_FILENAME,
    ),
    "merged": (MERGED_TOPOLOGY_ALL_FILENAME,),
    "system": (EXTADDR_DEVICE_LABEL_MAP_FILENAME,),
}

FILE_SOURCES = {
    filename: source for source, filenames in SOURCE_FILES.items() for filename in filenames
}
Probe = Callable[[], Awaitable[str | None]]


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
                stderr=subprocess.DEVNULL,
                timeout=PROBE_TIMEOUT_SECONDS,
            ),
            timeout=PROBE_TIMEOUT_SECONDS + 0.25,
        )
    except (OSError, subprocess.TimeoutExpired, asyncio.TimeoutError):
        return "unreachable"
    if completed.returncode != 0:
        return "command-failed"
    return None if completed.stdout.strip() else "invalid-response"


async def _probe_otbr_restapi() -> str | None:
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                OTBRRestApiClient(timeout=2, retries=0).get_node_state
            ),
            timeout=PROBE_TIMEOUT_SECONDS + 0.25,
        )
    except (Exception, asyncio.TimeoutError):
        return "unreachable"
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
    except Exception:
        return "unreachable"
    return None


DEFAULT_PROBES: dict[str, Probe] = {
    "otbr-cli": _probe_otbr_cli,
    "otbr-restapi": _probe_otbr_restapi,
    "ha-matter-ws": _probe_ha_matter_ws,
}


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

    async def capabilities(self, data_dir: Path) -> dict[str, object]:
        files = {
            filename: {"cached": (data_dir / filename).is_file(), "source": source}
            for filename, source in FILE_SOURCES.items()
        }
        sources: dict[str, object] = {}
        for source, filenames in SOURCE_FILES.items():
            cached = any(files[filename]["cached"] for filename in filenames)
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