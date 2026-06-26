from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTORS_JS = REPO_ROOT / "src" / "js" / "tdash-adaptors.js"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_meshdiag_networkdiag_route_edges_use_route_routeData_only() -> None:
    text = _read_text(ADAPTORS_JS)

    # Legacy route_data traversal must be removed from adaptor route edge generation.
    assert "node.route_data?.route_data" not in text
    assert "node.route_data.route_data" not in text

    # Route traversal should use canonical route.routeData shape.
    assert "(Array.isArray(node.route?.routeData) ? node.route.routeData : []).forEach((route) => {" in text


def test_meshdiag_networkdiag_lqi_uses_canonical_route_fields() -> None:
    text = _read_text(ADAPTORS_JS)

    # LQI extraction in networkdiag route edge path should use camelCase fields.
    assert "const lqIn = toFiniteNumber(route.linkQualityIn) || 0;" in text
    assert "const lqOut = toFiniteNumber(route.linkQualityOut) || 0;" in text

    # Old snake_case direct reads should not remain in this adaptor file.
    assert "route.link_quality_in" not in text
    assert "route.link_quality_out" not in text
