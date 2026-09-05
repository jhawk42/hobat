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
      } from "./src/js/tdash-health.js";

      const requested = [];
      globalThis.fetch = async (path) => {
        requested.push(path);
        return { ok: true, json: async () => ({}) };
      };

      await fetchHealthAssessment("dataset-id");
      await fetchHealthDevice("assessment-id", "extaddr:0011223344556677");
      await fetchHealthSupport("extpan:0011223344556677");

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

    assert len(result["requested"]) == 4
    assert all(path.startswith("api/health/") for path in result["requested"])
    assert all(url.startswith("http://localhost:9165/api/health/") for url in result["resolved"][0])
    assert all(
        url.startswith("https://ha.example/api/hassio_ingress/session/api/health/")
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


def test_health_workflow_controls_and_navigation_contract_are_present() -> None:
    html = (ROOT / "src/tdash.html").read_text(encoding="utf-8")
    health_js = (ROOT / "src/js/tdash-health.js").read_text(encoding="utf-8")
    ui_js = (ROOT / "src/js/tdash-ui.js").read_text(encoding="utf-8")
    table_js = (ROOT / "src/js/tdash-table-renderer.js").read_text(encoding="utf-8")
    topology_js = (ROOT / "src/js/tdash-topology-renderer.js").read_text(encoding="utf-8")
    css = (ROOT / "src/tdash.css").read_text(encoding="utf-8")

    for element_id in (
      "health-status-filter",
      "health-scope-filter",
      "health-evidence-filter",
      "btn-health-return",
      "btn-health-reset",
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
    assert 'lastRenderedDatasetByView.delete("table")' in ui_js
    assert 'lastRenderedDatasetByView.delete("topology")' in ui_js
    assert "setTopologyHealthFindings" in ui_js
    assert "setTableHealthFindings" in ui_js
    assert 'replace(/^extAddress:/, "extaddr:")' in table_js
    assert 'replace(/^extAddress:/, "extaddr:")' in topology_js
    assert "viewModel.rawByIdForDetails.get(nodeId)" in topology_js
    assert '[...HEALTH_COLUMNS, ...TABLE_PRIORITY_COLUMNS]' in table_js
    assert ".health-finding-evidence" in css
    assert ".health-coverage-pillar" in css
    assert "overflow-wrap: anywhere" in css
    assert "@media (max-width: 760px)" in css