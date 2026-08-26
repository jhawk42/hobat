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
          allCapabilities: options.every((option) =>
            typeof option.capabilityKey === "string" && option.capabilityKey
          ),
          allConditionMetadata: options.every((option) =>
            typeof option.conditionKind === "string" &&
            Object.hasOwn(option, "collectionPath") &&
            Object.hasOwn(option, "collectionMetricField") &&
            Object.hasOwn(option, "aggregation") &&
            Object.hasOwn(option, "evaluatorId") &&
            Object.hasOwn(option, "relationshipKind")
          ),
          allDisplayMetadata: options.every((option) =>
            typeof option.severity === "string" &&
            Object.hasOwn(option, "threshold") &&
                (typeof option.comparison === "string" || option.comparison === null) &&
            typeof option.unit === "string"
          ),
        };
        console.log(JSON.stringify(result));
        """,
    )

    assert result == {
        "uniqueValues": True,
        "allSourced": True,
        "allCapabilities": True,
        "allConditionMetadata": True,
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
    assert table_frame["matchedRecords"] == [{"frameErrorRate": 12}]


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


def test_every_diagnostic_option_obeys_metadata_boundaries_in_both_views() -> None:
    result = _run_diagnostic_evaluator(
        """
        import { DIAGNOSTIC_FILTER_OPTIONS } from "./src/js/tdash-constants.js";
        import {
          compareDiagnosticMetric,
          isNodeVisibleByDiagnosticFilter,
          isRowVisibleByDiagnosticFilter,
        } from "./src/js/tdash-filters.js";

        const setPath = (target, path, value) => {
          const parts = path.split(".");
          let current = target;
          parts.slice(0, -1).forEach((part) => {
            current[part] ??= {};
            current = current[part];
          });
          current[parts.at(-1)] = value;
        };
        const isBooleanSummary = (field) => field?.startsWith("has") || field?.includes("_has_");
        const expectedFor = (option, metric) => {
          if (option.evaluatorId === "range") {
            const [lower, upper] = option.threshold;
            return metric >= lower && (option.rangeUpperInclusive ? metric <= upper : metric < upper);
          }
          return compareDiagnosticMetric(metric, option.comparison, option.threshold);
        };
        const samplesFor = (option) => option.evaluatorId === "range"
          ? [option.threshold[0] - 1, option.threshold[0], option.threshold[1], option.threshold[1] + 1]
          : [option.threshold - 1, option.threshold, option.threshold + 1];

        const failures = [];
        for (const option of DIAGNOSTIC_FILTER_OPTIONS.filter((item) => item.value !== "all")) {
          for (const metric of samplesFor(option)) {
            const expected = expectedFor(option, metric);
            const topology = {};
            const table = {};

            if (option.conditionKind === "collection") {
              topology[option.topoNodeField] = isBooleanSummary(option.topoNodeField)
                ? expected
                : metric;
              const relationship = { [option.collectionMetricField]: metric };
              table[option.collectionPath] = [relationship];
            } else if (option.evaluatorId === "link-ratio") {
              topology[option.topoNodeField] = metric;
              table.totalLinks = 100;
              table[option.value.startsWith("low-lq3-") ? "links3" : "links1"] = metric * 100;
            } else {
              topology[option.topoNodeField] = metric;
              setPath(table, option.tableRowField, metric);
            }

            if (option.evaluatorId === "ftd-router") {
              topology.isFtdRouter = true;
              table.mode = { device: "FTD" };
              table.rloc16 = "0x1000";
            }

            const topologyResult = isNodeVisibleByDiagnosticFilter(topology, option.value);
            const tableResult = isRowVisibleByDiagnosticFilter(table, option.value);
            if (topologyResult !== expected || tableResult !== expected) {
              failures.push({ value: option.value, metric, expected, topologyResult, tableResult });
            }
          }
        }
        console.log(JSON.stringify({ failures }));
        """,
    )

    assert result == {"failures": []}


def test_table_capabilities_detect_canonical_mle_change_counters() -> None:
    result = _run_diagnostic_evaluator(
        """
        import { DIAGNOSTIC_FILTER_OPTIONS } from "./src/js/tdash-constants.js";
        import {
          computeTableCapabilities,
          isDiagnosticOptionAvailable,
        } from "./src/js/tdash-filters.js";

        const capabilities = computeTableCapabilities([{
          mleCounters: {
            partIdChangesCount: 5,
            newParentCount: 7,
          },
        }]);
        const available = Object.fromEntries(
          DIAGNOSTIC_FILTER_OPTIONS
            .filter((option) => [
              "medium-partition-changes",
              "high-partition-changes",
              "medium-parent-changes",
              "high-parent-changes",
            ].includes(option.value))
            .map((option) => [
              option.value,
              isDiagnosticOptionAvailable(option, capabilities),
            ]),
        );
        console.log(JSON.stringify({
          hasFieldPartitionChanges: capabilities.hasFieldPartitionChanges,
          hasFieldParentChanges: capabilities.hasFieldParentChanges,
          available,
        }));
        """,
    )

    assert result == {
        "hasFieldPartitionChanges": True,
        "hasFieldParentChanges": True,
        "available": {
            "medium-partition-changes": True,
            "high-partition-changes": True,
            "medium-parent-changes": True,
            "high-parent-changes": True,
        },
    }