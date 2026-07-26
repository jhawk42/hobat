from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_meshdiag_unknown_child_label_does_not_replace_networkdiag_label() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the JavaScript adaptor regression")

    script = r"""
import { adaptMeshdiagNetworkdiag } from './src/js/tdash-adaptors.js';
import { normalizeDatasetPayload } from './src/js/tdash-utils.js';

const meshdiag = normalizeDatasetPayload([{
  rloc16: '0x2800',
  deviceLabel: 'Parent router',
  children: [{
    rloc16: '0x2808',
    deviceLabel: 'Unknown-0x2808',
    lq: '3',
    mode: { device: 'MTD' },
  }],
}]);
const networkdiag = normalizeDatasetPayload([{
  rloc16: '0x2808',
  extAddress: '36f3f9ed32fe9bf9',
  deviceLabel: 'Front Porch Eve Aqua Water Valve 8B12',
  children: [],
  mode: { device: 'MTD' },
}]);
const fileMap = new Map([
  ['td-otbr-cli-meshdiag-topology.json', meshdiag],
  ['td-otbr-cli-networkdiag-fetch-all.json', networkdiag],
]);

const mergedRows = normalizeDatasetPayload([networkdiag[0]]);
const result = adaptMeshdiagNetworkdiag(fileMap, mergedRows);
const child = result.nodeData.find((node) => node.id === '0x2808');
if (!child) throw new Error('Expected child node 0x2808');
if (child.label !== 'Front Porch Eve Aqua Water Valve 8B12\n0x2808') {
  throw new Error(`Unexpected child label: ${JSON.stringify(child.label)}`);
}
"""

    result = subprocess.run(
        [
            node,
            "--experimental-default-type=module",
            "--input-type=module",
            "--eval",
            script,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr