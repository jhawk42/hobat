from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_aggregation(script: str) -> dict[str, object]:
    node_executable = shutil.which("node")
    if node_executable is None:
        pytest.skip("Node.js is required for frontend Network Insights tests.")
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


def test_network_aggregation_filters_rows_deduplicates_devices_and_summarizes_metrics() -> None:
    result = _run_aggregation(
        """
        import { aggregateNetworkDiagnosticsForRows } from "./src/js/tdash-filters.js";

        const model = aggregateNetworkDiagnosticsForRows([
          {
            rloc16: "0x1000",
            deviceLabel: "Triggered router",
            type: "router",
            macCounters: {
              ifTotalErrorsTotalPktsRatio: 6,
              ifTotalDiscardsTotalPktsRatio: 0,
            },
          },
          {
            rloc16: "0x1000",
            deviceLabel: "Duplicate router",
            type: "router",
            macCounters: { ifTotalErrorsTotalPktsRatio: 99 },
          },
          {
            rloc16: "0x1001",
            deviceLabel: "Healthy child",
            type: "child",
            macCounters: {
              ifTotalErrorsTotalPktsRatio: 1,
              ifTotalDiscardsTotalPktsRatio: 1,
            },
          },
          {
            name: "mDNS-only record",
            omrIpv6Address: "fd00::1",
            serviceInfo: { addresses: [] },
            macCounters: { ifTotalErrorsTotalPktsRatio: 99 },
          },
        ]);
        const source = model.sources.find((item) => item.source === "macCounters");
        const errors = source.conditions.find((item) =>
          item.option.value === "mac-total-errors-ratio-high",
        );
        const discards = source.conditions.find((item) =>
          item.option.value === "mac-total-discards-ratio-medium",
        );
        console.log(JSON.stringify({
          eligibleDeviceCount: model.eligibleDeviceCount,
          evaluableDeviceCount: model.evaluableDeviceCount,
          errors: {
            triggeredDeviceCount: errors.triggeredDeviceCount,
            triggeredDevices: errors.triggeredDevices,
            observedDeviceCount: errors.observedDeviceCount,
            nonTriggeredDeviceCount: errors.nonTriggeredDeviceCount,
            minMetricText: errors.minMetricText,
            maxMetricText: errors.maxMetricText,
          },
          discards: {
            triggeredDeviceCount: discards.triggeredDeviceCount,
            observedDeviceCount: discards.observedDeviceCount,
            nonTriggeredDeviceCount: discards.nonTriggeredDeviceCount,
            minMetricText: discards.minMetricText,
            maxMetricText: discards.maxMetricText,
          },
        }));
        """,
    )

    assert result == {
        "eligibleDeviceCount": 2,
        "evaluableDeviceCount": 2,
        "errors": {
            "triggeredDeviceCount": 1,
            "triggeredDevices": [
                {"identity": "rloc16:0x1000", "displayName": "Triggered router"},
            ],
            "observedDeviceCount": 2,
            "nonTriggeredDeviceCount": 1,
            "minMetricText": "1.0%",
            "maxMetricText": "6.0%",
        },
        "discards": {
            "triggeredDeviceCount": 0,
            "observedDeviceCount": 2,
            "nonTriggeredDeviceCount": 2,
            "minMetricText": "0.0%",
            "maxMetricText": "1.0%",
        },
    }


def test_network_aggregation_rejects_non_thread_rows() -> None:
    result = _run_aggregation(
        """
        import { aggregateNetworkDiagnosticsForRows } from "./src/js/tdash-filters.js";

        const model = aggregateNetworkDiagnosticsForRows([
          { name: "mDNS", omrIpv6Address: "fd00::1", serviceInfo: {} },
          { recordKey: "static label", deviceLabel: "Unclassified" },
        ]);
        console.log(JSON.stringify(model));
        """,
    )

    assert result == {
        "eligibleDeviceCount": 0,
        "evaluableDeviceCount": 0,
        "sources": [],
    }


def test_network_aggregation_keeps_highest_array_diagnostic_tier() -> None:
    result = _run_aggregation(
        """
        import { aggregateNetworkDiagnosticsForRows } from "./src/js/tdash-filters.js";

        const model = aggregateNetworkDiagnosticsForRows([{
          rloc16: "0x2000",
          type: "router",
          routerNeighbors: [{ frameErrorRate: 35 }],
        }]);
        const source = model.sources.find((item) => item.source === "link_quality");
        console.log(JSON.stringify(source.conditions.map((condition) => ({
          value: condition.option.value,
          triggeredDeviceCount: condition.triggeredDeviceCount,
          maxMetricText: condition.maxMetricText,
        }))));
        """,
    )

    assert result == [
        {
            "value": "router-neighbor-err-rate-frame-critical",
            "triggeredDeviceCount": 1,
            "maxMetricText": "35.0%",
        },
    ]


def test_network_aggregation_keeps_observed_only_thread_metrics() -> None:
    result = _run_aggregation(
        """
        import { aggregateNetworkDiagnosticsForRows } from "./src/js/tdash-filters.js";

        const model = aggregateNetworkDiagnosticsForRows([{
          rloc16: "0x3001",
          type: "child",
          macCounters: { ifTotalErrorsTotalPktsRatio: 0 },
        }]);
        const source = model.sources.find((item) => item.source === "macCounters");
        const condition = source.conditions.find((item) =>
          item.option.value === "mac-total-errors-ratio-medium",
        );
        console.log(JSON.stringify({
          eligibleDeviceCount: model.eligibleDeviceCount,
          evaluableDeviceCount: model.evaluableDeviceCount,
          triggeredDeviceCount: condition.triggeredDeviceCount,
          observedDeviceCount: condition.observedDeviceCount,
          nonTriggeredDeviceCount: condition.nonTriggeredDeviceCount,
          minMetricText: condition.minMetricText,
        }));
        """,
    )

    assert result == {
        "eligibleDeviceCount": 1,
        "evaluableDeviceCount": 1,
        "triggeredDeviceCount": 0,
        "observedDeviceCount": 1,
        "nonTriggeredDeviceCount": 1,
        "minMetricText": "0.0%",
    }