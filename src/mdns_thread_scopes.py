import argparse
import json
import os
from platform import node
import socket
import sys
import threading
import time
import base64
import logging
from typing import Sequence
import util_network

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
from td_json_key_normalizer import convert_keys_to_camel_case
from util_data import (
    create_checkpoint_filename,
    resolve_data_file_path,
    resolve_data_dir,
    save_json_atomic,
)
from td_const import TD_DATA_DIR_ARG_HELP

from mdns_thread_util import VENDORS, FIELD_METADATA, _base_field_dict, get_vendor_from_oui
from mdns_meshcop import (
    decode_state_bitmap_br,
    format_state_bitmap_br,
    decode_thread_partition_id,
    decode_thread_beacon_bitmap,
    format_thread_beacon_bitmap,
    _enrich_field_sb,
    _enrich_field_bb,
    _enrich_field_at,
    _enrich_field_xa,
    _enrich_field_pt,
    print_meshcop_service_info,
)
from mdns_hap import (
    HAP_CATEGORIES,
    decode_hap_status_flags,
    format_hap_status_flags,
    decode_hap_feature_flags,
    format_hap_feature_flags,
    get_hap_category_name,
    decode_hap_setup_hash,
    _enrich_field_sf,
    _enrich_field_ff,
    _enrich_field_sh,
    _enrich_field_ci,
    print_hap_service_info,
)
from mdns_matter import (
    MATTER_DEVICE_TYPES,
    get_matter_device_type_name,
    parse_matter_vp,
    decode_matter_commissioning_data,
    format_matter_commissioning_data,
    decode_matter_tcp_support,
    get_pairing_hint_description,
    decode_matter_icd_capability,
    parse_fabric_and_node_ids_from_name,
    _enrich_field_VP,
    _enrich_field_DT,
    _enrich_field_CD,
    _enrich_field_D,
    _enrich_field_PH,
    _enrich_field_interval_ms,
    _enrich_field_T,
    _enrich_field_ICD,
    print_matter_service_info,
)

TD_MDNS_BROWSE_TIMEOUT_ENV_NAME = "TD_MDNS_BROWSE_TIMEOUT"
# seconds (default if env var not set)"
TD_MDNS_BROWSE_TIMEOUT_DEFAULT_VALUE = 5

# ---------------------------------------------------------------------------
# Enricher dispatch table
# ---------------------------------------------------------------------------
FIELD_ENRICHERS = {
    "sb": _enrich_field_sb,
    "bb": _enrich_field_bb,
    "at": _enrich_field_at,
    "xa": _enrich_field_xa,
    "pt": _enrich_field_pt,
    "sf": _enrich_field_sf,
    "ff": _enrich_field_ff,
    "sh": _enrich_field_sh,
    "ci": _enrich_field_ci,
    "VP": _enrich_field_VP,
    "DT": _enrich_field_DT,
    "CD": _enrich_field_CD,
    "D": _enrich_field_D,
    "PH": _enrich_field_PH,
    "SII": _enrich_field_interval_ms,
    "SAI": _enrich_field_interval_ms,
    "SAT": _enrich_field_interval_ms,
    "T": _enrich_field_T,
    "ICD": _enrich_field_ICD,
}


def _enrich_properties(properties: dict) -> dict:
    """Return an enriched copy of a zeroconf properties dict.

    Each key maps to a structured object with full_name, decoded, hex, base64,
    plus any field-specific decoded information (bitmaps, categories, etc.).
    Unknown fields fall back to _base_field_dict.
    """
    enriched = {}
    for raw_key, raw_value in properties.items():
        key_str = (
            raw_key.decode("utf-8", errors="replace")
            if isinstance(raw_key, bytes)
            else str(raw_key)
        )
        full_name = FIELD_METADATA.get(key_str, key_str)
        enricher = FIELD_ENRICHERS.get(key_str)
        if enricher:
            enriched[key_str] = enricher(raw_value, full_name)
        else:
            enriched[key_str] = _base_field_dict(raw_value, full_name)
    return enriched


class MDNSDumpListener(ServiceListener):
    def __init__(
        self,
        include_matter_tcp_supported: bool = False,
        omr_ipv6addr_prefix: str = None,
        checkpoint_output_file=None,
    ):
        self._last_update = time.time()
        self.idle_done = threading.Event()
        self._lock = threading.Lock()
        self._records_by_key = {}
        self._include_matter_tcp_supported = include_matter_tcp_supported
        self._omr_ipv6addr_prefix = omr_ipv6addr_prefix
        self._checkpoint_output_file = checkpoint_output_file
        self._checkpoint_write_lock = threading.Lock()

    def _update_last_event_time(self):
        """Record the time of the most recent service event."""
        self._last_update = time.time()

    def _to_json_safe_value(self, value):
        """Convert values to JSON-safe representations."""
        if isinstance(value, bytes):
            return {
                "decoded": value.decode("utf-8", errors="replace"),
                "hex": value.hex(),
                "base64": base64.b64encode(value).decode("ascii"),
            }
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            safe = {}
            for k, v in value.items():
                key_str = (
                    k.decode("utf-8", errors="replace")
                    if isinstance(k, bytes)
                    else str(k)
                )
                safe[key_str] = self._to_json_safe_value(v)
            return safe
        if isinstance(value, (list, tuple, set)):
            return [self._to_json_safe_value(v) for v in value]
        if hasattr(value, "__dict__"):
            return self._to_json_safe_value(vars(value))
        return str(value)

    def _build_record_from_service_info(self, type_: str, name: str, info, event: str):
        """Build a common JSON record from zeroconf ServiceInfo + metadata."""
        parsed_addresses = []
        omr_ipv6_addr = None
        if info and hasattr(info, "parsed_addresses"):
            try:
                parsed_addresses = info.parsed_addresses()
                # Enrich node with OMR IPv6 address  using OMR prefix
                if self._omr_ipv6addr_prefix:
                    omr_ipv6_addr = util_network.find_omr_address_in_list(
                        parsed_addresses, self._omr_ipv6addr_prefix
                    )
            except Exception:
                parsed_addresses = []

        raw_addresses = []
        if info and getattr(info, "addresses", None):
            raw_addresses = [
                a.hex() if isinstance(a, bytes) else str(a) for a in info.addresses
            ]

        properties = {}
        if info and getattr(info, "properties", None):
            properties = _enrich_properties(info.properties)

        # For Matter operational scope, inject CompressedFabricID / NodeID extracted
        # from the service instance name when they are absent from the TXT properties.
        # The instance name encodes the *Compressed* Fabric ID (HKDF-derived 8 bytes),
        # not the raw Matter Fabric ID. Store it under a distinct key so consumers
        # are never confused between the two values.
        if type_ == "_matter._tcp.local.":
            compressed_fabric_id_hex, node_id_hex, compressed_fabric_id_dec, node_id_dec = (
                parse_fabric_and_node_ids_from_name(name)
            )
            if "FabricID_compressed" not in properties and compressed_fabric_id_hex:
                entry = {
                    "full_name": "Compressed Fabric ID",
                    "decoded": compressed_fabric_id_hex,
                    "source": "instance_name",
                }
                if compressed_fabric_id_dec is not None:
                    entry["int_value"] = compressed_fabric_id_dec
                properties["FabricID_compressed"] = entry
            if "NodeID" not in properties and node_id_hex:
                entry = {
                    "full_name": FIELD_METADATA.get("NodeID", "Node ID"),
                    "decoded": node_id_hex,
                    "source": "instance_name",
                }
                if node_id_dec is not None:
                    entry["int_value"] = node_id_dec
                properties["NodeID"] = entry

        service_info = {}
        if info:
            # Start with all public non-callable attributes from ServiceInfo.
            if hasattr(info, "__dict__"):
                try:
                    for k, v in vars(info).items():
                        if not k.startswith("_"):
                            service_info[k] = self._to_json_safe_value(v)
                except TypeError:
                    pass
            for attr_name in dir(info):
                if attr_name.startswith("_") or attr_name in service_info:
                    continue
                try:
                    attr_value = getattr(info, attr_name)
                except Exception:
                    continue
                if callable(attr_value):
                    continue
                service_info[attr_name] = self._to_json_safe_value(attr_value)

            # Override with explicitly structured / enriched fields.
            service_info.update(
                {
                    "name": getattr(info, "name", None),
                    "type": getattr(info, "type", None),
                    "server": getattr(info, "server", None),
                    "port": getattr(info, "port", None),
                    "priority": getattr(info, "priority", None),
                    "weight": getattr(info, "weight", None),
                    "interface_index": getattr(info, "interface_index", None),
                    "host_ttl": getattr(info, "host_ttl", None),
                    "other_ttl": getattr(info, "other_ttl", None),
                    "key": getattr(info, "key", None),
                    "text": self._to_json_safe_value(getattr(info, "text", None)),
                    "addresses_raw_hex": raw_addresses,
                    "addresses_parsed": parsed_addresses,
                    "properties": properties,
                }
            )

        # Build the final record object with metadata and enriched service info.
        retobj = {}
        retobj["record_key"] = f"{type_}|{name}"
        retobj["record_key"] = f"{type_}|{name}"
        retobj["event"] = event
        retobj["captured_at_epoch"] = time.time()
        retobj["captured_at_iso"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        retobj["scope"] = type_
        retobj["name"] = name
        # Add extaddr if xa exists. promote to top level for easier access
        extaddr = service_info.get("properties", {}).get(
            "xa", {}).get("hex", None)
        if extaddr is not None:
            retobj["extAddress"] = extaddr
            
        # promote BR role to top level for easier access
        decoded_mn = service_info.get("properties", {}).get("mn", {}).get("decoded", None)
        if decoded_mn is not None:
            if decoded_mn == "BorderRouter":
                retobj["is_border_router"] = True  
                retobj["role"] = "border router"
                
        # Add omr_ipv6_addr if exists. promote to top level for easier access
        if omr_ipv6_addr is not None:
            retobj["omrIpv6Address"] = omr_ipv6_addr
        retobj["service_info"] = service_info

        return retobj

    def _is_matter_tcp_excluded(self, type_: str, info) -> bool:
        """Return True for _matter._tcp records that advertise TCP support (T=1).

        By default, Matter operational records with T=1 (TCP supported) are
        excluded from JSON output and console printing.  Records with T=0 or
        no T key are included.

        Pass --mattertcpsupported to include T=1 records.
        """
        if self._include_matter_tcp_supported:
            return False  # opt-in: never exclude
        if type_ != "_matter._tcp.local.":
            return False
        if info is None or not getattr(info, "properties", None):
            return False
        for raw_key, raw_val in info.properties.items():
            key_str = (
                raw_key.decode("utf-8", errors="replace")
                if isinstance(raw_key, bytes)
                else str(raw_key)
            )
            if key_str == "T":
                try:
                    val_str = (
                        raw_val.decode("utf-8")
                        if isinstance(raw_val, bytes)
                        else str(raw_val)
                    )
                    return bool(int(val_str))  # T=1 → exclude
                except (ValueError, TypeError):
                    return False
        return False  # T absent → include

    def _upsert_record(self, record):
        with self._lock:
            self._records_by_key[record["record_key"]] = record

    def get_records(self):
        with self._lock:
            return sorted(self._records_by_key.values(), key=lambda r: r["record_key"])

    def _write_checkpoint_snapshot(self) -> None:
        """Persist the current record snapshot to the checkpoint file."""
        if self._checkpoint_output_file is None:
            return
        with self._checkpoint_write_lock:
            records = self.get_records()
            save_json_atomic(
                convert_keys_to_camel_case(records),
                self._checkpoint_output_file,
                indent=2,
            )
        logging.debug(
            "Saved %d mDNS checkpoint record(s) to %s",
            len(records),
            self._checkpoint_output_file,
        )

    def wait_for_idle(self, idle_timeout: float = 30.0, poll: float = 0.5):
        """Block until no service events have arrived for *idle_timeout* seconds,
        then set idle_done so callers can close Zeroconf cleanly."""
        while True:
            time.sleep(poll)
            self._write_checkpoint_snapshot()
            if time.time() - self._last_update >= idle_timeout:
                self.idle_done.set()
                return

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._update_last_event_time()
        info = zc.get_service_info(type_, name)
        if self._is_matter_tcp_excluded(type_, info):
            return
        self._upsert_record(self._build_record_from_service_info(
            type_, name, info, "update"))
        self._write_checkpoint_snapshot()

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._update_last_event_time()
        # Only record remove events for records we actually stored.
        record_key = f"{type_}|{name}"
        with self._lock:
            if record_key not in self._records_by_key:
                return
        self._upsert_record(self._build_record_from_service_info(
            type_, name, None, "remove"))
        self._write_checkpoint_snapshot()
        logging.info("Service Removed: %s", name)

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._update_last_event_time()
        info = zc.get_service_info(type_, name)
        if self._is_matter_tcp_excluded(type_, info):
            return
        self._upsert_record(
            self._build_record_from_service_info(type_, name, info, "add"))
        self._write_checkpoint_snapshot()
        logging.info("Service Added: %s (%s)", name, type_)
        if info:
            logging.debug("\n[ SCOPE: %s ]", type_)
            logging.debug("  Name:    %s", name)
            logging.debug(
                "  Address: %s:%s",
                socket.inet_ntoa(info.addresses[0]) if info.addresses else "Unknown",
                info.port,
            )
            if hasattr(info, "parsed_addresses"):
                logging.debug("  Parsed Addresses: %s", info.parsed_addresses())

            if info.properties:
                is_thread_br_scope = type_ in [
                    "_meshcop._udp.local.",
                    "_trel._udp.local.",
                ]
                is_hap_scope = type_ in [
                    "_hap._udp.local.", "_hap._tcp.local."]
                is_matter_scope = type_ in [
                    "_matter._tcp.local.",
                    "_matterc._udp.local.",
                ]

                props = {k.decode("utf-8"): v for k, v in info.properties.items()}

                if is_thread_br_scope:
                    print_meshcop_service_info(name, info, props)
                elif is_hap_scope:
                    print_hap_service_info(name, info, props)
                elif is_matter_scope:
                    print_matter_service_info(name, type_, info, props)
                else:
                    # For non-Thread BR, non-HAP, and non-Matter scopes, print all TXT records
                    logging.debug("  TXT Records:")
                    for key, value in info.properties.items():
                        val_str = (
                            value.decode("utf-8") if isinstance(value, bytes) else value
                        )
                        logging.debug(
                            "    - %s: %s",
                            key.decode("utf-8") if isinstance(key, bytes) else key,
                            val_str,
                        )


def main(argv: Sequence[str] | None = None) -> int:

    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="Browse Thread-related mDNS scopes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""scope argument:
  (none)   browse all thread scopes (default)
  thread   browse Thread-related scopes (_meshcop._udp, _trel._udp, _hap._udp, _matterc._udp, _matter._tcp)
  br       browse Thread Border Router scopes (_meshcop._udp, _trel._udp)
  hap      browse Apple HomeKit HAP scopes (_hap._udp)
  matter   browse Matter scopes (_matter._tcp, _matterc._udp)

options:
  --haptcp   Also browse _hap._tcp.local. (Wi-Fi HomeKit accessories).
             Applies when scope is 'all' or 'hap'. Off by default.""",
    )

    parser.add_argument(
        "scope",
        nargs="?",
        choices=["thread", "br", "hap", "matter"],
        default="thread",
        help="Scope filter: thread | br | hap | matter  (default: thread scopes)",
    )
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    parser.add_argument(
        "--browse-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=f"Seconds of idle time before auto-exit (default: {TD_MDNS_BROWSE_TIMEOUT_DEFAULT_VALUE}, or {TD_MDNS_BROWSE_TIMEOUT_ENV_NAME} env var)",
    )
    parser.add_argument(
        "--haptcp",
        action="store_true",
        default=False,
        help="Also browse _hap._tcp.local. (Wi-Fi HomeKit accessories). "
        "Applies when scope is 'thread' or 'hap'. Off by default.",
    )
    parser.add_argument(
        "--mattertcpsupported",
        action="store_true",
        default=False,
        help="Include _matter._tcp records where T=1 (TCP supported). "
        "By default those records are excluded.",
    )
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        default=False,
        help="Enable debug logging for detailed mDNS service output.",
    )
    args = parser.parse_args(argv)

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    td_data_dir = resolve_data_dir(data_dir=args.datadir)

    scopes_all = [
        "_meshcop._udp.local.",
        "_hap._udp.local.",
        "_matterc._udp.local.",
        "_matter._tcp.local.",
    ]

    scopes_br = ["_meshcop._udp.local."]
    scopes_br_trel = ["_trel._udp.local."]
    scopes_apple_hap = ["_hap._udp.local."]
    scopes_matter = ["_matterc._udp.local.", "_matter._tcp.local."]

    scope_map = {
        None: (scopes_all, "thread"),
        "thread": (scopes_all, "Thread"),
        "br": (scopes_br, "Thread Border Router"),
        "hap": (scopes_apple_hap, "Apple HomeKit HAP"),
        "matter": (scopes_matter, "Matter"),
    }

    selected_scopes, scope_label = scope_map[args.scope]

    # Opt-in: append _hap._tcp.local. (Wi-Fi HomeKit) when --haptcp is set
    if args.haptcp and args.scope in (None, "thread", "hap"):
        if "_hap._tcp.local." not in selected_scopes:
            selected_scopes = selected_scopes + ["_hap._tcp.local."]

    logging.info(
        f"Browsing {scope_label} scopes ({len(selected_scopes)} service type(s))... (Press Ctrl+C to stop)"
    )

    _default_timeout = float(
        os.environ.get(
            TD_MDNS_BROWSE_TIMEOUT_ENV_NAME, str(
                TD_MDNS_BROWSE_TIMEOUT_DEFAULT_VALUE)
        )
    )
    IDLE_TIMEOUT = (
        args.browse_timeout if args.browse_timeout is not None else _default_timeout
    )

    if args.scope is None:
        scope_tag = "thread"
    else:
        scope_tag = args.scope.lower()

    output_file = resolve_data_file_path(
        f"td-mdns-scopes-{scope_tag}.json", td_data_dir
    )
    checkpoint_file = resolve_data_file_path(
        create_checkpoint_filename(f"td-mdns-scopes-{scope_tag}.json"),
        td_data_dir,
    )

   # Main execution:

    # Get thread network info for reference in parsing and enriching mdns data
    thread_network_info = util_network.fetch_thread_network_info()
    omr_ipv6addr_prefix = (
        thread_network_info["prefix_omr_ipv6addr_prefix"]
        if thread_network_info and "prefix_omr_ipv6addr_prefix" in thread_network_info
        else None
    )

    zeroconf = Zeroconf()
    listener = MDNSDumpListener(
        include_matter_tcp_supported=args.mattertcpsupported,
        omr_ipv6addr_prefix=omr_ipv6addr_prefix,
        checkpoint_output_file=checkpoint_file,
    )

    # Start browsers for each scope
    browsers = [ServiceBrowser(zeroconf, s, listener) for s in selected_scopes]

    # Monitor in a background thread; signals idle_done when quiet for IDLE_TIMEOUT seconds
    idle_thread = threading.Thread(
        target=listener.wait_for_idle,
        kwargs={"idle_timeout": IDLE_TIMEOUT},
        daemon=True,
    )
    idle_thread.start()

    try:
        logging.info(
            f"Waiting (exits automatically after {int(IDLE_TIMEOUT)}s of no new updates)..."
        )
        listener.idle_done.wait()
    except KeyboardInterrupt:
        pass
    finally:
        logging.info("Stopping...")
        zeroconf.close()

        records = listener.get_records()

        save_json_atomic(convert_keys_to_camel_case(records), output_file, indent=2)

        logging.info(f"Saved {len(records)} mDNS record(s) to {output_file}")
        logging.debug(json.dumps(records, indent=2))
        logging.debug("Saved mDNS scope data into %s as JSON:\n%s",
                output_file, json.dumps(records, indent=2))

if __name__ == "__main__":
    sys.exit(main())
