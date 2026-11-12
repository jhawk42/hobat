from __future__ import annotations

import logging
import os
import sys
import unittest
import pytest
from types import SimpleNamespace
from unittest.mock import patch

import mdns_hap
import mdns_matter
import mdns_meshcop
import mdns_thread_scopes


def _messages(mock_debug) -> list[str]:
    return [str(call.args[0]) % call.args[1:] for call in mock_debug.call_args_list]


class TestMDNSEnricherRegistry(unittest.TestCase):
    def test_scope_owners_export_complete_enricher_maps(self) -> None:
        self.assertEqual(
            set(mdns_meshcop.MESHCOP_FIELD_ENRICHERS),
            {"sb", "bb", "at", "xa", "pt"},
        )
        self.assertEqual(
            set(mdns_hap.HAP_FIELD_ENRICHERS),
            {"sf", "ff", "sh", "ci"},
        )
        self.assertEqual(
            set(mdns_matter.MATTER_FIELD_ENRICHERS),
            {"VP", "DT", "CD", "D", "PH", "SII", "SAI", "SAT", "T", "ICD"},
        )

    def test_central_registry_is_composed_from_owner_maps(self) -> None:
        expected = {
            **mdns_meshcop.MESHCOP_FIELD_ENRICHERS,
            **mdns_hap.HAP_FIELD_ENRICHERS,
            **mdns_matter.MATTER_FIELD_ENRICHERS,
        }
        self.assertEqual(mdns_thread_scopes.FIELD_ENRICHERS, expected)

    def test_registry_composition_rejects_duplicate_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate mDNS field enricher: shared"):
            mdns_thread_scopes._compose_field_enrichers(
                {"shared": lambda value, name: {}},
                {"shared": lambda value, name: {}},
            )

    def test_registry_composition_rejects_non_callables(self) -> None:
        with self.assertRaisesRegex(TypeError, "mDNS field enricher for bad must be callable"):
            mdns_thread_scopes._compose_field_enrichers({"bad": None})

    def test_representative_fields_keep_enriched_shapes(self) -> None:
        enriched = mdns_thread_scopes._enrich_properties(
            {
                b"xa": bytes.fromhex("0017F21234567890"),
                b"ci": b"5",
                b"VP": b"123+456",
                b"SII": b"1500",
                b"unknown": b"value",
            }
        )

        self.assertEqual(enriched["xa"]["vendor"], "Apple")
        self.assertEqual(enriched["ci"]["category_name"], "Lighting (Light Bulb / Switch)")
        self.assertEqual(enriched["VP"]["vendor_id"], 123)
        self.assertEqual(enriched["VP"]["product_id"], 456)
        self.assertEqual(enriched["SII"]["milliseconds"], 1500)
        self.assertEqual(enriched["SII"]["seconds"], 1.5)
        self.assertEqual(
            enriched["unknown"],
            {
                "full_name": "unknown",
                "decoded": "value",
                "hex": "76616c7565",
                "base64": "dmFsdWU=",
            },
        )

    def test_meshcop_presentation_keeps_representative_log(self) -> None:
        info = SimpleNamespace(
            server="border-router.local.",
            addresses=[b"\x7f\x00\x00\x01"],
            port=49191,
            properties={b"rv": b"1.3", b"extra": b"kept"},
        )

        with patch.object(logging, "debug") as debug:
            mdns_meshcop.print_meshcop_service_info(
                "Border Router._meshcop._udp.local.",
                info,
                {"rv": b"1.3", "extra": b"kept"},
            )

        self.assertEqual(
            _messages(debug),
            [
                "\n[ THREAD BORDER ROUTER FOUND ]",
                "  Instance Name: Border Router._meshcop._udp.local.",
                "  Hostname:      border-router.local.",
                "  Address:       127.0.0.1:49191",
                "\n  Thread Border Router Identity & Capabilities:",
                "    - Protocol Revision (rv): 1.3",
                "\n  Additional Metadata:",
                "    - extra: kept",
            ],
        )

    def test_hap_presentation_keeps_representative_log(self) -> None:
        with patch.object(logging, "debug") as debug:
            mdns_hap.print_hap_service_info(
                "Light._hap._udp.local.",
                None,
                {"id": b"AA:BB", "ci": b"5", "sf": b"1", "extra": b"kept"},
            )

        self.assertEqual(
            _messages(debug),
            [
                "\n  HomeKit Accessory Protocol (HAP) Attributes:",
                "    - Device ID (id): AA:BB",
                "    - Category Identifier (ci): 5 (Lighting (Light Bulb / Switch))",
                "    - Status Flags (sf): 1",
                "      * Pairing: Not Paired | IP Networking: Enabled | Problem Detected: No",
                "      * Individual Bits:",
                "        - Bit 0 (Pairing Status): Not Paired",
                "        - Bit 1 (IP Networking): Enabled",
                "        - Bit 2 (Problem Detected): No",
                "\n  Additional Metadata:",
                "    - extra: kept",
            ],
        )


@pytest.mark.parametrize("raw,number,status,flags", [
    (b"\x00", 0, "No flags set", [False] * 6),
    (b"\x3f", 63, "Connection Allowed, Native Commissioner, Active Commissioner, "
     "Active Thread Partition, Leader Role, Backbone Router", [True] * 6),
    ("21", 33, "Connection Allowed, Backbone Router", [True, False, False, False, False, True]),
])
def test_meshcop_state_bitmap_through_real_dispatch(raw, number, status, flags):
    field = mdns_thread_scopes._enrich_properties({b"sb": raw})["sb"]
    assert field["int_value"] == number
    assert field["status"] == status
    assert [(bit["bit"], bit["name"], bit["value"]) for bit in field["individual_bits"]] == list(zip(
        range(6), ("connection_allowed", "native_commissioner", "active_commissioner",
                   "active_thread_partition", "leader_role", "backbone_router"), flags,
    ))


@pytest.mark.parametrize("raw,number,hex_value,status,flags", [
    (b"\x00", 0, "0000", "No flags set", [False] * 8),
    (b"\xff", 255, "00FF", "Active Commissioning, Native Commissioner, Ethernet Interface, "
     "WiFi Interface, Thread Interface, Thread Multicast Listener EID, "
     "Thread Domain Unicast Address, Backbone Router", [True] * 8),
    (b"\x81", 129, "0081", "Active Commissioning, Backbone Router",
     [True, False, False, False, False, False, False, True]),
])
def test_meshcop_beacon_bitmap_through_real_dispatch(raw, number, hex_value, status, flags):
    field = mdns_thread_scopes._enrich_properties({b"bb": raw})["bb"]
    assert (field["int_value"], field["hex_value"], field["status"]) == (number, hex_value, status)
    assert [bit["value"] for bit in field["individual_bits"]] == flags
    assert [bit["name"] for bit in field["individual_bits"]] == [
        "commissioning_active", "native_commissioner", "eth_interface", "wifi_interface",
        "thread_interface", "thread_ml_eid", "thread_dua", "backbone_router",
    ]


@pytest.mark.parametrize("raw,number,hex_value", [
    (b"\x00", 0, "00000000"), (b"\x01\x23\xab\xcd", 19114957, "0123ABCD"),
])
def test_meshcop_partition_fixed_width_hex(raw, number, hex_value):
    field = mdns_thread_scopes._enrich_properties({b"pt": raw})["pt"]
    assert field["int_value"] == number
    assert field["hex_value"] == hex_value


@pytest.mark.parametrize("raw,values,status", [
    (b"0", ["Paired", "Enabled", "No"], "Pairing: Paired | IP Networking: Enabled | Problem Detected: No"),
    ("7", ["Not Paired", "Disabled", "Yes"], "Pairing: Not Paired | IP Networking: Disabled | Problem Detected: Yes"),
])
def test_hap_status_wire_values(raw, values, status):
    field = mdns_thread_scopes._enrich_properties({b"sf": raw})["sf"]
    assert field["status"] == status
    assert [bit["value"] for bit in field["individual_bits"]] == values
    assert [bit["name"] for bit in field["individual_bits"]] == [
        "pairing_status", "ip_networking_enabled", "problem_detected",
    ]


@pytest.mark.parametrize("raw,flags,features", [
    (b"\x00", [False] * 4, "No special features"),
    (b"\x0f", [True] * 4, "HAP over CoAP, Wi-Fi Throughput Management, Matter Bridge, HAP over BLE"),
    ("5", [True, False, True, False], "HAP over CoAP, Matter Bridge"),
])
def test_hap_feature_wire_values_are_enriched(raw, flags, features):
    field = mdns_thread_scopes._enrich_properties({b"ff": raw})["ff"]
    assert field["supported_features"] == features
    assert [bit["value"] for bit in field["individual_bits"]] == flags
    assert [bit["name"] for bit in field["individual_bits"]] == [
        "supports_hap_over_coap", "supports_wifi_throughput",
        "supports_matter_bridge", "supports_hap_over_ble",
    ]


def test_hash_and_malformed_optional_fields_preserve_envelopes():
    fields = mdns_thread_scopes._enrich_properties({
        b"sh": b"ASOrzQ==", b"sb": "not-hex", b"bb": b"", b"pt": b"",
        b"sf": b"bad", b"ff": "bad", b"unknown": b"kept",
    })
    assert fields["sh"]["hex_value"] == "0123ABCD"
    assert fields["sh"]["decoded"] == "ASOrzQ=="
    assert fields["sh"]["hex"] == "41534f727a513d3d"
    assert fields["sh"]["base64"] == "QVNPcnpRPT0="
    for key in ("sb", "bb", "pt", "sf", "ff"):
        assert "individual_bits" not in fields[key]
        assert "int_value" not in fields[key]
        assert "full_name" in fields[key]
        assert "decoded" in fields[key]
    assert fields["sb"]["decoded"] == "not-hex"
    assert "hex" not in fields["sb"]
    assert fields["bb"]["hex"] == ""
    assert fields["unknown"] == {
        "full_name": "unknown", "decoded": "kept", "hex": "6b657074", "base64": "a2VwdA==",
    }
    bad_hash = mdns_thread_scopes._enrich_properties({b"sh": b"a"})["sh"]
    assert "hex_value" not in bad_hash
    assert bad_hash["decoded"] == "a"


if __name__ == "__main__":
    unittest.main()