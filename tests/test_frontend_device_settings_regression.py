from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
UTILS_JS = REPO_ROOT / "src" / "js" / "tdash-utils.js"
TOPOLOGY_JS = REPO_ROOT / "src" / "js" / "tdash-topology-renderer.js"
TOPOLOGY_VIEW_MODEL_JS = REPO_ROOT / "src" / "js" / "tdash-topology-view-model.js"
TABLE_JS = REPO_ROOT / "src" / "js" / "tdash-table-renderer.js"
DATASET_JS = REPO_ROOT / "src" / "js" / "tdash-dataset.js"
UI_JS = REPO_ROOT / "src" / "js" / "tdash-ui.js"
HTML = REPO_ROOT / "src" / "tdash.html"
CONSTANTS_JS = REPO_ROOT / "src" / "js" / "tdash-constants.js"
DIAGNOSTICS_JS = REPO_ROOT / "src" / "js" / "tdash-device-diagnostics.js"


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


def test_matter_details_section_precedes_mdns_and_uses_source_fields() -> None:
    html = _read_text(HTML)
    constants_text = _read_text(CONSTANTS_JS)
    utils_text = _read_text(UTILS_JS)

    assert html.index('id="matter-list"') < html.index('id="mdns-list"')
    assert 'sectionId: "matter-list"' in constants_text
    for field in (
        "matter.deviceLabel",
        "matter.nodeId",
        "matter.matterId",
        "matter.vendorName",
        "matter.vendorModel",
        "matter.serialNumber",
        "matter.matterVersion",
        "matter.dateCommissioned",
        "matter.lastInterview",
        "deviceTypes",
        "networkInterfaces",
    ):
        assert f'"{field}"' in constants_text
    assert '`${listIdPrefix}matter-list`,' in utils_text


def test_table_category_control_is_registry_driven_and_precedes_more_info() -> None:
    html = _read_text(HTML)
    table_text = _read_text(TABLE_JS)
    ui_text = _read_text(UI_JS)

    assert html.index('id="table-column-category"') < html.index('id="btn-more-info"')
    assert 'value="all">All</option>' in html
    assert "getTableColumnCategories" in table_text
    assert "DEVICE_DETAILS_SECTIONS" in table_text
    assert 'applyTableFilters({ preserveSelection: true })' in ui_text
    assert "let _tableSort = null;" in table_text
    assert "function sortedTableRows(rows)" in table_text


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


def test_diagnostics_tab_and_lifecycle_are_separate_from_sync() -> None:
    ui_text = _read_text(UI_JS)
    html = _read_text(HTML)
    diagnostics_text = _read_text(DIAGNOSTICS_JS)

    assert html.index('id="btn-device-details-insights"') < html.index(
        'id="btn-device-details-diagnostics"'
    ) < html.index('id="btn-device-details-settings"')
    assert 'id="device-diagnostics-status"' in html
    assert 'role="status" aria-live="polite"' in html
    assert 'id="btn-device-diagnostics-cancel"' in html
    assert 'name="device-diagnostics-counters" value="both"' in html
    assert 'fetch("/api/device-actions"' in ui_text
    assert 'fetch(`/api/device-action-jobs/${encodeURIComponent(jobId)}`' in ui_text
    assert "invocationVersion !== deviceDiagnosticsState.invocationVersion" in ui_text
    assert "buildDeviceDiagnosticsModel" in diagnostics_text
    assert 'DEVICE_ACTIONS.MATTER_PING' in diagnostics_text
    assert 'DEVICE_ACTIONS.SYSTEM_PING' in diagnostics_text


def test_network_insights_uses_aggregation_and_dataset_refresh_lifecycle() -> None:
    ui_text = _read_text(UI_JS)
    html = _read_text(HTML)

    assert 'id="network-insights-content" role="status" aria-live="polite"' in html
    assert "aggregateNetworkDiagnosticsForRows," in ui_text
    assert "function renderNetworkInsights()" in ui_text
    assert "contentEl.replaceChildren();" in ui_text
    assert "aggregateNetworkDiagnosticsForRows(currentDataset.rows)" in ui_text
    assert "onActivate: renderNetworkInsights" in ui_text
    assert "renderNetworkInsights();\n  const view = currentView;" in ui_text
    assert "renderNetworkInsights();\ninitDeviceDetailsPanelTabs();" in ui_text
    assert "NETWORK_INSIGHT_DEVICE_LIMIT = 10" in ui_text
    assert "condition.triggeredDevices.slice(0, NETWORK_INSIGHT_DEVICE_LIMIT)" in ui_text
    assert "Load a dataset to view network diagnostic insights." in ui_text
    assert "No eligible Thread devices are available in this dataset." in ui_text
    assert "Eligible Thread devices do not provide diagnostic metrics." in ui_text
    assert "not triggering this condition." in ui_text


def test_topology_selection_includes_adapted_node_diagnostic_fields() -> None:
    topology_text = _read_text(TOPOLOGY_VIEW_MODEL_JS)

    assert "const TOPOLOGY_DIAGNOSTIC_FIELDS" in topology_text
    assert "TOPOLOGY_DIAGNOSTIC_FIELDS.map((field) => [field, node[field]])" in topology_text
    assert "mergeForDisplay(viewModel.rawByIdForDetails.get(selectedId) || {}, diagnosticDetails)" in topology_text