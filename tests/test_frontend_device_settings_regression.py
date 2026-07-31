from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
UTILS_JS = REPO_ROOT / "src" / "js" / "tdash-utils.js"
TOPOLOGY_JS = REPO_ROOT / "src" / "js" / "tdash-topology-renderer.js"
TABLE_JS = REPO_ROOT / "src" / "js" / "tdash-table-renderer.js"
DATASET_JS = REPO_ROOT / "src" / "js" / "tdash-dataset.js"
UI_JS = REPO_ROOT / "src" / "js" / "tdash-ui.js"
HTML = REPO_ROOT / "src" / "tdash.html"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_device_selection_event_is_shared_by_both_renderers() -> None:
    utils_text = _read_text(UTILS_JS)
    topology_text = _read_text(TOPOLOGY_JS)
    table_text = _read_text(TABLE_JS)

    assert 'DEVICE_SELECTION_EVENT = "tdash:device-selected"' in utils_text
    assert "export function publishDeviceSelection(record)" in utils_text
    assert "publishDeviceSelection(mergedDetails);" in topology_text
    assert "publishDeviceSelection(rawRow);" in table_text


def test_selection_clear_paths_publish_null() -> None:
    topology_text = _read_text(TOPOLOGY_JS)
    table_text = _read_text(TABLE_JS)

    assert topology_text.count("publishDeviceSelection(null);") >= 3
    assert "publishDeviceSelection(null);" in table_text


def test_static_label_cache_can_override_stale_raw_labels() -> None:
    dataset_text = _read_text(DATASET_JS)
    enrichment_start = dataset_text.index("function enrichNodeWithStaticLabel(node)")
    enrichment_end = dataset_text.index("export function enrichRows(rows)", enrichment_start)
    enrichment = dataset_text[enrichment_start:enrichment_end]

    assert "export function setStaticDeviceLabel(extaddr, deviceLabel)" in dataset_text
    assert "staticExtaddrLabelMap.set(key, label);" in dataset_text
    assert "if (toText(node.deviceLabel)" not in enrichment
    assert "return { ...node, deviceLabel: label, device_label: label };" in enrichment


def test_settings_uses_authoritative_get_and_exact_patch_body() -> None:
    ui_text = _read_text(UI_JS)

    assert "async function loadSelectedDeviceLabel()" in ui_text
    assert "if (response.status === 404)" in ui_text
    assert "async function saveSelectedDeviceLabel()" in ui_text
    assert 'method: "PATCH"' in ui_text
    assert "body: JSON.stringify({ deviceLabel })" in ui_text
    assert "setStaticDeviceLabel(extAddress, savedLabel);" in ui_text
    assert "renderCurrentView();" in ui_text
    assert 'response.status === 201 ? "Device label added." : "Device label saved."' in ui_text


def test_settings_guards_stale_responses_and_supports_cancel() -> None:
    ui_text = _read_text(UI_JS)

    assert "requestVersion !== deviceSettingsState.requestVersion" in ui_text
    assert "extAddress !== deviceSettingsState.projection?.extAddress" in ui_text
    assert "inputEl.value = deviceSettingsState.loadedLabel;" in ui_text
    assert 'event.key === "Escape"' in ui_text
    assert 'event.key === "Enter"' in ui_text


def test_invalid_extaddress_is_treated_as_cleared_selection() -> None:
    ui_text = _read_text(UI_JS)

    assert "const hasValidSelection = candidateProjection?.hasValidExtAddress === true;" in ui_text
    assert "deviceSettingsState.record = hasValidSelection ? record : null;" in ui_text
    assert "deviceSettingsState.projection = hasValidSelection ? candidateProjection : null;" in ui_text


def test_settings_markup_starts_empty_and_disabled() -> None:
    html = _read_text(HTML)

    assert 'id="device-rloc16" class="detail-kv-value"></span>' in html
    assert 'id="device-extaddress" class="detail-kv-value"></span>' in html
    assert 'id="device-label" name="device-label" maxlength="128"' in html
    assert 'id="device-settings-status"' in html
    assert 'role="status" aria-live="polite"' in html
    assert "0xa800" not in html
    assert "4e866ce96501b9ed" not in html


def test_insights_panel_uses_shared_selection_and_evaluator() -> None:
    ui_text = _read_text(UI_JS)
    html = _read_text(HTML)

    assert 'id="device-insights-panel-content" role="status" aria-live="polite"' in html
    assert "evaluateDiagnosticsForRecord," in ui_text
    assert "selectHighestQualifyingDiagnosticEvaluations," in ui_text
    assert "function renderDeviceInsights(record)" in ui_text
    assert 'contentEl.replaceChildren();' in ui_text
    assert "evaluateDiagnosticsForRecord(record, currentView)" in ui_text
    assert "selectHighestQualifyingDiagnosticEvaluations(" in ui_text
    assert "evaluation.triggered || (isMoreInfoEnabled() && evaluation.metricText)" in ui_text
    assert "renderDeviceInsights(deviceInsightsState.record);" in ui_text
    assert "document.addEventListener(DEVICE_SELECTION_EVENT" in ui_text
    assert "function initDeviceInsights()" in ui_text
    assert "initDeviceInsights();" in ui_text


def test_topology_selection_includes_adapted_node_diagnostic_fields() -> None:
    topology_text = _read_text(TOPOLOGY_JS)

    assert "const TOPOLOGY_DIAGNOSTIC_FIELDS" in topology_text
    assert "TOPOLOGY_DIAGNOSTIC_FIELDS.map((field) => [field, node[field]])" in topology_text
    assert "mergeForDisplay(rawSource, topologyDiagnosticDetails)" in topology_text