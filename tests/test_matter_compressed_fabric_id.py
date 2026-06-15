#!/usr/bin/env python3

import os
import sys


# Import lab parser module directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "lab"))

from matter_device_name_network_info import compute_compressed_fabric_id


def test_compute_compressed_fabric_id_strips_uncompressed_prefix_byte():
    # Sample pulled from td-matter-ws-devices-thread-fetch-all.json fabrics_decoded/raw_entry.
    root_public_key_b64 = (
        "BNIymH8IHRfy4jcZjwq5ASAXeSh71G3k9+LteVLc63Z5s+fKvdol8K/8gO2g8Zom"
        "DXYY9eihkviXtovOVfBOtBk="
    )
    import base64

    root_public_key = base64.b64decode(root_public_key_b64)

    # With matter-js compatible input handling (strip 0x04 prefix), expected ID is:
    # 26940470CE85FB53. This value appears in td-mdns-scopes-matter.json.
    assert compute_compressed_fabric_id(root_public_key, 2) == "26940470CE85FB53"


def test_compute_compressed_fabric_id_accepts_64_byte_key_material():
    import base64

    root_public_key_b64 = (
        "BNIymH8IHRfy4jcZjwq5ASAXeSh71G3k9+LteVLc63Z5s+fKvdol8K/8gO2g8Zom"
        "DXYY9eihkviXtovOVfBOtBk="
    )
    key_65 = base64.b64decode(root_public_key_b64)
    key_64 = key_65[1:]

    assert key_65[0] == 0x04
    assert len(key_65) == 65
    assert len(key_64) == 64

    # Both forms should compute to the same compressed fabric ID.
    assert compute_compressed_fabric_id(key_65, 2) == compute_compressed_fabric_id(key_64, 2)


def test_compute_compressed_fabric_id_invalid_inputs():
    assert compute_compressed_fabric_id(b"", 1) is None
    assert compute_compressed_fabric_id(b"\x04" * 65, None) is None
