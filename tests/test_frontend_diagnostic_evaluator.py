from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_diagnostic_evaluator(script: str) -> dict[str, object]:
  node_executable = shutil.which("node")
  if node_executable is None:
    pytest.skip("Node.js is required for frontend diagnostic evaluator tests.")
  result = subprocess.run(
    [
      node_executable,
      "--experimental-default-type=module",
      "--input-type=module",
      "--eval",
      script,
    ],
    cwd=REPO_ROOT,
    check=True,
    capture_output=True,
    text=True,
  )
  return json.loads(result.stdout)


def test_diagnostic_registry_has_unique_sourced_display_metadata() -> None:
    result = _run_diagnostic_evaluator(
        """
        import { DIAGNOSTIC_FILTER_OPTIONS } from "./src/js/tdash-constants.js";

        const options = DIAGNOSTIC_FILTER_OPTIONS.filter((option) => option.value !== "all");
        const result = {
          uniqueValues: new Set(options.map((option) => option.value)).size === options.length,
          allSourced: options.every((option) => typeof option.source === "string" && option.source),
          allDisplayMetadata: options.every((option) =>
            typeof option.severity === "string" &&
            Object.hasOwn(option, "threshold") &&
            typeof option.comparison === "string" &&
            typeof option.unit === "string"
          ),
        };
        console.log(JSON.stringify(result));
        """,
    )

    assert result == {
        "uniqueValues": True,
        "allSourced": True,
        "allDisplayMetadata": True,
    }


def test_evaluator_reports_view_specific_metrics_and_boolean_conditions() -> None:
    result = _run_diagnostic_evaluator(
        """
        import { evaluateDiagnosticsForRecord } from "./src/js/tdash-filters.js";

        const byValue = (items, value) => items.find((item) => item.option.value === value);
        const topology = evaluateDiagnosticsForRecord({
          ifTotalErrorsTotalPktsRatio: 6,
          router_neighbor_has_rss_low: true,
        }, "topology");
        const table = evaluateDiagnosticsForRecord({
          routerNeighbors: [{ frameErrorRate: 12 }],
        }, "table");
        const result = {
          topologyError: byValue(topology, "mac-total-errors-ratio-high"),
          topologyRss: byValue(topology, "router-neighbor-rss-low"),
          tableFrame: byValue(table, "router-neighbor-err-rate-frame-high"),
        };
        console.log(JSON.stringify(result));
        """,
    )

    topology_error = result["topologyError"]
    assert topology_error["metric"] == 6
    assert topology_error["metricText"] == "6.0%"
    assert topology_error["thresholdText"] == ">= 5.0%"
    assert topology_error["triggered"] is True
    assert topology_error["option"]["severity"] == "high"

    topology_rss = result["topologyRss"]
    assert "metric" not in topology_rss
    assert "metricText" not in topology_rss
    assert topology_rss["triggered"] is True

    table_frame = result["tableFrame"]
    assert table_frame["metric"] == 12
    assert table_frame["metricText"] == "12.0%"
    assert table_frame["thresholdText"] == ">= 10.0%"
    assert table_frame["triggered"] is True


def test_insights_keep_only_highest_qualifying_group_tier() -> None:
    result = _run_diagnostic_evaluator(
        """
        import {
          evaluateDiagnosticsForRecord,
          selectHighestQualifyingDiagnosticEvaluations,
        } from "./src/js/tdash-filters.js";

        const evaluations = evaluateDiagnosticsForRecord({
          ifTotalDiscardsTotalPktsRatio: 9.3,
        }, "topology");
        const result = selectHighestQualifyingDiagnosticEvaluations(evaluations)
          .map((item) => item.option.value);
        console.log(JSON.stringify(result));
        """,
    )

    assert result == ["mac-total-discards-ratio-high"]