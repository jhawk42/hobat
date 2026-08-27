from __future__ import annotations

import os

import pytest

from util_ot_ctl import exec_ot_ctl


@pytest.mark.live
def test_live_otbr_state() -> None:
    if os.environ.get("TD_LIVE_TESTS") != "1":
        pytest.skip("set TD_LIVE_TESTS=1 to run against a configured OTBR")

    output = exec_ot_ctl("state")
    assert output
    assert not output.startswith("Error:"), output