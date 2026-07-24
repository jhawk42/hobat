from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTORS_JS = REPO_ROOT / "src" / "js" / "tdash-adaptors.js"
CONSTANTS_JS = REPO_ROOT / "src" / "js" / "tdash-constants.js"
FILTERS_JS = REPO_ROOT / "src" / "js" / "tdash-filters.js"
TOPOLOGY_RENDERER_JS = REPO_ROOT / "src" / "js" / "tdash-topology-renderer.js"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_meshdiag_networkdiag_route_edges_keep_lq_style_semantics() -> None:
    text = _read_text(ADAPTORS_JS)

    assert "const lqIn = toFiniteNumber(route.linkQualityIn) || 0;" in text
    assert "const lqOut = toFiniteNumber(route.linkQualityOut) || 0;" in text
    assert "const avgLqi = Math.max(lqIn, lqOut);" in text
    assert "const lqStyle = lqStyleFromAvgLqi(avgLqi, 3);" in text


def test_route_edges_classify_otbr_route_sources_across_scoped_adaptors() -> None:
    text = _read_text(ADAPTORS_JS)

    assert "function getOtbrRouteCategory(sourceNode)" in text
    assert "role === 'border router'" in text
    assert "role === 'router'" in text
    assert "modeDevice === 'FTD' ? EDGE_CATEGORY_OTBR_ROUTE_FTD_CHILD" in text
    assert "return category ? [EDGE_CATEGORY_OTBR_ROUTE, category] : [];" in text

    # Scoped adaptor paths retain canonical route traversal and use source categories.
    assert text.count("(Array.isArray(node.route?.routeData) ? node.route.routeData : []).forEach((route) => {") >= 3
    assert text.count("linkCategories: routeCategories") >= 3


def test_rest_api_route_data_uses_source_categories() -> None:
    text = _read_text(ADAPTORS_JS)
    rest_api_adaptor = text.split("export function adaptOtbrRestApi(fileMap) {")[1]

    assert "const routeCategories = getOtbrRouteCategories(node);" in rest_api_adaptor
    assert "if (routeCategories.length === 0) return;" in rest_api_adaptor
    assert "linkCategories: routeCategories" in rest_api_adaptor


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
