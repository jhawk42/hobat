from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONSTANTS_JS = REPO_ROOT / "src" / "js" / "tdash-constants.js"
FILTERS_JS = REPO_ROOT / "src" / "js" / "tdash-filters.js"
TOPOLOGY_RENDERER_JS = REPO_ROOT / "src" / "js" / "tdash-topology-renderer.js"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_routes_subfilters_have_their_approved_category_membership() -> None:
    constants = _read_text(CONSTANTS_JS)
    filters = _read_text(FILTERS_JS)

    assert 'export const LINK_FILTER_ROUTES_ROUTERS = "otbr_routes_routers";' in constants
    assert 'export const LINK_FILTER_ROUTES_FTD_CHILD = "otbr_routes_ftd_child";' in constants
    assert 'export const EDGE_CATEGORY_OTBR_ROUTE_ROUTER = "otbr_route_router";' in constants
    assert 'export const EDGE_CATEGORY_OTBR_ROUTE_FTD_CHILD = "otbr_route_ftd_child";' in constants
    assert 'label: "Routes: Routers"' in constants
    assert 'label: "Routes: REEDs"' in constants
    assert "if (mode === LINK_FILTER_ROUTES_ROUTERS)" in filters
    assert "if (mode === LINK_FILTER_ROUTES_FTD_CHILD)" in filters


def test_mesh_ring_preserves_ftd_child_route_edge_styling() -> None:
    renderer = _read_text(TOPOLOGY_RENDERER_JS)

    assert "EDGE_CATEGORY_OTBR_ROUTE_FTD_CHILD" in renderer
    assert (
        "!categories.includes(EDGE_CATEGORY_OTBR_ROUTE_FTD_CHILD)"
        in renderer
    )
