import pytest


pytestmark = pytest.mark.requires_data_dir


def test_device_projection_matches_cached_capabilities(node_json) -> None:
    result = node_json(
        "tests/js/run-device-projection.mjs", timeout=60,
    )
    assert result["checked"] > 0