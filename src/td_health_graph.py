"""Deterministic undirected graph analysis for Thread topology evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class GraphEdge:
    relationship_id: str
    from_device_id: str
    to_device_id: str


@dataclass(frozen=True)
class GraphAnalysis:
    nodes: tuple[str, ...]
    edge_count: int
    bridge_relationship_ids: tuple[str, ...]
    bridge_components: dict[str, tuple[tuple[str, ...], ...]]
    articulation_device_ids: tuple[str, ...]
    articulation_components: dict[str, tuple[tuple[str, ...], ...]]


def _components(
    nodes: tuple[str, ...],
    adjacency: dict[str, set[str]],
    *,
    excluded_node: str | None = None,
    excluded_edge: tuple[str, str] | None = None,
) -> tuple[tuple[str, ...], ...]:
    remaining = [node for node in nodes if node != excluded_node]
    unseen = set(remaining)
    components: list[tuple[str, ...]] = []
    while unseen:
        start = min(unseen)
        stack = [start]
        component: set[str] = set()
        while stack:
            node = stack.pop()
            if node not in unseen:
                continue
            unseen.remove(node)
            component.add(node)
            for neighbor in sorted(adjacency[node], reverse=True):
                if neighbor == excluded_node:
                    continue
                if excluded_edge and tuple(sorted((node, neighbor))) == excluded_edge:
                    continue
                if neighbor in unseen:
                    stack.append(neighbor)
        components.append(tuple(sorted(component)))
    return tuple(sorted(components))


def analyze_undirected_graph(
    nodes: Iterable[str], edges: Iterable[GraphEdge]
) -> GraphAnalysis:
    ordered_nodes = tuple(sorted(set(nodes)))
    adjacency = {node: set() for node in ordered_nodes}
    relationship_ids_by_pair: dict[tuple[str, str], set[str]] = {}
    for edge in edges:
        if edge.from_device_id == edge.to_device_id:
            continue
        if edge.from_device_id not in adjacency or edge.to_device_id not in adjacency:
            continue
        pair = tuple(sorted((edge.from_device_id, edge.to_device_id)))
        adjacency[pair[0]].add(pair[1])
        adjacency[pair[1]].add(pair[0])
        relationship_ids_by_pair.setdefault(pair, set()).add(edge.relationship_id)

    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parents: dict[str, str | None] = {}
    bridge_pairs: set[tuple[str, str]] = set()
    articulation_ids: set[str] = set()
    next_index = 0

    def visit(node: str) -> None:
        nonlocal next_index
        discovery[node] = next_index
        low[node] = next_index
        next_index += 1
        child_count = 0
        for neighbor in sorted(adjacency[node]):
            if neighbor not in discovery:
                parents[neighbor] = node
                child_count += 1
                visit(neighbor)
                low[node] = min(low[node], low[neighbor])
                if low[neighbor] > discovery[node]:
                    bridge_pairs.add(tuple(sorted((node, neighbor))))
                if parents[node] is None and child_count > 1:
                    articulation_ids.add(node)
                if parents[node] is not None and low[neighbor] >= discovery[node]:
                    articulation_ids.add(node)
            elif neighbor != parents[node]:
                low[node] = min(low[node], discovery[neighbor])

    for node in ordered_nodes:
        if node not in discovery:
            parents[node] = None
            visit(node)

    bridge_components: dict[str, tuple[tuple[str, ...], ...]] = {}
    bridge_relationship_ids: list[str] = []
    for pair in sorted(bridge_pairs):
        components = _components(ordered_nodes, adjacency, excluded_edge=pair)
        for relationship_id in sorted(relationship_ids_by_pair[pair]):
            bridge_relationship_ids.append(relationship_id)
            bridge_components[relationship_id] = components
    articulation_components = {
        device_id: _components(ordered_nodes, adjacency, excluded_node=device_id)
        for device_id in sorted(articulation_ids)
    }
    return GraphAnalysis(
        nodes=ordered_nodes,
        edge_count=len(relationship_ids_by_pair),
        bridge_relationship_ids=tuple(bridge_relationship_ids),
        bridge_components=bridge_components,
        articulation_device_ids=tuple(sorted(articulation_ids)),
        articulation_components=articulation_components,
    )