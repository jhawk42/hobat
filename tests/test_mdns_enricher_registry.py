from __future__ import annotations

import logging
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

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


if __name__ == "__main__":
    unittest.main()