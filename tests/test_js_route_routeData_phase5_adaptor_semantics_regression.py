from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTORS_JS = REPO_ROOT / "src" / "js" / "tdash-adaptors.js"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_meshdiag_networkdiag_route_edges_keep_lq_style_semantics() -> None:
    text = _read_text(ADAPTORS_JS)

    assert "const lqIn = toFiniteNumber(route.linkQualityIn) || 0;" in text
    assert "const lqOut = toFiniteNumber(route.linkQualityOut) || 0;" in text
    assert "const avgLqi = Math.max(lqIn, lqOut);" in text
    assert "const lqStyle = lqStyleFromAvgLqi(avgLqi, 3);" in text


def test_route_edges_keep_otbr_route_category_across_adaptors() -> None:
    text = _read_text(ADAPTORS_JS)

    # Phase 5 guard: route edges continue to advertise OTBR route category.
    assert text.count("linkCategories: [EDGE_CATEGORY_OTBR_ROUTE]") >= 3

    # Ensure canonical route container traversal remains in all route edge paths.
    assert text.count("(Array.isArray(node.route?.routeData) ? node.route.routeData : []).forEach((route) => {") >= 3
