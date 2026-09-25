import json
import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.requires_data_dir


def test_device_projection_matches_cached_capabilities() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "tests/js/run-device-projection.mjs"],
        cwd=root, capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout)["checked"] > 0