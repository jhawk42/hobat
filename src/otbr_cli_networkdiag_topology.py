import argparse
import os
import re
import json
import sys
import time
import logging

from copy import deepcopy
from typing import Sequence
from const import EXTADDR_DEVICE_LABEL_MAP_FILENAME, TD_DATA_DIR_ARG_HELP
import util_ot_ctl
import util_network
from otbr_cli_router_table import fetch_and_parse_router_table
from extaddr_device_label_map import load_extaddr_device_label_map
from util_data import data_file_path, resolve_data_dir, save_json_atomic


# Thread TLV (Type-Length-Value)
# TLV value sets used for different detail levels by networkdiag functions to request Thread diagnostic information from devices.
# Some devices fail to return any TLV data when the list contains certain TLVs e.g. 28 Thread Stack Version TLV.
# So multiple detail levels allow retries with progressively simpler TLV sets.

# TLV 0 = Ext Address
# TLV 1 = RLOC16
# TLV 2 = Mode
# TLV 8 = IPv6 Address List
# TLV 9 = MAC Counters
# TLV 16 = Child Table
# TLV 28 = Thread Stack Version
# TLV 34 = MLE Counters

# ROUTER TLVs - includes childtable
TLV_VALUES_DETAILED = "0 1 2 28 8 16 9 34"
TLV_VALUES_MEDIUM = "0 1 2 8 16 9"
TLV_VALUES_SIMPLE = "0 1 2 8"
# CHILD TLVs
TLV_VALUES_CHILD_DETAILED = "0 1 2 8 28 9 34"
TLV_VALUES_CHILD_MEDIUM = "0 1 2 8 9"
TLV_VALUES_CHILD_SIMPLE = "0 1 2 8"


def fetch_ipv6_addresses():
    """
    Queries Thread network for IPv6 addresses of all routers.
    Runs: ot-ctl meshdiag topology ip6-addrs
    Returns a dictionary mapping RLOC16 to IPv6 addresses.
    """
    output = util_ot_ctl.exec_ot_ctl("meshdiag topology ip6-addrs")
    logging.debug(
        f"[DEBUG] Output of 'meshdiag topology ip6-addrs':\n{output}\n")

    ipv6_map = {}

    # Parse output to extract RLOC16 and IPv6 address pairs
    # Expected format: "RLOC:0x5000 => ffxx::0200:x:x:x" or similar
    lines = output.split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Match patterns like "RLOC16: 0x5000" or "RLOC: 0x5000" followed by IPv6
        rloc_match = re.search(r"0x[0-9a-fA-F]{4}", line)

        # Match IPv6 addresses (simplified pattern)
        ipv6_match = re.search(
            r"([0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F]{0,4}", line)

        if rloc_match and ipv6_match:
            rloc = rloc_match.group(0)
            ipv6 = ipv6_match.group(0)

            if rloc not in ipv6_map:
                ipv6_map[rloc] = []
            ipv6_map[rloc].append(ipv6)

    return ipv6_map


def parse_ipv6_address_list(output):
    """Extracts IPv6 Address List from diagnostic output."""
    ipv6_list = []
    # Match IPv6 addresses in the IP6 Address List section
    lines = output.split("\n")
    in_ipv6_section = False
    for line in lines:
        if "IP6 Address List:" in line:
            in_ipv6_section = True
            continue
        if in_ipv6_section:
            if line.strip().startswith("- "):
                ipv6_addr = line.strip().lstrip("- ")
                ipv6_list.append(ipv6_addr)
            # Check for end of IPv6 section (next section header)
            elif line.strip() and (
                line.strip().startswith("ChildId:")
                or line.strip().startswith("Child Table:")
                or line.strip().startswith("MAC Counters:")
                or line.strip().startswith("MLE Counters:")
                or ("Ext Address:" in line and "Rloc16:" not in line)
            ):
                # End of IP6 list section
                break
            elif not line.strip():
                # Empty line might also indicate section boundary
                continue
    return ipv6_list


# TLV 2: Mode TLV to get more detailed info about the node's capabilities and role (e.g., if it's a sleepy end device, router-eligible end device, or full router) which can help better understand the topology and identify potential issues with devices that are not behaving as expected. This will also help enrich the topology map with more detailed information about each node's role and capabilities in the network.


def device_type_from_mode(mode):
    """Returns device classification from Thread mode flags."""
    if (
        mode.get("rx_on_when_idle") == 1
        and mode.get("device_type") == 1
        and mode.get("network_data") == 1
    ):
        return "FTD"
    if (
        mode.get("rx_on_when_idle") == 0
        and mode.get("device_type") == 0
        and mode.get("network_data") == 0
    ):
        return "MTD"
    return "Unknown"


def parse_mode_flags(output):
    """Extracts top-level TLV 2 Mode flags from diagnostic output."""
    mode = {}
    lines = output.split("\n")
    in_mode_section = False

    for line in lines:
        stripped = line.strip()

        # Top-level "Mode:" line (child mode blocks are indented)
        if stripped == "Mode:" and not line.startswith(" "):
            in_mode_section = True
            continue

        if not in_mode_section:
            continue

        # End mode section at next top-level field
        if stripped and not line.startswith(" "):
            break

        if "RxOnWhenIdle:" in line:
            val_match = re.search(r"RxOnWhenIdle:\s*(\d+)", line)
            if val_match:
                mode["rx_on_when_idle"] = int(val_match.group(1))
        elif "DeviceType:" in line:
            val_match = re.search(r"DeviceType:\s*(\d+)", line)
            if val_match:
                mode["device_type"] = int(val_match.group(1))
        elif "NetworkData:" in line:
            val_match = re.search(r"NetworkData:\s*(\d+)", line)
            if val_match:
                mode["network_data"] = int(val_match.group(1))

        # Determine device type based on mode flags
        mode["device"] = device_type_from_mode(mode)

    return mode


def parse_child_table(output, parent_rloc16):
    """Extracts detailed Child Table information from diagnostic output."""
    children = []
    lines = output.split("\n")
    in_child_section = False
    current_child = None

    # Get parent prefix for child rloc16s
    parent_rloc16_int = int(
        parent_rloc16, 0
    )  # Auto-detect base (handles both 0xNNNN and decimal)

    for i, line in enumerate(lines):
        if "Child Table:" in line:
            in_child_section = True
            continue

        if not in_child_section:
            continue

        # Detect end of Child Table section
        if line.strip() and not line.startswith(" ") and "ChildId" not in line:
            if current_child:
                current_child["mode"]["device"] = device_type_from_mode(
                    current_child["mode"]
                )
                children.append(current_child)
                current_child = None  # Prevent duplicate append after loop
            break

        # Match ChildId
        if "ChildId:" in line:
            if current_child:
                current_child["mode"]["device"] = device_type_from_mode(
                    current_child["mode"]
                )
                children.append(current_child)
            child_id_match = re.search(
                r"ChildId:\s*(0x[0-9a-fA-F]+|\d+)", line)
            child_id = child_id_match.group(1) if child_id_match else "Unknown"

            # Child RLOC16 is derived from parent RLOC16 by replacing the last byte with the ChildId (0-255)
            # For example, if parent RLOC16 is 0x0400 and ChildId is 0x0006, child RLOC16 would be 0x0406
            try:
                child_id_int = int(
                    child_id, 0
                )  # Auto-detect base (handles both 0xNNNN and decimal)
                child_rloc16_int = (parent_rloc16_int & 0xFF00) | (
                    child_id_int & 0x00FF
                )
                child_rloc16 = f"0x{child_rloc16_int:04x}"
            except ValueError:
                child_rloc16 = f"Unknown-{child_id}"

            current_child = {
                "id": child_id,
                "rloc16": child_rloc16,
                "timeout": None,
                "link_quality": None,
                "mode": {},
            }
        elif current_child:
            # Parse Timeout
            if "Timeout:" in line:
                timeout_match = re.search(r"Timeout:\s*(\d+)", line)
                if timeout_match:
                    current_child["timeout"] = int(timeout_match.group(1))
            # Parse Link Quality
            elif "Link Quality:" in line:
                lq_match = re.search(r"Link Quality:\s*(\d+)", line)
                if lq_match:
                    current_child["link_quality"] = int(lq_match.group(1))
            # Parse Mode fields
            elif "RxOnWhenIdle:" in line:
                val_match = re.search(r"RxOnWhenIdle:\s*(\d+)", line)
                if val_match:
                    current_child["mode"]["rx_on_when_idle"] = int(
                        val_match.group(1))
            elif "DeviceType:" in line:
                val_match = re.search(r"DeviceType:\s*(\d+)", line)
                if val_match:
                    current_child["mode"]["device_type"] = int(
                        val_match.group(1))
            elif "NetworkData:" in line:
                val_match = re.search(r"NetworkData:\s*(\d+)", line)
                if val_match:
                    current_child["mode"]["network_data"] = int(
                        val_match.group(1))

    if current_child:
        current_child["mode"]["device"] = device_type_from_mode(
            current_child["mode"]
        )
        children.append(current_child)

    return children


def parse_mac_counters(output):
    """Extracts MAC Counters from diagnostic output.

    Thread network MAC counters track packet-level performance, where high errors indicate radio
    interference or weak signal strength, and high discards often signal network congestion or
    inadequate buffer space. Common causes include improperly placed Border Routers, interference
    with 2.4GHz Wi-Fi, or outdated firmware, requiring node reboots or improved mesh topology

    Troubleshooting Steps:
    -Improve Topology: Ensure Thread Border Routers are well-spaced and not directly next to Wi-Fi
     routers to minimize interference.
    -Reboot Devices: Cycle power on unresponsive accessories (turn off/on) to clear hung buffers
     and force reconnection.
    -Check Signal: If a device has high discard counts, it may be too far from its neighbors in
     the mesh, requiring a repeater or closer proximity to a border router

    Example MAC Counters:
        "mac_counters": {
            "ifinunknownprotos": 0,
            "ifinerrors": 2654,
            "ifouterrors": 175,
            "ifinucastpkts": 1019,
            "ifinbroadcastpkts": 32654,
            "ifindiscards": 17,
            "ifoutucastpkts": 2235,
            "ifoutbroadcastpkts": 243,
            "ifoutdiscards": 0
        }

    """

    counters = {}
    lines = output.split("\n")
    in_mac_section = False

    for line in lines:
        if "MAC Counters:" in line:
            in_mac_section = True
            continue
        if not in_mac_section:
            continue

        # End of MAC Counters section
        if line.strip() and not line.startswith(" ") and ":" not in line.split()[0]:
            break
        if line.strip() and not line.startswith(" ") and line.strip() != "":
            if any(x in line for x in ["Counters:", "Errors", "Pkts", "Discards"]):
                break

        # Parse counter lines like "IfInUnknownProtos: 0"
        if ":" in line and line.startswith(" "):
            parts = line.strip().split(":")
            if len(parts) == 2:
                key = parts[0].strip().lower().replace(" ", "_")
                try:
                    value = int(parts[1].strip())
                    counters[key] = value
                except ValueError:
                    pass

    # Enhance MAC counters with totals
    if counters:
        # Calculate total packets by summing unicast and broadcast packets for both in and out directions.
        # This provides a more comprehensive view of the overall traffic volume at the MAC layer, which can
        # help contextualize the error and discard counts. For example, a high number of errors may be more
        # concerning if the total packet count is low, while it may be less significant if the total packet
        # count is very high. By having the total packet count, we can better assess the health and performance
        # of the network and identify potential issues that may need to be addressed.

        # total IN packets = IN unicast + IN broadcast
        ifintotalpkts = counters.get("ifinucastpkts", 0) + counters.get("ifinbroadcastpkts", 0)
        counters["ifintotalpkts"] = ifintotalpkts

        # total OUT packets = OUT unicast + OUT broadcast
        ifouttotalpkts = counters.get("ifoutucastpkts", 0) + counters.get("ifoutbroadcastpkts", 0)
        counters["ifouttotalpkts"] = ifouttotalpkts

        # total IN and OUT packets = IN unicast + IN broadcast + OUT unicast + OUT broadcast
        counters["iftotalpkts"] = ifintotalpkts + ifouttotalpkts

        # Errors are from malformed packets, interference, or weak signal strength causing corruption during
        # transmission, while discards typically indicate congestion or buffer overflows where packets are
        # dropped due to lack of resources to process them. By calculating the total packets, errors, and
        # discards, we can get a clearer picture of the overall health and performance of the network at
        # the MAC layer. High error counts relative to total packets may indicate issues with signal quality
        # or interference, while high discard counts may point to congestion or insufficient buffering
        # capacity in the network.
        #
        # Discards can also occur when a device is overwhelmed with more traffic than it can handle, which
        # may be the case in a dense network or if a device has limited resources. By looking at the total
        # packets in relation to errors and discards, we can better understand whether high error/discard
        # counts are significant issues that need to be addressed or if they are just a small fraction of
        # the overall traffic and may not be as concerning.

        # IN Errors
        ifinerrors = counters.get("ifinerrors", 0)
        # OUT Errors
        ifouterrors = counters.get("ifouterrors", 0)
        # TOTAL Errors
        totalerrors = ifinerrors + ifouterrors
        counters["iftotalerrors"] = totalerrors

        # Discards
        # IN Discards
        ifindiscards = counters.get("ifindiscards", 0)
        # OUT Discards
        ifoutdiscards = counters.get("ifoutdiscards", 0)
        # TOTAL Discards
        totaldiscards = ifindiscards + ifoutdiscards
        counters["iftotaldiscards"] = totaldiscards

        # TOTAL IN  errdiscs (errors and discards)
        iftotal_inerrdiscs = ifinerrors + ifindiscards
        counters["iftotal_inerrdiscs"] = iftotal_inerrdiscs
        
        # TOTAL OUT errdiscs (errors and discards)
        iftotal_outerrdiscs = ifouterrors + ifoutdiscards
        counters["iftotal_outerrdiscs"] = iftotal_outerrdiscs

        # TOTAL IN AND OUT errdiscs (errors and discards)
        iftotal_errdiscs = totalerrors + totaldiscards
        counters["iftotal_errdiscs"] = iftotal_errdiscs

        # Calc Ratios

        # TOTAL IN ERRORS DISCARDS
        if iftotal_inerrdiscs > 0:
            # Calc ratio of ifinerrors to total in errors and discards
            ifinerrors_totalinerrdiscs_ratio = round((ifinerrors / iftotal_inerrdiscs), 1)
            counters["ifinerrors_totalinerrdiscs_ratio"] = ifinerrors_totalinerrdiscs_ratio

            # Calc ratio of ifindiscards to total in errors and discards
            ifindiscards_totalinerrdiscs_ratio = round((ifindiscards / iftotal_inerrdiscs), 1)
            counters["ifindiscards_totalinerrdiscs_ratio"] = ifindiscards_totalinerrdiscs_ratio

        # TOTAL OUT ERRORS DISCARDS
        if iftotal_outerrdiscs > 0:
            # Calc ratio of ifouterrors to total out errors and discards
            ifouterrors_totalouterrdiscs_ratio = round((ifouterrors / iftotal_outerrdiscs), 1)
            counters["ifouterrors_totalouterrdiscs_ratio"] = ifouterrors_totalouterrdiscs_ratio

            # Calc ratio of ifoutdiscards to total out errors and discards
            ifoutdiscards_totalouterrdiscs_ratio = round((ifoutdiscards / iftotal_outerrdiscs), 1)
            counters["ifoutdiscards_totalouterrdiscs_ratio"] = ifoutdiscards_totalouterrdiscs_ratio

        # TOTAL IN AND OUT ERRORS DISCARDS
        if iftotal_errdiscs > 0:
            # Calc ratio of total errors to total errors and discards
            iftotalerrors_totalerrdiscs_ratio = round((totalerrors / iftotal_errdiscs), 1)
            counters["iftotalerrors_totalerrdiscs_ratio"] = iftotalerrors_totalerrdiscs_ratio

            # Calc ratio of total discards to total errors and discards
            iftotaldiscards_totalerrdiscs_ratio = round((totaldiscards / iftotal_errdiscs), 1)
            counters["iftotaldiscards_totalerrdiscs_ratio"] = iftotaldiscards_totalerrdiscs_ratio

        # Help determine if high error counts are significant
        # Format the percentages to 1 decimal place when printing
        
        # Calc errors ratio of inerrors to IN total packets
        if ifintotalpkts > 0:
            counters["ifinerrors_intotalpkts_ratio"] = round(
                (ifinerrors / ifintotalpkts), 1)

        # Calc errors ratio of outerrors to OUT total packets
        if ifouttotalpkts > 0:
            counters["ifouterrors_outtotalpkts_ratio"] = round(
                (ifouterrors / ifouttotalpkts), 1)

        # calc errors pct relative to total errors to help determine if high error counts are significant or just a small fraction of overall traffic. This can help prioritize troubleshooting efforts by focusing on nodes that have a high percentage of errors, which may indicate more severe issues with signal quality or interference that need to be addressed to improve network performance and reliability.
        if totalerrors > 0:
            counters["ifinerrors_totalerrors_pct"] = round(
                (ifinerrors / totalerrors) * 100, 1)
            counters["ifouterrors_totalerrors_pct"] = round(
                (ifouterrors / totalerrors) * 100, 1)
        else:
            counters["ifinerrors_totalerrors_pct"] = 0
            counters["ifouterrors_totalerrors_pct"] = 0

        # Help determine if high discard counts are significant
        # Format the percentages to 1 decimal place when printing

        # Calc discards ratio of indiscards to IN total packets
        if ifintotalpkts > 0:
            counters["ifindiscards_intotalpkts_ratio"] = round(
                (ifindiscards / ifintotalpkts), 1)

        # Calc discards ratio of outdiscards to OUT total packets
        if ifouttotalpkts > 0:
            counters["ifoutdiscards_outtotalpkts_ratio"] = round(
                (ifoutdiscards / ifouttotalpkts), 1)

        # calc discards pct relative to total discards to help determine if high discard counts are significant or just a small fraction of overall traffic. This can help prioritize troubleshooting efforts by focusing on nodes that have a high percentage of discards, which may indicate more severe issues with congestion or insufficient buffering capacity that need to be addressed to improve network performance and reliability.
        if totaldiscards > 0:
            counters["ifindiscards_totaldiscards_pct"] = round(
                (ifindiscards / totaldiscards) * 100, 1
            )
            counters["ifoutdiscards_totaldiscards_pct"] = round(
                (ifoutdiscards / totaldiscards) * 100, 1
            )
        else:
            counters["ifindiscards_totaldiscards_pct"] = 0
            counters["ifoutdiscards_totaldiscards_pct"] = 0

    return counters


def parse_mle_counters(output):
    """Extracts MLE Counters from diagnostic output.

    Thread Network MLE Counters

    MLE (Mesh Link Establishment) counters provide insights into the stability and performance of the Thread mesh network.
    High counts of MLE errors or failed attempts can indicate issues with network connectivity, such as interference,
    weak signal strength, or misconfigured devices.

    Common causes include devices:
    - being too far apart, outdated firmware,
    - excessive network congestion.

    Troubleshooting steps involve
    - improving device placement to ensure better signal strength,
    - updating firmware to fix known issues, and
    - rebooting devices to clear any temporary network glitches.

    Example MLE Counters:
        "mle_counters": {
        "disabledrole": 0,
        "detachedrole": 5,
        "childrole": 5,
        "routerrole": 0,
        "leaderrole": 0,
        "attachattempts": 11,
        "partitionidchanges": 1,
        "betterpartitionattachattempts": 0,
        "parentchanges": 4

    """

    counters = {}
    lines = output.split("\n")
    in_mle_section = False

    for line in lines:
        if "MLE Counters:" in line:
            in_mle_section = True
            continue
        if not in_mle_section:
            continue

        # End of MLE Counters section
        if (
            line.strip()
            and not line.startswith(" ")
            and not any(x in line for x in ["Role", "Attempts", "Changes"])
        ):
            if "Counters" not in line and "Time" not in line:
                break

        # Parse counter lines
        if ":" in line and line.startswith(" "):
            parts = line.strip().split(":")
            if len(parts) == 2:
                key = parts[0].strip().lower().replace(" ", "_")
                try:
                    value = int(parts[1].strip())
                    counters[key] = value
                except ValueError:
                    pass

    # Enhance MLE counters with totals
    if counters:
        counters["totalparentpartitionchanges"] = (
            counters.get("parentchanges", 0)
            + counters.get("betterpartitionattachattempts", 0)
            + counters.get("partitionidchanges", 0)
        )

    return counters


def parse_time_statistics(output):
    """Extracts time statistics from diagnostic output."""
    time_stats = {}
    lines = output.split("\n")

    for line in lines:
        if "TrackedTime:" in line:
            match = re.search(r"TrackedTime:\s*(\d+)", line)
            if match:
                time_stats["tracked_time"] = int(match.group(1))
        elif "DisabledTime:" in line:
            match = re.search(r"DisabledTime:\s*(\d+)", line)
            if match:
                time_stats["disabled_time"] = int(match.group(1))
        elif "DetachedTime:" in line:
            match = re.search(r"DetachedTime:\s*(\d+)", line)
            if match:
                time_stats["detached_time"] = int(match.group(1))
        elif "ChildTime:" in line:
            match = re.search(r"ChildTime:\s*(\d+)", line)
            if match:
                time_stats["child_time"] = int(match.group(1))
        elif "RouterTime:" in line:
            match = re.search(r"RouterTime:\s*(\d+)", line)
            if match:
                time_stats["router_time"] = int(match.group(1))
        elif "LeaderTime:" in line:
            match = re.search(r"LeaderTime:\s*(\d+)", line)
            if match:
                time_stats["leader_time"] = int(match.group(1))

    if time_stats:
        tracked_time = time_stats.get("tracked_time", 0)
        if tracked_time > 0:
            # Combine detached and disabled time for overall "non-connected" time
            detached_disabled_time = time_stats.get("detached_time", 0) + time_stats.get("disabled_time", 0)
            time_stats["detached_disabled_time"] = detached_disabled_time

            detached_disabled_time_pct = round((detached_disabled_time / tracked_time) * 100, 1)
            time_stats["detached_disabled_pct"] = detached_disabled_time_pct

            # Calculate percentages for each role time relative to tracked time
            # format the percentages to 1 decimal place when printing
            time_stats["router_pct"] = round(
                (time_stats.get("router_time", 0) / tracked_time) * 100, 1
            )
            time_stats["child_pct"] = round(
                (time_stats.get("child_time", 0) / tracked_time) * 100, 1
            )
            time_stats["leader_pct"] = round(
                (time_stats.get("leader_time", 0) / tracked_time) * 100, 1
            )
            time_stats["disabled_pct"] = round(
                (time_stats.get("disabled_time", 0) / tracked_time) * 100, 1
            )
            time_stats["detached_pct"] = round(
                (time_stats.get("detached_time", 0) / tracked_time) * 100, 1
            )
            time_stats["detached_disabled_pct"] = round(
                (time_stats.get("detached_disabled_time", 0) / tracked_time) * 100, 1
            )

    return time_stats


def parse_multicast_diag_output(output: str, extaddr_map: dict | None = None) -> dict:
    """
    Parses multicast network diagnostic output containing responses from multiple devices.

    Multicast commands (ot-ctl networkdiagnostic get ff03::1/ff02::1 ...) return a single
    combined output with multiple device responses. Each response begins with:
        DIAG_GET.rsp/ans from <responder-ipv6>: <hex-data>
    Followed by parsed fields (Ext Address, Rloc16, Mode, IP6 Address List, etc.).

    This function splits the output into per-device blocks and parses each using existing
    parse functions (parse_mode_flags, parse_ipv6_address_list, parse_child_table, etc.).

    Args:
        output: Raw multicast diagnostic output string
        extaddr_map: Optional dict mapping extended addresses to device labels

    Returns:
        Dict keyed by extaddr (16-char hex string), with device records as values.
        Each record contains:
        {
            "extaddr": str,               # from TLV 0, used as dict key
            "rloc16": str,                # from TLV 1, e.g. "0x2000"
            # from extaddr_map or f"Unknown-{rloc16}"
            "device_label": str,
            "thread_stack_version": str,  # from TLV 28 or "Unknown"
            "mode": dict,                 # from parse_mode_flags()
            "ipv6_addrs": list,           # from parse_ipv6_address_list()
            "responder_ipv6": str,        # IPv6 from DIAG_GET.rsp header
            "children": list,             # from parse_child_table() if present
            "mac_counters": dict,         # from parse_mac_counters() if present
            "mle_counters": dict,         # from parse_mle_counters() if present
            "time_statistics": dict,      # from parse_time_statistics() if present
        }
    """
    if extaddr_map is None:
        extaddr_map = {}

    result = {}

    # Split output by response marker, discarding the first element (preamble)
    blocks = output.split("DIAG_GET.rsp/ans from ")
    blocks = blocks[1:]  # Discard preamble

    for block in blocks:
        if not block.strip():
            continue

        # Split on first newline to extract responder IPv6
        lines = block.split("\n", 1)
        if not lines:
            continue

        # Extract responder IPv6 from first line (format: "<ipv6>: <hex-data>")
        first_line = lines[0]
        responder_ipv6 = ""
        if ": " in first_line:
            responder_ipv6 = first_line.split(": ")[0].strip()

        # Extract Ext Address (TLV 0) - required field
        extaddr_match = re.search(r"Ext Address:\s*([0-9a-fA-F]{16})", block)
        if not extaddr_match:
            logging.warning(
                f"Malformed multicast response block (no Ext Address): {block[:100]}...")
            continue

        extaddr = extaddr_match.group(1).lower()

        # Extract Rloc16 (TLV 1)
        rloc16_match = re.search(r"Rloc16:\s*(0x[0-9a-fA-F]{4})", block)
        rloc16 = rloc16_match.group(1) if rloc16_match else "Unknown"

        # Extract Thread Stack Version (TLV 28)
        thread_version_match = re.search(
            r"Thread Stack Version:\s*(.+?)(?:\n|$)", block)
        thread_stack_version = thread_version_match.group(
            1).strip() if thread_version_match else "Unknown"

        # Resolve device label from extaddr_map
        device_label = extaddr_map.get(extaddr, f"Unknown-{rloc16}")

        # Parse mode flags and IPv6 addresses (always present in request)
        mode = parse_mode_flags(block)
        ipv6_addrs = parse_ipv6_address_list(block)

        # Parse optional TLV data (may be present depending on response)
        children = parse_child_table(block, rloc16)
        mac_counters = parse_mac_counters(block)
        mle_counters = parse_mle_counters(block)
        time_statistics = parse_time_statistics(block)

        # Build device record
        device_record = {
            "extaddr": extaddr,
            "rloc16": rloc16,
            "device_label": device_label,
            "thread_stack_version": thread_stack_version,
            "mode": mode,
            "ipv6_addrs": ipv6_addrs,
            "responder_ipv6": responder_ipv6,
            "children": children,
            "total_children": len(children),
            "mac_counters": mac_counters,
            "mle_counters": mle_counters,
            "time_statistics": time_statistics,
        }

        # Store in result dict, keyed by extaddr (last duplicate wins for now)
        result[extaddr] = device_record

    logging.info(f"Parsed {len(result)} unique devices from multicast output")
    return result


def merge_device_record(existing: dict, new: dict) -> dict:
    """
    Merges a newer device record into an existing one, preserving the most complete information.

    Used when the same device responds to multiple multicast retries with different TLV data.
    This function applies field-by-field merge rules to combine responses intelligently.

    Args:
        existing: The existing device record to merge into (mutated in place)
        new: The new device record to merge from

    Returns:
        The updated existing dict (mutated and also returned)

    Merge rules (field by field):
        - extaddr: Keep existing (should be identical, it's the key)
        - rloc16: Keep existing if not "Unknown", else take new
        - device_label: Keep existing if not starting with "Unknown-", else take new
        - tlv_values: Take new if new is non-empty dict and existing is empty, else keep existing
        - thread_stack_version: Keep existing if not "Unknown", else take new
        - mode: Take new if new mode is non-empty and existing is empty, else keep existing
        - ipv6_addrs: Union: merge lists, deduplicate preserving order
        - responder_ipv6: Keep existing (first responder wins)
        - children: Take new if new is non-empty list and existing is empty, else keep existing
        - mac_counters: Take new if new is non-empty dict and existing is empty, else keep existing
        - mle_counters: Take new if new is non-empty dict and existing is empty, else keep existing
        - time_statistics: Take new if new is non-empty dict and existing is empty, else keep existing
    """
    # extaddr: keep existing (it's the key, should be identical)
    # (no update needed)

    # rloc16: keep existing if not "Unknown", else take new
    if existing.get("rloc16") == "Unknown" and new.get("rloc16") != "Unknown":
        existing["rloc16"] = new["rloc16"]

    # device_label: keep existing if not starting with "Unknown-", else take new
    if existing.get("device_label", "").startswith("Unknown-") and not new.get("device_label", "").startswith("Unknown-"):
        existing["device_label"] = new["device_label"]

    # tlv_values: take new if new is non-empty dict and existing is empty, else keep existing
    if not existing.get("tlv_values") and new.get("tlv_values"):
        existing["tlv_values"] = new["tlv_values"]

    # thread_stack_version: keep existing if not "Unknown", else take new
    if existing.get("thread_stack_version") == "Unknown" and new.get("thread_stack_version") != "Unknown":
        existing["thread_stack_version"] = new["thread_stack_version"]

    # mode: take new if new mode is non-empty dict and existing is empty, else keep existing
    if not existing.get("mode") and new.get("mode"):
        existing["mode"] = new["mode"]

    # ipv6_addrs: union merge, deduplicate preserving order
    if existing.get("ipv6_addrs") and new.get("ipv6_addrs"):
        # Merge lists, deduplicate while preserving order
        seen = set(existing["ipv6_addrs"])
        for addr in new["ipv6_addrs"]:
            if addr not in seen:
                existing["ipv6_addrs"].append(addr)
                seen.add(addr)
    elif new.get("ipv6_addrs"):
        existing["ipv6_addrs"] = new["ipv6_addrs"]

    # responder_ipv6: keep existing (first responder wins)
    # (no update needed)

    # children: take new if new is non-empty list and existing is empty list
    if not existing.get("children") and new.get("children"):
        existing["children"] = new["children"]
        existing["total_children"] = len(existing["children"])

    # mac_counters: take new if new is non-empty dict and existing is empty
    if not existing.get("mac_counters") and new.get("mac_counters"):
        existing["mac_counters"] = new["mac_counters"]

    # mle_counters: take new if new is non-empty dict and existing is empty
    if not existing.get("mle_counters") and new.get("mle_counters"):
        existing["mle_counters"] = new["mle_counters"]

    # time_statistics: take new if new is non-empty dict and existing is empty
    if not existing.get("time_statistics") and new.get("time_statistics"):
        existing["time_statistics"] = new["time_statistics"]

    return existing


def get_tlv_values_for_detail_level(tlv_detail_level: int) -> str:
    """
    Maps a detail level to the appropriate TLV values string for network diagnostics.

    Args:
        tlv_detail_level: Detail level (6=DETAILED, 5=MEDIUM, 4/3/2/1=SIMPLE, etc.)
                         Levels 6-4 are for routers, 3-1 are for child devices.

    Returns:
        TLV values string (space-separated TLV numbers)
    """
    match tlv_detail_level:
        # ROUTER TLV sets
        case 6:
            return TLV_VALUES_DETAILED
        case 5:
            return TLV_VALUES_MEDIUM
        case 4:
            return TLV_VALUES_SIMPLE
        # CHILD TLV sets
        case 3:
            return TLV_VALUES_CHILD_DETAILED
        case 2:
            return TLV_VALUES_CHILD_MEDIUM
        case 1:
            return TLV_VALUES_CHILD_SIMPLE
        case _:
            return TLV_VALUES_SIMPLE


def fetch_network_diag_for_device(
    rloc, ipv6_rloc_prefix, extaddr_map=None, ipv6_addresses=None, tlv_detail_level=6
):
    """
    Queries and parses network diagnostic data for a single router.

    Args:
        rloc: RLOC16 value for the router (e.g., "0x0400")
        ipv6_rloc_prefix: IPv6 prefix for building RLOC IPv6 address
        extaddr_map: Dictionary mapping extended addresses to node names
        ipv6_addresses: Dictionary of IPv6 addresses by RLOC

    Returns:
        Dictionary containing parsed diagnostic data for the router, or None if extaddr is not found
    """
    if extaddr_map is None:
        extaddr_map = {}
    if ipv6_addresses is None:
        ipv6_addresses = {}

    rloc_hex = util_network.strip_rloc16_hex_prefix(rloc)
    ipv6_rloc_addr = util_network.build_rloc16_ipv6_address(
        ipv6_rloc_prefix, rloc_hex
    )

    # Get TLV values for the requested detail level
    tlv_values = get_tlv_values_for_detail_level(tlv_detail_level)

    # Query each router for its TLV fields: Ext Addr, RLOC16, Thread Stack Version,
    # IPv6 Address List, Child Table, MAC Counters, MLE Counters, Time Statistics
    output = util_ot_ctl.exec_ot_ctl(
        f"networkdiagnostic get {ipv6_rloc_addr} {tlv_values}"
    )
    logging.debug(
        f"Diagnostic for RLOC {rloc} (IPv6: {ipv6_rloc_addr}):\n{output}\n")

    # Extract Ext Address (TLV 0)
    extaddr_match = re.search(r"Ext Address: ([0-9a-fA-F]{16})", output)

    # If extaddr is not found, return None (caller will handle with default values)
    if not extaddr_match:
        return None

    # Try resolve device_label from extaddr_map, if not found use "Unknown-{rloc}"
    device_label = extaddr_map.get(extaddr_match.group(1))
    if not device_label:
        device_label = f"Unknown-{rloc}"

    # Extract Rloc16 (TLV 1)
    rloc16 = re.search(r"Rloc16: (0x[0-9a-fA-F]{4})", output)

    # Extract Thread Stack Version (TLV 28)
    thread_version = re.search(r"Thread Stack Version: (.+?)(?:\n|$)", output)

    # Parse detailed structures
    mode_flags = parse_mode_flags(output)
    ipv6_list = parse_ipv6_address_list(output)
    children = parse_child_table(output, rloc)
    mac_counters = parse_mac_counters(output)
    mle_counters = parse_mle_counters(output)
    time_stats = parse_time_statistics(output)

    network_topology_node = {
        "extaddr": extaddr_match.group(1) if extaddr_match else "Unknown",
        "rloc16": rloc16.group(1) if rloc16 else rloc,
        "device_label": device_label,
        "tlv_values": tlv_values,
        "thread_stack_version": thread_version.group(1).strip()
        if thread_version
        else "Unknown",
        "mode": mode_flags,
        "ipv6_addrs": ipv6_list if ipv6_list else ipv6_addresses.get(rloc, []),
        "children": children,
        "mac_counters": mac_counters,
        "mle_counters": mle_counters,
        "time_statistics": time_stats,
    }

    return network_topology_node


def fetch_network_diag_multicast(
    multicast_addr: str,
    extaddr_map: dict | None = None,
    network_dataset_info: dict | None = None,
) -> dict:
    """
    Queries network diagnostic data via multicast with retry and merge strategy.

    Sends networkdiagnostic queries to all devices on a multicast address (ff03::1 for
    all mesh devices or ff02::1 for immediate neighbors). Retries with progressively
    simpler TLV sets to maximize device responses, merging results to get the most
    complete information across all retries.

    Args:
        multicast_addr: Multicast address to target ("ff03::1" or "ff02::1")
        extaddr_map: Optional dict mapping extended addresses to device labels
        network_dataset_info: Optional dict with network info (contains OMR prefix)

    Returns:
        Dict keyed by rloc16, with device records as values (same format as
        fetch_network_diag_topology output). Each record includes consolidated
        data from all retry attempts.
    """
    if extaddr_map is None:
        extaddr_map = {}

    # Extract OMR prefix if available
    omr_ipv6addr_prefix = (
        network_dataset_info["prefix_omr_ipv6addr_prefix"]
        if network_dataset_info and "prefix_omr_ipv6addr_prefix" in network_dataset_info
        else None
    )

    # 3 attempts gives {DETAILED, MEDIUM, SIMPLE}, 2 attempts gives {DETAILED, MEDIUM}, 1 attempt gives {DETAILED}
    retries = 2
    delay_start = 0.1  # between retries 0.10 0.20 0.50 1.0 1.5 1.75 2.0 seconds
    tlv_detail_level = 6
    consolidated = {}  # Keyed by extaddr during collection

    # Retry loop with progressively simpler TLV sets
    for retry_idx in range(retries):
        # Get TLV values for current detail level
        tlv_values = get_tlv_values_for_detail_level(tlv_detail_level)

        logging.info(
            f"Multicast attempt {retry_idx + 1}/{retries} to {multicast_addr} "
            f"(TLV level {tlv_detail_level}): {tlv_values}"
        )

        # Execute multicast query
        output = util_ot_ctl.exec_ot_ctl(
            f"networkdiagnostic get {multicast_addr} {tlv_values}"
        )
        logging.debug(
            f"[DEBUG] Multicast output (attempt {retry_idx + 1}):\n{output}\n")

        # Parse multicast output
        parsed = parse_multicast_diag_output(output, extaddr_map)

        # Merge results into consolidated dict (keyed by extaddr)
        for device_record in parsed.values():
            extaddr = device_record["extaddr"]
            # Add TLV set info to record
            device_record["tlv_values"] = tlv_values
            if extaddr in consolidated:
                merge_device_record(consolidated[extaddr], device_record)
            else:
                consolidated[extaddr] = device_record

        logging.info(
            f"Multicast attempt {retry_idx + 1}: {len(parsed)} responses, "
            f"{len(consolidated)} unique devices so far"
        )

        # Sleep before next retry (but not after the last retry)
        if retry_idx < retries - 1:
            tlv_detail_level = max(1, tlv_detail_level - 1)  # Floor at 1

            r_delay = delay_start
            time.sleep(r_delay)

    # Finalize the consolidated dict

    # Re-key by rloc16 and add type/omrIpv6Address fields
    result = {}
    for record in consolidated.values():
        rloc16 = record.get("rloc16", "Unknown")

        # Add OMR IPv6 address if prefix available
        if omr_ipv6addr_prefix:
            record["omrIpv6Address"] = util_network.find_omr_address_in_list(
                record.get("ipv6_addrs", []), omr_ipv6addr_prefix
            )
        else:
            record["omrIpv6Address"] = None

        # Add device type (multicast reaches routers primarily)
        # If rloc16 ends in 00 it's likely a router, if it ends in 01-ff it's likely a child, but since this is from multicast responses which are primarily from routers, we can default to "Router" for all records here. For more accurate type classification, we would need to analyze the mode flags or other TLV data, but for simplicity in this consolidated view, we can assume these are primarily router responses.
        if record.get("rloc16", "Unknown") != "Unknown":
            if record["rloc16"].lower().endswith("00"):
                record["type"] = "Router"
            else:
                record["type"] = "Child"
        else:
            record["type"] = "Unknown"

        # Store in result, keyed by rloc16
        result[rloc16] = record

    logging.info(
        f"Multicast consolidation complete: {len(result)} devices (keyed by rloc16)"
    )
    return result


def fetch_network_diag_topology_multicast_network(
    extaddr_map: dict | None = None,
    network_dataset_info: dict | None = None,
) -> dict:
    """
    Queries network diagnostic data via multicast to all Thread devices in the mesh (ff03::1).

    This is a thin wrapper around fetch_network_diag_multicast() that targets the
    all-thread-devices multicast address, allowing discovery of the entire mesh network.

    Args:
        extaddr_map: Optional dict mapping extended addresses to device labels
        network_dataset_info: Optional dict with network info (contains OMR prefix)

    Returns:
        Dict keyed by rloc16 with device records from all mesh devices
    """
    return fetch_network_diag_multicast(
        multicast_addr="ff03::1",
        extaddr_map=extaddr_map,
        network_dataset_info=network_dataset_info,
    )


def fetch_network_diag_topology_multicast_neighbors(
    extaddr_map: dict | None = None,
    network_dataset_info: dict | None = None,
) -> dict:
    """
    Queries network diagnostic data via multicast to immediate one-hop neighbors (ff02::1).

    This is a thin wrapper around fetch_network_diag_multicast() that targets the
    link-local multicast address, allowing discovery of only immediate neighbors
    reachable in one hop from the querying device.

    Args:
        extaddr_map: Optional dict mapping extended addresses to device labels
        network_dataset_info: Optional dict with network info (contains OMR prefix)

    Returns:
        Dict keyed by rloc16 with device records from immediate one-hop neighbors
    """
    return fetch_network_diag_multicast(
        multicast_addr="ff02::1",
        extaddr_map=extaddr_map,
        network_dataset_info=network_dataset_info,
    )


def fetch_network_diag_topology(
    extaddr_map=None, network_dataset_info=None, expand_children=True
):
    """Maps the full network topology and returns a Python dictionary."""

    # expand_children controls whether to perform additional queries for each router to get their child table data and include that in the topology map. This can provide a more complete view of the network with parent-child relationships, but it also significantly increases the number of queries and overall runtime, especially in larger networks with many routers and children. By default, it's set to True to get the most detailed topology map, but it can be set to False to only get the parent nodes without expanding children for a faster but less detailed topology mapping.
    # Set to True to also query and include child nodes in the topology map (will increase runtime significantly)
    # Set to False to only get parent nodes without expanding children

    # 1. Initialize topology map
    network_topology_map = {}

    # 2. Extract OMR prefix
    omr_ipv6addr_prefix = (
        network_dataset_info["prefix_omr_ipv6addr_prefix"]
        if network_dataset_info and "prefix_omr_ipv6addr_prefix" in network_dataset_info
        else None
    )

    # 3. Get mesh-local prefix
    meshlocal_prefix = util_network.fetch_meshlocal_prefix()
    ipv6_rloc_prefix = util_network.build_rloc_ipv6_address_prefix(
        meshlocal_prefix
    )

    # 4. Get all active routers (potential parents)
    router_table_data = fetch_and_parse_router_table(extaddr_map)
    router_rlocs = [
        router.get("rloc16") for router in router_table_data if router.get("rloc16")
    ]

    # 5. Get IPv6 addresses for all routers
    # need this if nodes don't reponse to networkdiagnostic get with TLV 8 for IPv6 address list, then we can at least populate the topology map with known IPv6 addresses for each RLOC16 from this separate query. This way we can still have some reference to IPv6 addresses in the topology even if some nodes don't respond to the full diagnostic query.
    ipv6_addresses = fetch_ipv6_addresses()
    ipv6_addresses = (
        ipv6_addresses if ipv6_addresses else {}
    )  # Ensure it's a dict even if empty

    # 6. Get the multicast topology data
    # This will give us a starting point with data from all devices that responded to the multicast query, which we can then enrich with additional direct queries for any missing data or child information as needed. The multicast query can help reduce the number of direct queries needed by providing data for many devices in one go, especially for those that respond with more detailed TLV sets in the initial retries.
    network_topology_map_multicast = fetch_network_diag_topology_multicast_network(
        extaddr_map, network_dataset_info
    )

    if network_topology_map_multicast:
        logging.info(
            f"Multicast topology map has {len(network_topology_map_multicast)} devices (keyed by rloc16)"
        )
        # Merge multicast topology data into main topology map, keyed by rloc16
        for rloc16, device_record in network_topology_map_multicast.items():
            if rloc16 in network_topology_map:
                merge_device_record(
                    network_topology_map[rloc16], device_record)
            else:
                network_topology_map[rloc16] = device_record
        logging.info(
            f"After merging multicast data, topology map has {len(network_topology_map)} devices (keyed by rloc16)"
        )
    else:
        logging.warning("Multicast topology map is empty or None")

    # 7. Loop through each router RLOC16 and query for its diagnostic data, then add to topology map. We can also check if we already have data for this RLOC16 from the multicast query before doing the direct query, and if so we can skip the direct query and just use the existing data to populate the topology map for this node. This way we can avoid unnecessary queries for nodes that already responded to the multicast request, which can help reduce overall runtime and network load. If we don't have data for this RLOC16 from the multicast query, then we proceed with the direct query with retries to try to get the data for this node.
    # Inner child loop also handles children and build a more complete topology map with parent-child relationships instead of just a flat map of RLOC16 to data. This way we can represent the full tree structure of the network instead of just a list of nodes.

    for rloc16 in router_rlocs:
        # Retry logic for networkdiagnostic get in case of transient errors or unresponsive nodes, retry N times with some delay before giving up and adding with default values
        # 3 attempts gives {DETAILED, MEDIUM, SIMPLE}, 2 attempts gives {DETAILED, MEDIUM}, 1 attempt gives {DETAILED}
        retries = 2
        delay_start = 0.1  # seconds

        # Initialize
        network_topology_node = None

        # Check if we already have data for this RLOC16 from the multicast query, if so skip the direct query and use the existing data to populate the topology map. This way we can avoid unnecessary queries for nodes that already responded to the multicast request, which can help reduce overall runtime and network load. If we don't have data for this RLOC16 from the multicast query, then we proceed with the direct query with retries to try to get the data for this node.
        record_exists = False
        if rloc16 in network_topology_map:
            record_exists = True
            # We already have data for this RLOC16 from the multicast query, we can skip the direct query
            # and use the existing data to populate the topology map. This way we can avoid unnecessary queries
            # for nodes that already responded to the multicast request, which can help reduce overall runtime
            # and network load. If we don't have data for this RLOC16 from the multicast query, then we proceed
            # with the direct query with retries to try to get the data for this node.
            network_topology_node = network_topology_map[rloc16]
            logging.info(
                f"RLOC16 {rloc16} already has data from multicast query, skipping direct query."
            )

        # Skip the retries but still check if we need to expand children for this node if expand_children is True, since the multicast query might not have included the child table data for this node if it was using a simpler TLV set. So we can still enrich the existing node data with child information if needed by doing a direct query just for the child table TLV, but we can skip the full diagnostic query with all TLVs since we already have that data from the multicast response.
        if (not record_exists):
            # Start with ROUTER TLV_VALUES_DETAILED for first attempt
            tlv_detail_level = 6

            for r in range(retries):
                # On last retries, try with simpler TLV set in case detailed one is causing issues
                if r == retries - 2:
                    tlv_detail_level = 5
                logging.info(
                    f"Router Node {rloc16} not found after {r} attempts, trying with tlv_detail_level {tlv_detail_level} {get_tlv_values_for_detail_level(tlv_detail_level)} TLV set."
                )

            if r == retries - 1:
                tlv_detail_level = 4
                logging.info(
                    f"Router Node {rloc16} not found after {r} attempts, trying with tlv_detail_level {tlv_detail_level} {get_tlv_values_for_detail_level(tlv_detail_level)} TLV set."
                )

            network_topology_node = fetch_network_diag_for_device(
                rloc16, ipv6_rloc_prefix, extaddr_map, ipv6_addresses, tlv_detail_level
            )
            if network_topology_node is not None:
                break
            logging.info(
                f"Router Node {rloc16} not found, retrying in {delay_start} seconds..."
            )
            # if last iteration skip sleep to avoid unnecessary delay before giving up and adding with default values
            if r < retries - 1:
                # Increase delay with each retry
                l_delay = delay_start * (r + 1)
                logging.info(
                    f"Waiting for {l_delay} seconds before next retry...{r + 1} of {retries}")
                time.sleep(l_delay)

        if network_topology_node is None:
            # extaddr not found, use default values
            network_topology_map[rloc16] = {
                "extaddr": f"Unknown-{rloc16}",
                "rloc16": rloc16,
                "device_label": f"Unknown-{rloc16}",
                "thread_stack_version": "Unknown",
                "mode": {},
                "ipv6_addrs": ipv6_addresses.get(rloc16, []),
                "omrIpv6Address": util_network.find_omr_address_in_list(
                    ipv6_addresses.get(rloc16, []), omr_ipv6addr_prefix
                )
                if omr_ipv6addr_prefix
                else None,
                "children": [],
                "type": "Unknown-Router",
                "mac_counters": {},
                "mle_counters": {},
                "time_statistics": {},
            }
        else:
            network_topology_node["type"] = "Router"
            if omr_ipv6addr_prefix:
                network_topology_node["omrIpv6Address"] = (
                    util_network.find_omr_address_in_list(
                        network_topology_node.get(
                            "ipv6_addrs", []), omr_ipv6addr_prefix
                    )
                )
            # Merge with existing data in topology map if present (e.g. from multicast query) to enrich the node data with any missing fields that we couldn't get from the direct query due to unresponsive node or TLV issues, this way we can have the most complete data possible for each node by combining the results from both the multicast and direct queries, and we can also handle cases where some nodes might only respond to one of the query types but not the other.
            if rloc16 in network_topology_map:
                merge_device_record(
                    network_topology_map[rloc16], network_topology_node)
            else:
                # If we don't already have data for this RLOC16 in the topology map, add it now. If we do have
                # existing data (e.g. from multicast), we will have already merged the new data into the existing
                # record, so we don't need to add it again.
                network_topology_map[rloc16] = network_topology_node

                logging.info(
                    f"Added router node {rloc16} {network_topology_node.get('extaddr', 'Unknown')} {network_topology_node.get('device_label', 'Unknown')} to topology map. {r+1}/{retries} attempts.  TLV detail level: {tlv_detail_level} {get_tlv_values_for_detail_level(tlv_detail_level)}"
                )
                logging.info(
                    f"Poll {len(network_topology_map)} unique devices so far"
                )

            if expand_children:
                # 8. Expand child nodes in topology:
                # - If expand_children is True, loop through child nodes from this router's child table
                # - Query each child's diagnostic data and add to topology map with parent-child relationships
                # - Tradeoff: More complete topology but significantly more queries/runtime (especially in large networks)
                # - Implement retry logic for child node queries similar to parent router logic
                # - Gather RLOC16 values from child table and perform direct queries for each
                # - Result: Topology map shows parent-child relationships instead of flat RLOC16-only map

                children_rlocs = [
                    child.get("rloc16")
                    for child in network_topology_node.get("children", [])
                    if child.get("rloc16")
                ]
                for child_rloc in children_rlocs:
                    # Check if child RLOC16 is already in topology map (e.g. from multicast query), 
                    # if so skip the direct query and use the existing data to populate the topology map 
                    # for this child node. This way we can avoid unnecessary queries for child nodes that 
                    # already responded to the multicast request, which can help reduce overall runtime and 
                    # network load. If we don't have data for this child RLOC16 from the multicast query, then 
                    # we proceed with the direct query with retries to try to get the data for this child node.

                    if child_rloc not in network_topology_map:
                        # If child_node returns none, retry N times with some delay
                        # in case the child sleeping (5 seconds), is not fully attached or responsive yet,
                        # otherwise add with default values

                        child_retries = 5  # number of retries

                        child_delay_max = 2.0  # max delay between retries
                        child_delay_start = 0.25  # seconds 0.25 0.5 1.0 2.0 seconds

                        # Child TLV strategy - progressively simplify to maximize response rate:
                        # - Start with detailed TLV (includes child table, IPv6 list); may not respond to simpler sets
                        # - Fall back to simpler TLV if detailed responses fail; still get basic node info
                        # - Maximize response chances while attempting to maximize detail level
                        child_tlv_detail_level = 3

                        for cr in range(child_retries):
                            # On last retries, try with simpler TLV set in case detailed one is causing issues

                            if cr == child_retries - 3:
                                # MEDIUM
                                child_tlv_detail_level = 2
                                logging.info(
                                    f"Child node {child_rloc} not found after {cr} attempts, trying with tlv_detail_level {child_tlv_detail_level} {get_tlv_values_for_detail_level(child_tlv_detail_level)} medium detail TLV set."
                                )

                            if cr == child_retries - 2:
                                # SIMPLE
                                child_tlv_detail_level = 1
                                logging.info(
                                    f"Child node {child_rloc} not found after {cr} attempts, trying with tlv_detail_level {child_tlv_detail_level} {get_tlv_values_for_detail_level(child_tlv_detail_level)} simple detail TLV set."
                                )

                            if cr == child_retries - 1:
                                # SIMPLE
                                child_tlv_detail_level = 1
                                logging.info(
                                    f"Child node {child_rloc} not found after {cr} attempts, trying with tlv_detail_level {child_tlv_detail_level} {get_tlv_values_for_detail_level(child_tlv_detail_level)} simple detail TLV set."
                                )

                            child_node = fetch_network_diag_for_device(
                                child_rloc,
                                ipv6_rloc_prefix,
                                extaddr_map,
                                ipv6_addresses,
                                child_tlv_detail_level,
                            )
                            if child_node is not None:
                                child_node["type"] = "Child"
                                break
                            logging.info(
                                f"Child node {child_rloc} not found, retrying in {child_delay_start} seconds..."
                            )
                            if cr < child_retries - 1:
                                # Increase delay with each retry
                                c_delay = child_delay_start * (cr + 1)
                                c_delay = min(c_delay, child_delay_max)
                                time.sleep(c_delay)

                        if child_node is None:
                            network_topology_map[child_rloc] = {
                                "extaddr": f"Unknown-{child_rloc}",
                                "rloc16": child_rloc,
                                "device_label": f"Unknown-{child_rloc}",
                                "thread_stack_version": "Unknown",
                                "mode": {},
                                "ipv6_addrs": ipv6_addresses.get(child_rloc, []),
                                "children": [],
                                "omrIpv6Address": util_network.find_omr_address_in_list(
                                    ipv6_addresses.get(child_rloc, []),
                                    omr_ipv6addr_prefix,
                                )
                                if omr_ipv6addr_prefix
                                else None,
                                "type": "Unknown-Child",
                                "mac_counters": {},
                                "mle_counters": {},
                                "time_statistics": {},
                            }

                        else:
                            child_node["omrIpv6Address"] = (
                                util_network.find_omr_address_in_list(
                                    child_node.get("ipv6_addrs", []),
                                    omr_ipv6addr_prefix,
                                )
                                if omr_ipv6addr_prefix
                                else None
                            )
                            network_topology_map[child_rloc] = child_node
                            # logging.info(
                            #    f"Added child node {child_rloc} {child_node.get('extaddr', 'Unknown')} {child_node.get('device_label', 'Unknown')} to topology map. {r}/{retries} attempts.  TLV detail level: {tlv_detail_level}"
                            # )
                            logging.info(
                                f"Added child node {child_rloc} {child_node.get('extaddr', 'Unknown')} {child_node.get('device_label', 'Unknown')} under parent {rloc16} {network_topology_node.get('extaddr', 'Unknown')} {network_topology_node.get('device_label', 'Unknown')} to topology map. {cr+1}/{child_retries} attempts.  TLV detail level: {child_tlv_detail_level} {get_tlv_values_for_detail_level(child_tlv_detail_level)}"
                            )
                            logging.info(
                                f"Poll Child {len(network_topology_map)} unique devices so far"
                            )

    logging.info(
        f"Poll consolidation complete: {len(network_topology_map)} unique devices found in topology map."
    )

    return network_topology_map


def print_network_diag_topology(topology):
    """Prints the network topology to console in tree format."""
    logging.debug("\n--- Thread Network Topology ---\n")
    for rloc, data in topology.items():
        logging.debug(f"Parent [RLOC: {rloc}] (Ext: {data['extaddr']})")
        logging.debug(
            f"  Thread Stack Version: {data.get('thread_stack_version', 'Unknown')}"
        )

        if data.get("ipv6_addrs"):
            logging.debug(f"  IPv6 Addresses ({len(data['ipv6_addrs'])}):")
            for ipv6 in data["ipv6_addrs"]:
                logging.debug(f"    - {ipv6}")

        if data.get("omrIpv6Address"):
            logging.debug(f"  OMR IPv6 Address: {data['omrIpv6Address']}")

        if data.get("children"):
            logging.debug(f"  Children ({len(data['children'])}):")
            for child in data["children"]:
                logging.debug(
                    f"    - ID: {child['id']}, Timeout: {child.get('timeout')}, Link Quality: {child.get('link_quality')}"
                )
                if child.get("mode"):
                    mode = child["mode"]
                    logging.debug(
                        f"      Mode: RxOnWhenIdle={mode.get('rx_on_when_idle')}, DeviceType={mode.get('device_type')}, NetworkData={mode.get('network_data')}"
                    )
            logging.debug(
                f"    Total Children: {data.get('total_children', 0)}")

        if data.get("mac_counters"):
            logging.debug(f"  MAC Counters:")
            for key, value in sorted(data["mac_counters"].items()):
                logging.debug(f"    {key}: {value}")

        if data.get("mle_counters"):
            logging.debug(f"  MLE Counters:")
            for key, value in sorted(data["mle_counters"].items()):
                logging.debug(f"    {key}: {value}")

        if data.get("time_statistics"):
            logging.debug(f"  Time Statistics:")
            time_stats = data["time_statistics"]
            if time_stats:
                total_time = time_stats.get("tracked_time", 0)
                router_pct = (
                    (time_stats.get("router_time", 0) / total_time * 100)
                    if total_time > 0
                    else 0
                )
                child_pct = (
                    (time_stats.get("child_time", 0) / total_time * 100)
                    if total_time > 0
                    else 0
                )
                logging.debug(
                    f"    Tracked: {time_stats.get('tracked_time')}, Router: {time_stats.get('router_time')} ({router_pct:.1f}%), Child: {time_stats.get('child_time')} ({child_pct:.1f}%)"
                )
                logging.debug(
                    f"    Disabled: {time_stats.get('disabled_time')}, Detached: {time_stats.get('detached_time')}, Leader: {time_stats.get('leader_time')}"
                )

        logging.debug("")


def save_topology_to_json_dict(
    data, filename="td-otbr-cli-networkdiag-topology.json"
):
    """Serializes the dictionary to a pretty-printed JSON file."""
    save_json_atomic(data, filename)
    logging.info(f"Successfully exported {len(data)} records for topology to {filename}")


def save_topology_to_json_list(
    data, filename="thread-networkdiagnostic-topology-list.json"
):
    """Converts dict format to list format and saves to JSON."""
    network_map = []

    for rloc, data in data.items():
        # Set the order of priority fields in the output JSON for better readability, with key fields like rloc16, extaddr, device_label at the top, and then the more detailed fields like mode, ipv6_addrs, children, counters grouped together below. This way when looking at the JSON output, it's easier to quickly identify the key information about each node before diving into the more detailed data.
        network_node = {
            "rloc16": rloc,
            "extaddr": data["extaddr"],
            "device_label": data.get("device_label", f"Unknown-{rloc}"),
            "tlv_values": data.get("tlv_values", []),
            "thread_stack_version": data.get("thread_stack_version", "Unknown"),
            "mode": data.get("mode", {}),
            "ipv6_addrs": data.get("ipv6_addrs", []),
            "omrIpv6Address": data.get("omrIpv6Address"),
            "type": data.get("type", "Unknown"),
            "children": data.get("children", []),
            "total_children": data.get("total_children", 0),
            "mac_counters": data.get("mac_counters", {}),
            "mle_counters": data.get("mle_counters", {}),
            "time_statistics": data.get("time_statistics", {}),
        }
        network_map.append(network_node)

    save_json_atomic(network_map, filename)
    logging.info(f"Successfully exported {len(network_map)} records for topology to {filename}")


def main_multicast_network(argv: Sequence[str] | None = None) -> int:
    """Entry point for topology-multicast-network subcommand (ff03::1)."""

    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    logging.info(
        "Initiating Thread Network Topology Scan (Multicast Network)...\n")

    parser = argparse.ArgumentParser(
        description="Thread Network Diagnostic Topology – Multicast Network (ff03::1)"
    )
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    args = parser.parse_args(argv)
    td_data_dir = resolve_data_dir(datadir_arg=args.datadir)

    # Load extaddr to device label mapping from JSON file
    extaddr_json_filename = data_file_path(
        EXTADDR_DEVICE_LABEL_MAP_FILENAME, td_data_dir
    )
    if os.path.exists(extaddr_json_filename):
        extaddr_map = load_extaddr_device_label_map(extaddr_json_filename)
    else:
        extaddr_map = {}

    network_dataset_info = util_network.fetch_network_dataset_info()

    # Get the multicast topology data
    data = fetch_network_diag_topology_multicast_network(
        extaddr_map, network_dataset_info
    )

    # Print the topology in tree format to console
    print_network_diag_topology(data)

    # Save the topology as JSON to file
    save_json_filename = data_file_path(
        "td-otbr-cli-networkdiag-topology-multicast-network.json", td_data_dir
    )
    save_topology_to_json_list(data, save_json_filename)

    # Print the raw topology dictionary as JSON to console for debugging
    logging.debug(json.dumps(data, indent=4))

    return 0


def main_multicast_neighbors(argv: Sequence[str] | None = None) -> int:
    """Entry point for topology-multicast-neighbors subcommand (ff02::1)."""

    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    logging.info(
        "Initiating Thread Network Topology Scan (Multicast Neighbors)...\n")

    parser = argparse.ArgumentParser(
        description="Thread Network Diagnostic Topology – Multicast Neighbors (ff02::1)"
    )
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    args = parser.parse_args(argv)
    td_data_dir = resolve_data_dir(datadir_arg=args.datadir)

    # Load extaddr to device label mapping from JSON file
    extaddr_json_filename = data_file_path(
        EXTADDR_DEVICE_LABEL_MAP_FILENAME, td_data_dir
    )
    if os.path.exists(extaddr_json_filename):
        extaddr_map = load_extaddr_device_label_map(extaddr_json_filename)
    else:
        extaddr_map = {}

    network_dataset_info = util_network.fetch_network_dataset_info()

    # Get the multicast topology data
    data = fetch_network_diag_topology_multicast_neighbors(
        extaddr_map, network_dataset_info
    )

    # Print the topology in tree format to console
    logging.debug("Final multicast neighbors topology data structure:\n%s", json.dumps(
        data, indent=4))
    print_network_diag_topology(data)

    # Save the topology as JSON to file
    save_json_filename = data_file_path(
        "td-otbr-cli-networkdiag-topology-multicast-neighbors.json", td_data_dir
    )
    save_topology_to_json_list(data, save_json_filename)

    # Print the raw topology dictionary as JSON to console for debugging
    logging.debug("Raw multicast neighbors topology data as JSON:\n%s",
                  json.dumps(data, indent=4))

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Main entry point with optional command-line arguments."""

    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="Thread Network Diagnostic Topology")
    parser.add_argument("--datadir", default=None, help=TD_DATA_DIR_ARG_HELP)
    children_group = parser.add_mutually_exclusive_group()
    children_group.add_argument(
        "-c",
        "--children",
        dest="expand_children",
        action="store_true",
        default=True,
        help="Expand and include child nodes in the topology map (default)",
    )
    children_group.add_argument(
        "-cno",
        "--children-no",
        dest="expand_children",
        action="store_false",
        help="Do not expand child nodes in the topology map",
    )
    args = parser.parse_args(argv)
    td_data_dir = resolve_data_dir(datadir_arg=args.datadir)

    # Load extaddr to nodename mapping from JSON file
    extaddr_json_filename = data_file_path(
        EXTADDR_DEVICE_LABEL_MAP_FILENAME, td_data_dir
    )

    # Check if file exists before parsing
    if os.path.exists(extaddr_json_filename):
        extaddr_map = load_extaddr_device_label_map(extaddr_json_filename)
    else:
        extaddr_map = {}

    network_dataset_info = util_network.fetch_network_dataset_info()

    # Get the networkdiagnostic topology data
    networkdiagnostic_topology_data = fetch_network_diag_topology(
        extaddr_map, network_dataset_info, expand_children=args.expand_children
    )

    # print the topology in tree format to console
    print_network_diag_topology(networkdiagnostic_topology_data)

    # save the topology as JSON to file
    save_json_filename = data_file_path(
        "td-otbr-cli-networkdiag-topology.json", td_data_dir
    )
    save_topology_to_json_list(
        networkdiagnostic_topology_data, save_json_filename
    )

    # Print the raw topology dictionary as JSON to console for debugging
    logging.debug("Raw topology data as JSON:\n%s", json.dumps(
        networkdiagnostic_topology_data, indent=4))


if __name__ == "__main__":
    sys.exit(main())
