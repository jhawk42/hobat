"""Browser health requests stay on the dashboard's direct or proxied origin."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_health_requests_resolve_relative_to_direct_and_proxy_dashboard_paths() -> None:
    script = r"""
      import {
        fetchHealthAssessment,
        fetchHealthDevice,
        fetchHealthSupport,
        startHealthProcessing,
        fetchHealthJob,
        cancelHealthJob,
      } from "./src/js/tdash-health.js";

      const requested = [];
      globalThis.fetch = async (path) => {
        requested.push(path);
        return { ok: true, json: async () => ({}) };
      };

      await fetchHealthAssessment("dataset-id");
      await fetchHealthDevice("assessment-id", "extaddr:0011223344556677");
      await fetchHealthSupport("extpan:0011223344556677");
      await startHealthProcessing("dataset-id");
      await fetchHealthJob("job-id");
      await cancelHealthJob("job-id");

      const pageUrls = [
        "http://localhost:9165/tdash.html",
        "https://ha.example/api/hassio_ingress/session/tdash.html",
      ];
      console.log(JSON.stringify({
        requested,
        resolved: pageUrls.map((base) => requested.map((path) => new URL(path, base).href)),
      }));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert len(result["requested"]) == 7
    assert all(path.startswith("api/") for path in result["requested"])
    assert all(url.startswith("http://localhost:9165/api/") for url in result["resolved"][0])
    assert all(
      url.startswith("https://ha.example/api/hassio_ingress/session/api/")
        for url in result["resolved"][1]
    )


def test_health_sections_use_stored_status_and_evidence_kind_without_reclassification() -> None:
    script = r"""
      import {projectHealthFindingSections} from "./src/js/tdash-health.js";
      const groups = [
        {ruleId: "poor.rule", status: "poor", scope: "device", findings: [{evidenceKind: "snapshot"}]},
        {ruleId: "unknown.rule", status: "unknown", scope: "network", findings: [{evidenceKind: "historical"}]},
        {ruleId: "moderate.rule", status: "moderate", scope: "relationship", findings: [{evidenceKind: "snapshot"}]},
        {ruleId: "strong.rule", status: "strong", scope: "device", findings: [{evidenceKind: "snapshot"}]},
      ];
      const sections = projectHealthFindingSections(groups, {
        status: "all", scope: "all", evidenceKind: "snapshot",
      });
      console.log(JSON.stringify(sections.map(({id, groups: items}) => ({
        id, rules: items.map(({ruleId, status}) => [ruleId, status]),
      }))));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == [
        {"id": "needs-work", "rules": [["poor.rule", "poor"]]},
        {"id": "needs-attention", "rules": [["moderate.rule", "moderate"]]},
        {"id": "going-well", "rules": [["strong.rule", "strong"]]},
    ]


def test_external_routing_is_excluded_from_health_presentation_projections() -> None:
    script = r"""
      import {
        projectHealthFindingDetail,
        projectHealthFindingSections,
        projectHealthSummaryRows,
        projectVisibleHealthFindingGroups,
        reconcileHealthInsightsSelection,
      } from "./src/js/tdash-health.js";

      const finding = (findingId, evidenceKind = "snapshot") => ({
        findingId, rank: 1, evidenceKind, materiality: "network",
        deviceIds: ["extaddr:1"], relationshipIds: [], endpoints: [], evidence: {},
      });
      const external = {
        groupId: "external", ruleId: "network.external-routing", status: "moderate",
        scope: "external", title: "Border Router OMR Addressing", summary: "Hidden",
        confidence: "medium", count: 1, deviceIds: ["extaddr:1"], relationshipIds: [],
        findings: [finding("external-finding")],
      };
      const retained = {
        groupId: "retained", ruleId: "network.router-redundancy", status: "poor",
        scope: "network", title: "Router Redundancy", summary: "Visible",
        confidence: "high", count: 1, deviceIds: [], relationshipIds: [],
        findings: [finding("retained-finding")],
      };
      const assessment = { assessmentId: "assessment", findingGroups: [external, retained] };
      console.log(JSON.stringify({
        visible: projectVisibleHealthFindingGroups(assessment.findingGroups).map(({ ruleId }) => ruleId),
        rows: projectHealthSummaryRows(assessment.findingGroups, { view: "all" }).map(({ ruleId }) => ruleId),
        sections: projectHealthFindingSections(assessment.findingGroups).flatMap(
          ({ groups }) => groups.map(({ ruleId }) => ruleId),
        ),
        detail: projectHealthFindingDetail(external),
        cleared: reconcileHealthInsightsSelection({ selectedGroupId: "external", selectedFindingId: "external-finding" }, assessment),
        retained: reconcileHealthInsightsSelection({ selectedGroupId: "retained", selectedFindingId: "retained-finding" }, assessment),
      }));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["visible"] == ["network.router-redundancy"]
    assert result["rows"] == ["network.router-redundancy"]
    assert result["sections"] == ["network.router-redundancy"]
    assert result["detail"] is None
    assert result["cleared"]["selectedGroupId"] is None
    assert result["cleared"]["detailsOpen"] is False
    assert result["retained"]["selectedGroupId"] == "retained"
    assert result["retained"]["selectedFindingId"] == "retained-finding"


def test_health_summary_projection_sort_counts_and_selection_reconciliation() -> None:
    script = r"""
      import {
        projectHealthFindingDetail,
        projectHealthSummaryRows,
        reconcileHealthInsightsSelection,
      } from "./src/js/tdash-health.js";
      const finding = (findingId, overrides = {}) => ({
        findingId,
        rank: 10,
        evidenceKind: "snapshot",
        materiality: "device",
        deviceIds: [],
        relationshipIds: [],
        endpoints: [],
        evidence: {value: 1},
        whyItMatters: "Impact",
        action: "Act",
        verify: "Verify",
        sourceFiles: ["source.json"],
        ...overrides,
      });
      const groups = [
        {
          groupId: "moderate-device", ruleId: "device.rule", status: "moderate",
          scope: "device", title: "Device issue", summary: "Summary", confidence: "high",
          count: 2, deviceIds: ["extaddr:2", "extaddr:1"], relationshipIds: [],
          findings: [finding("finding-1", {deviceIds: ["extaddr:1"]})],
        },
        {
          groupId: "poor-link", ruleId: "relationship.rule", status: "poor",
          scope: "relationship", title: "Link issue", summary: "Summary", confidence: "medium",
          count: 3, deviceIds: ["extaddr:1", "extaddr:2"], relationshipIds: ["link:1", "link:2"],
          findings: [finding("finding-2", {
            evidenceKind: "historical", materiality: "relationship",
            relationshipIds: ["link:1", "link:2"], whyItMatters: "Link impact",
          })],
        },
        {
          groupId: "strong-network", ruleId: "network.rule", status: "strong",
          scope: "network", title: "Network good", summary: "Summary", confidence: "high",
          count: 1, deviceIds: [], relationshipIds: [],
          findings: [finding("finding-3", {materiality: "network"})],
        },
      ];
      const actionable = projectHealthSummaryRows(groups);
      const all = projectHealthSummaryRows(groups, {view: "all"});
      const detail = projectHealthFindingDetail(groups[1], "finding-2");
      const retained = reconcileHealthInsightsSelection({
        assessmentId: "old", selectedGroupId: "poor-link",
        selectedFindingId: "finding-2", detailsOpen: true,
      }, {assessmentId: "new", findingGroups: groups});
      const cleared = reconcileHealthInsightsSelection({
        selectedGroupId: "missing", selectedFindingId: "missing", detailsOpen: true,
      }, {assessmentId: "new", findingGroups: groups});
      console.log(JSON.stringify({
        actionable: actionable.map((row) => [row.groupId, row.affected.label]),
        all: all.map((row) => row.groupId),
        detail: [detail.affected.label, detail.items[0].isExpanded, detail.shared.action],
        retained,
        cleared,
      }));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["actionable"] == [
        ["poor-link", "2 relationships"],
        ["moderate-device", "2 devices"],
    ]
    assert result["all"] == ["poor-link", "moderate-device", "strong-network"]
    assert result["detail"] == ["2 relationships", True, "Act"]
    assert result["retained"]["assessmentId"] == "new"
    assert result["retained"]["selectedFindingId"] == "finding-2"
    assert result["cleared"]["selectedGroupId"] is None
    assert result["cleared"]["detailsOpen"] is False


def test_health_status_controls_keep_navigation_and_coloring_independent() -> None:
    script = r'''
      import { renderHealthStatus } from "./src/js/tdash-health.js";

      class Element {
        constructor(tagName) {
          this.tagName = tagName;
          this.children = [];
          this.attributes = {};
          this.listeners = {};
          this.textContent = "";
          this.className = "";
        }
        appendChild(child) { this.children.push(child); return child; }
        replaceChildren(...children) { this.children = children; }
        toggleAttribute(name, force) { this.attributes[name] = String(Boolean(force)); }
        setAttribute(name, value) { this.attributes[name] = String(value); }
        addEventListener(type, listener) { this.listeners[type] = listener; }
        click() { this.listeners.click?.(); }
      }
      globalThis.document = { createElement: (tagName) => new Element(tagName) };

      const container = new Element("div");
      let openedInsights = 0;
      let toggledColoring = 0;
      renderHealthStatus(container, {
        assessment: {
          status: "Moderate", completeness: "complete", observedAt: "2026-09-18T00:00:00Z",
        },
        loading: false, error: "", refreshStatus: "", topologyColoringEnabled: false,
      }, {
        openInsights: () => { openedInsights += 1; },
        toggleTopologyColoring: () => { toggledColoring += 1; },
      });
      const [heading, status] = container.children;
      heading.click();
      status.click();
      console.log(JSON.stringify({
        heading: [heading.tagName, heading.textContent],
        status: [status.tagName, status.textContent, status.attributes["aria-pressed"], status.attributes["aria-label"]],
        openedInsights,
        toggledColoring,
      }));
    '''
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["heading"] == ["button", "Health:"]
    assert result["status"] == [
        "button",
        "Moderate (coloring off)",
        "false",
        "Moderate health; topology coloring off",
    ]
    assert result["openedInsights"] == 1
    assert result["toggledColoring"] == 1


def test_health_workflow_controls_and_navigation_contract_are_present() -> None:
    html = (ROOT / "src/tdash.html").read_text(encoding="utf-8")
    health_js = (ROOT / "src/js/tdash-health.js").read_text(encoding="utf-8")
    ui_js = (ROOT / "src/js/tdash-ui.js").read_text(encoding="utf-8")
    table_js = (ROOT / "src/js/tdash-table-renderer.js").read_text(encoding="utf-8")
    topology_js = (ROOT / "src/js/tdash-topology-renderer.js").read_text(encoding="utf-8")
    css = (ROOT / "src/tdash.css").read_text(encoding="utf-8")

    for element_id in (
          "health-view-filter",
      "health-status-filter",
      "health-scope-filter",
      "health-evidence-filter",
      "btn-health-return",
      "btn-health-reset",
      "btn-health-refresh",
      "btn-health-refresh-cancel",
          "health-insights-summary",
          "health-finding-table",
          "health-insights-announcement",
          "health-finding-details",
          "btn-health-finding-close",
    ):
      assert f'id="{element_id}"' in html
    for section in ("Needs Work", "Needs Attention", "Going Well"):
      assert section in health_js
    for action in (
      "showTopology",
      "showTable",
      "inspectDevice",
      "compareEndpoints",
      "applyFilter",
    ):
      assert action in health_js
      assert action in ui_js
    assert "restoreHealthNavigationContext" in ui_js
    assert "renderHealthFindingDetails" in ui_js
    assert "initContextDetailsPanel" in ui_js
    assert 'tableRow.addEventListener("click", () => actions.selectGroup?.(row.groupId));' in health_js
    assert 'aria-current", "true"' in health_js
    assert 'heading.setAttribute("aria-sort"' in health_js
    assert "invalidateHealthRefresh" in ui_js
    assert "Health: refreshing" in health_js
    assert "Health: failed" in health_js
    assert "Health: cancelled" in health_js
    assert "healthTopologyColoringEnabled = false" in ui_js
    assert "setTopologyHealthFindings(findings, healthTopologyColoringEnabled)" in ui_js
    assert "applyHealthAssessmentPresentation(assessment)" in ui_js
    assert "applyHealthAssessmentPresentation(null)" in ui_js
    assert "topologyColoringEnabled" in health_js
    assert 'aria-pressed", String(coloringEnabled)' in health_js
    assert '<option value="all" selected>All</option>' in html
    assert 'view: "all"' in ui_js
    assert 'healthInsightsViewState.view = "all";' in ui_js
    assert 'document.getElementById("health-view-filter").value = "all";' in ui_js
    assert "Health processed:" in health_js
    assert "refreshedAt" in ui_js
    assert html.index('id="btn-health-refresh"') < html.index('id="btn-details-panel-toggle"')
    assert 'lastRenderedDatasetByView.delete("table")' in ui_js
    assert 'lastRenderedDatasetByView.delete("topology")' in ui_js
    assert "setTopologyHealthFindings" in ui_js
    assert "setTableHealthFindings" in ui_js
    assert 'replace(/^extAddress:/, "extaddr:")' in table_js
    assert 'replace(/^extAddress:/, "extaddr:")' in topology_js
    assert "viewModel.rawByIdForDetails.get(nodeId)" in topology_js
    assert '[...HEALTH_COLUMNS, ...TABLE_PRIORITY_COLUMNS]' in table_js
    assert '"Dataset Evidence Pillars"' in health_js
    assert "COVERAGE_STATUS_GLYPHS" in health_js
    assert 'sufficient: "\\u2713"' in health_js
    assert 'limited: "!"' in health_js
    assert 'missing: "\\u00d7"' in health_js
    assert 'if (capability !== status)' in health_js
    assert 'Dataset capability: ${capability}.' in health_js
    assert ".health-coverage-heading" in css
    assert ".health-finding-evidence" in css
    assert ".health-coverage-pillar" in css
    assert ".health-coverage-state.state-sufficient" in css
    assert ".health-coverage-state.state-limited" in css
    assert ".health-coverage-state.state-missing" in css
    assert ".health-status-button" in css
    assert ".health-status-navigation" in css
    assert "overflow-wrap: anywhere" in css
    assert "@media (max-width: 760px)" in css