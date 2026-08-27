from __future__ import annotations

import logging
import os
import sys
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import mdns_matter


def _messages(mock_debug) -> list[str]:
    return [str(call.args[0]) % call.args[1:] for call in mock_debug.call_args_list]


class TestMatterPresentation(unittest.TestCase):
    def test_descriptors_cover_fields_in_presentation_order(self) -> None:
        self.assertEqual(
            [
                (descriptor.txt_key, descriptor.applicability)
                for descriptor in mdns_matter.MATTER_PRESENTATION_DESCRIPTORS
            ],
            [
                ("txtvers", "both"),
                ("VP", "both"),
                ("DT", "both"),
                ("DN", "both"),
                ("RI", "both"),
                ("PI", "both"),
                ("CD", "both"),
                ("D", "both"),
                ("PH", "both"),
                ("PI", "commissionable"),
                ("FabricID", "both"),
                ("FabricID_compressed", "both"),
                ("NodeID", "both"),
                ("SII", "both"),
                ("SAI", "both"),
                ("SAT", "both"),
                ("T", "both"),
                ("ICD", "both"),
            ],
        )

    def test_descriptor_metadata_is_frozen_and_validated(self) -> None:
        descriptor = mdns_matter.MATTER_PRESENTATION_DESCRIPTORS[0]
        with self.assertRaises(FrozenInstanceError):
            descriptor.label = "Changed"

        duplicate = (descriptor, descriptor)
        with self.assertRaisesRegex(ValueError, "Duplicate Matter presentation descriptor"):
            mdns_matter._validate_presentation_descriptors(duplicate)

        invalid_scope = mdns_matter.MatterFieldDescriptor(
            "bad", "Bad", "invalid", str, mdns_matter._format_text
        )
        with self.assertRaisesRegex(ValueError, "Invalid Matter descriptor applicability"):
            mdns_matter._validate_presentation_descriptors((invalid_scope,))

        invalid_callback = mdns_matter.MatterFieldDescriptor(
            "bad", "Bad", "both", None, mdns_matter._format_text
        )
        with self.assertRaisesRegex(TypeError, "Matter presentation callback"):
            mdns_matter._validate_presentation_descriptors((invalid_callback,))

    def test_reusable_decoders_accept_bytes_strings_and_malformed_values(self) -> None:
        self.assertEqual(mdns_matter._decode_text(b"value"), "value")
        self.assertEqual(mdns_matter._decode_text("value"), "value")
        self.assertEqual(mdns_matter._decode_interval(b"1250"), ("1250", 1.25))
        self.assertEqual(mdns_matter._decode_interval("bad"), ("bad", None))
        self.assertEqual(mdns_matter._decode_tcp(b"1"), ("1", True))
        self.assertEqual(mdns_matter._decode_tcp("bad"), ("bad", None))

    def test_commissionable_fields_keep_order_and_details(self) -> None:
        props = {
            "txtvers": b"1",
            "VP": b"123+456",
            "DT": b"17",
            "DN": b"Kitchen Light",
            "RI": b"rotating-id",
            "PI": b"Open the app",
            "CD": b"1",
            "D": b"3840",
            "PH": b"33",
            "SII": b"1500",
            "SAI": b"250",
            "SAT": b"bad",
            "T": b"0",
            "ICD": b"1",
            "X-Extra": b"kept",
        }

        with patch.object(logging, "debug") as debug:
            mdns_matter.print_matter_service_info(
                "commissionable._matterc._udp.local.",
                "_matterc._udp.local.",
                None,
                props,
            )

        self.assertEqual(
            _messages(debug),
            [
                "\n  Matter Commissionable (Pairing Mode) Attributes:",
                "    - TXT Record Version (txtvers): 1",
                "    - Vendor Product (VP): 123+456",
                "      * Vendor ID: 123",
                "      * Product ID: 456",
                "    - Device Type (DT): 17 (On/Off Light)",
                "    - Device Name (DN): Kitchen Light",
                "    - Rotating Identifier (RI): rotating-id",
                "    - Product Identifier (PI): Open the app",
                "    - Commissioning Data (CD): 1",
                "      * Status: Operational",
                "    - Discriminator (D): 3840 (0xf00)",
                "    - Pairing Hint (PH): 33",
                "      * Description: Setup Code Available | Uses NFC",
                "    - Pairing Instruction (PI): Open the app",
                "    - Sleepy Idle Interval (SII): 1500ms (1.5s)",
                "    - Sleepy Active Interval (SAI): 250ms (0.2s)",
                "    - Sleepy Active Threshold (SAT): bad",
                "    - TCP Support (T): 0 (Not Supported)",
                "    - Intermittently Connected Device (ICD): 1",
                "      * Description: Long Idle Time (LIT) Device with Extended Sleep/Check-in Protocol",
                "\n  Additional Metadata:",
                "    - X-Extra: kept",
            ],
        )

    def test_operational_ids_fall_back_to_instance_name(self) -> None:
        with patch.object(logging, "debug") as debug:
            mdns_matter.print_matter_service_info(
                "000000000000000A-000000000000000B._matter._tcp.local.",
                "_matter._tcp.local.",
                None,
                {"FabricID": "raw-fabric"},
            )

        self.assertEqual(
            _messages(debug),
            [
                "\n  Matter Operational Attributes:",
                "    - Fabric ID (raw): raw-fabric",
                "    - Compressed Fabric ID (from name): 000000000000000A",
                "      * Decimal: 10",
                "    - Node ID (from name): 000000000000000B",
                "      * Decimal: 11",
            ],
        )

    def test_malformed_regular_values_keep_fallback_output(self) -> None:
        props = {"VP": b"bad", "DT": b"bad", "CD": b"bad", "D": b"bad", "T": b"bad"}

        with patch.object(logging, "debug") as debug:
            mdns_matter.print_matter_service_info(
                "bad._matterc._udp.local.", "_matterc._udp.local.", None, props
            )

        self.assertEqual(
            _messages(debug),
            [
                "\n  Matter Commissionable (Pairing Mode) Attributes:",
                "    - Vendor Product (VP): bad",
                "    - Device Type (DT): bad (Invalid Device Type)",
                "    - Commissioning Data (CD): bad",
                "    - Discriminator (D): bad",
                "    - TCP Support (T): bad",
            ],
        )


if __name__ == "__main__":
    unittest.main()