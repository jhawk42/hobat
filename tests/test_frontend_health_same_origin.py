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