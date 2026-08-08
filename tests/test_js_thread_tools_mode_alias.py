from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_thread_tools_child_mode_alias_corrects_synthesized_nodes() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the JavaScript adaptor regression")

    script = r"""
import { adaptThreadToolsNative } from './src/js/tdash-adaptors.js';

const diagnostics = [{
  macAddr: 0x2800,
  extMacAddr: 'parent',
  mode: { ftd: true },
  children: [
    { macAddr: 0x2818, extAddress: 'mtd-child', isDeviceTypeMtd: false },
    { macAddr: 0x2808, extAddress: 'ftd-child', isDeviceTypeMtd: true },
  ],
}, {
  macAddr: 0x2818,
  extMacAddr: 'mtd-child',
  mode: { ftd: true },
  isSynthesized: true,
}, {
  macAddr: 0x2808,
  extMacAddr: 'ftd-child',
  mode: { ftd: true },
  isSynthesized: true,
}];

const result = adaptThreadToolsNative(new Map([
  ['diagnostics.json', { diagnostics }],
]));
const mtdNode = result.nodeData.find((item) => item.id === '0x2818');
const ftdNode = result.nodeData.find((item) => item.id === '0x2808');
const router = result.nodeData.find((item) => item.id === '0x2800');
const childRows = result.routerChildByRloc16.get('0x2800').router_child_table;
const mtdRow = childRows.find((item) => item.macAddr === 0x2818);
const ftdRow = childRows.find((item) => item.macAddr === 0x2808);

if (mtdRow.isDeviceTypeFtd !== false || ftdRow.isDeviceTypeFtd !== true) {
  throw new Error('Expected isDeviceTypeFtd to preserve the Thread Tools boolean encoding');
}
if (mtdNode.modeDevice !== 'MTD' || mtdNode.shape !== 'dot' || mtdNode.isRouter) {
  throw new Error(`Unexpected MTD node: ${JSON.stringify(mtdNode)}`);
}
if (ftdNode.modeDevice !== 'FTD' || ftdNode.shape !== 'dot' || ftdNode.isRouter) {
  throw new Error(`Unexpected FTD child node: ${JSON.stringify(ftdNode)}`);
}
if (router.shape !== 'hexagon' || !router.isRouter) {
  throw new Error(`Unexpected router node: ${JSON.stringify(router)}`);
}
"""

    result = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr