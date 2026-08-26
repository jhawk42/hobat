from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
UTILS_JS = REPO_ROOT / "src" / "js" / "tdash-utils.js"
DATASET_JS = REPO_ROOT / "src" / "js" / "tdash-dataset.js"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_utils_exposes_route_container_canonicalization() -> None:
    text = _read_text(UTILS_JS)

    assert "export function normalizeRouteContainer" in text
    assert "canonicalizeRouteContainer" in text
    assert "dropLegacyRouteData" in text

    # Canonical route object should drop nested legacy route_data key.
    assert "delete normalizedRoute.route_data;" in text

    # Legacy route_data arrays must be mapped into canonical routeData.
    assert "_getOwnPropertyValueByAlias(routeSource, \"routeData\") ?? routeSource.route_data" in text

    # Optional top-level cleanup of legacy route_data container.
    assert "delete result.route_data;" in text


def test_normalize_dataset_payload_accepts_and_propagates_options() -> None:
    text = _read_text(UTILS_JS)

    assert "export function normalizeDatasetPayload(value, options = {})" in text
    assert "normalizeRowMergeAliases(value, options)" in text
    assert "normalizeDatasetPayload(item, options)" in text
    assert "normalizeDatasetPayload(child, options)" in text


def test_dataset_uses_internal_vs_canonical_route_normalization_modes() -> None:
    text = _read_text(DATASET_JS)

    assert "const NORMALIZE_OPTIONS_MERGE_INTERNAL = Object.freeze({" in text
    assert "canonicalizeRouteContainer: false" in text
    assert "dropLegacyRouteData: false" in text

    assert "const NORMALIZE_OPTIONS_CANONICAL_OUTPUT = Object.freeze({" in text
    assert "canonicalizeRouteContainer: true" in text
    assert "dropLegacyRouteData: true" in text

    # Progressive and final merge staging should preserve legacy merge behavior.
    assert "normalizeDatasetPayload(\n                checkpointData,\n                NORMALIZE_OPTIONS_MERGE_INTERNAL," in text
    assert "normalizeDatasetPayload(\n                data,\n                NORMALIZE_OPTIONS_MERGE_INTERNAL," in text
    assert "normalizeDatasetPayload(result.value, NORMALIZE_OPTIONS_MERGE_INTERNAL)" in text

    # Public dataset output should expose canonical route.routeData shape.
    assert "normalizeRowMergeAliases(row, NORMALIZE_OPTIONS_CANONICAL_OUTPUT)" in text
    assert "normalizeDatasetPayload(file, NORMALIZE_OPTIONS_CANONICAL_OUTPUT)" in text


def test_dataset_partial_and_final_outputs_use_canonicalized_buffers() -> None:
    text = _read_text(DATASET_JS)

    assert "export function buildDatasetRows(entry, rawFiles, options = {})" in text
    assert "normalizeRowMergeAliases(row, NORMALIZE_OPTIONS_CANONICAL_OUTPUT)" in text
    assert "const canonicalRawFiles = rawFiles.map((file) =>" in text
    assert "const { rows, loadedFiles } = buildDatasetRows(entry, rawFiles);" in text
    assert "const assembled = buildDatasetRows(entry, rawFiles);" in text
    assert "rows: assembled.rows" in text
