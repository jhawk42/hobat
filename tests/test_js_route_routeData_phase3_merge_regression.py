from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MERGE_JS = REPO_ROOT / "src" / "js" / "tdash-merge.js"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_deep_merge_supports_routeData_array_merge() -> None:
    text = _read_text(MERGE_JS)

    # Phase 3: deepMergeObjects must merge canonical route.routeData arrays.
    assert "if ((key === \"route_data\" || key === \"routeData\") && Array.isArray(sv)) {" in text
    assert "target[key] = mergeRouteData(ownerRloc16, Array.isArray(tv) ? tv : [], sv, ctx);" in text


def test_deep_merge_reconciles_route_sequence_by_rfc1982() -> None:
    text = _read_text(MERGE_JS)

    # Sequence conflict resolution for route containers should use RFC1982 comparator.
    assert "const isRouteContainerPath = pathPrefix === \"route\" || pathPrefix === \"route_data\";" in text
    assert "if (isRouteContainerPath && (key === \"id_sequence\" || key === \"idSequence\")) {" in text
    assert "if (isSequenceNewer(incomingSeq, existingSeq)) {" in text

    # Keep both sequence aliases aligned when both are present.
    assert "target.id_sequence = resolvedSeq;" in text
    assert "target.idSequence = resolvedSeq;" in text
