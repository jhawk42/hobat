"""Home Assistant Matter collection orchestration without persistence side effects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ha_matter_ws_client import DEFAULT_MATTER_WS_URI, NodeSnapshot, fetch_node_snapshot
from ha_matter_ws_extractor import dedupe_nodes, extract_node_info
from ha_matter_ws_snapshots import build_device_snapshot, build_diagnostic_snapshot
from ha_matter_ws_topology import (
    build_mesh_diagnostic_snapshot,
    build_topology_snapshot,
)
from util_data import save_json_atomic


@dataclass(frozen=True)
class MatterCollection:
    uri: str
    message_count: int
    node_count: int
    server_info: dict[str, Any]
    devices: tuple[dict[str, Any], ...]
    diagnostics: tuple[dict[str, Any], ...]
    mesh_diagnostics: tuple[dict[str, Any], ...]
    topology: tuple[dict[str, Any], ...]


CollectionProgressCallback = Callable[[int, int, MatterCollection], None]


def _build_collection(
    snapshot: NodeSnapshot,
    records: list[dict[str, Any]],
    *,
    node_count: int,
) -> MatterCollection:
    devices = build_device_snapshot(records)
    diagnostics = build_diagnostic_snapshot(records)
    mesh_diagnostics = build_mesh_diagnostic_snapshot(diagnostics)
    topology = build_topology_snapshot(diagnostics)
    return MatterCollection(
        uri=snapshot.uri,
        message_count=len(snapshot.frames),
        node_count=node_count,
        server_info=dict(snapshot.server_info),
        devices=tuple(devices),
        diagnostics=tuple(diagnostics),
        mesh_diagnostics=tuple(mesh_diagnostics),
        topology=tuple(topology),
    )


async def collect_devices(
    uri: str = DEFAULT_MATTER_WS_URI,
    *,
    connect_timeout: float = 10.0,
    request_timeout: float = 5.0,
    settle_timeout: float = 0.25,
    max_frames: int = 500,
    progress_callback: CollectionProgressCallback | None = None,
) -> MatterCollection:
    """Collect and normalize devices; command-owned persistence arrives in Phase 5."""

    snapshot = await fetch_node_snapshot(
        uri,
        connect_timeout=connect_timeout,
        request_timeout=request_timeout,
        settle_timeout=settle_timeout,
        max_frames=max_frames,
    )
    nodes = dedupe_nodes(list(snapshot.nodes))
    records: list[dict[str, Any]] = []
    total = len(nodes)
    for completed, node in enumerate(nodes, start=1):
        records.append(extract_node_info(node, server_info=snapshot.server_info))
        if progress_callback is not None:
            progress_callback(
                completed,
                total,
                _build_collection(snapshot, records, node_count=total),
            )
    return _build_collection(snapshot, records, node_count=total)


def save_collection(
    collection: MatterCollection,
    *,
    device_output: Path,
    server_info_output: Path,
) -> None:
    """Atomically save outputs after collection and normalization have succeeded."""

    save_json_atomic(
        list(collection.devices), device_output, add_trailing_newline=True
    )
    save_json_atomic(
        collection.server_info, server_info_output, add_trailing_newline=True
    )