import os
import sys
import subprocess
import json
import logging
from typing import Sequence

from const import EXTADDR_DEVICE_LABEL_MAP_FILENAME
from extaddr_device_label_map import load_extaddr_device_label_map
import util_ot_ctl
from util_data import data_file_path, parse_datadir_from_argv, resolve_data_dir, save_json_atomic


def fetch_router_table():
    try:
        # Executes the command: ot-ctl router table
        output = util_ot_ctl.exec_ot_ctl("router table")
        logging.debug(f"[DEBUG] Output of 'ot-ctl router table':\n{output}\n")

        return output
    except subprocess.CalledProcessError as e:
        logging.error(f"Error running ot-ctl: {e}")
        raise
    except Exception as e:
        logging.error(f"Unexpected error running ot-ctl: {e}")
        raise


def parse_router_table(output, extaddr_map=None):
    """
    Parses the router table output into a list of router dictionaries.

    Expected format:
    | ID | RLOC16 | Next Hop | Path Cost | LQ In | LQ Out | Age | Extended MAC     | Link |
    +----+--------+----------+-----------+-------+--------+-----+------------------+------+
    |  1 | 0x0400 |       25 |         1 |     2 |      3 |  20 | 8e3b369df65e9496 |    1 |

    Args:
        output: Router table output text
        extaddr_map: Optional dictionary mapping extended MAC to node name

    Returns:
        List of router dictionaries

    Raises:
        TypeError: If output is not a string
    """
    if not isinstance(output, str):
        raise TypeError(
            f"Expected output to be a string, got {type(output).__name__}")

    routers = []
    if extaddr_map is None:
        extaddr_map = {}
    lines = output.strip().split("\n")

    # Find the header line (contains "ID" and "RLOC16")
    header_line = None
    header_idx = 0
    for i, line in enumerate(lines):
        if "ID" in line and "RLOC16" in line:
            header_line = line
            header_idx = i
            break

    if not header_line:
        return routers

    # Extract field names from the header line
    # Header format: "| ID | RLOC16 | Next Hop | Path Cost | LQ In | LQ Out | Age | Extended MAC     | Link |"
    field_names = [f.strip() for f in header_line.split("|")[1:-1]]

    # Parse data rows (skip header and separator lines)
    for line in lines[header_idx + 2:]:
        # Skip separator lines (lines starting with +)
        if line.startswith("+") or not line.strip():
            continue

        # Skip header-like lines
        if "ID" in line or "RLOC16" in line:
            continue

        # Split by pipe and extract values
        values = [v.strip() for v in line.split("|")[1:-1]]

        # Only process lines with the correct number of fields
        if len(values) == len(field_names):
            router = {}
            for field_name, value in zip(field_names, values):
                # Try to convert to int if it's a numeric field
                try:
                    if field_name in [
                        "ID",
                        "Path Cost",
                        "LQ In",
                        "LQ Out",
                        "Age",
                        "Link",
                    ]:
                        router[field_name] = int(value)
                    else:
                        # Conform RLOC16 key and value are stored in lowercase for consistent mapping
                        if field_name == "RLOC16":
                            router["rloc16"] = (
                                value.lower()
                            )  # Normalize RLOC16 to lowercase for consistent mapping
                        else:
                            router[field_name] = value
                except ValueError:
                    router[field_name] = value

            # Get device_label from extaddr_map if available
            ext_mac = router.get("Extended MAC", "").lower()
            # Normalize to extaddr field name
            if ext_mac:
                router["extaddr"] = ext_mac
            # Add device_label from extaddr_map if available
            if ext_mac and ext_mac in extaddr_map:
                router["device_label"] = extaddr_map[ext_mac]

            routers.append(router)
        else:
            if values:  # Skip blank separator rows silently
                logging.warning(
                    "router table: unexpected format, pattern did not match: %r", line
                )

    return routers


def fetch_and_parse_router_table(extaddr_map=None):
    """
    Retrieves and parses the thread router table data.

    Args:
        extaddr_map: Optional dictionary mapping extended MAC to node name

    Returns:
        List of router dictionaries with parsed data

    Raises:
        Exception: If retrieving or parsing router table fails
    """
    raw_output = fetch_router_table()
    if not raw_output:
        raise ValueError("Router table output is empty")
    return parse_router_table(raw_output, extaddr_map)


def main(argv: Sequence[str] | None = None) -> int:

    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )
    td_data_dir = resolve_data_dir(data_dir=parse_datadir_from_argv(argv))

    try:
        # Load extaddr to nodename mapping from JSON file
        extaddr_json_filename = data_file_path(
            EXTADDR_DEVICE_LABEL_MAP_FILENAME, td_data_dir
        )

        # Check if file exists before parsing
        if os.path.exists(extaddr_json_filename):
            logging.info(
                f"Loading extended address to node name mapping from {extaddr_json_filename}..."
            )
            extaddr_map = load_extaddr_device_label_map(
                extaddr_json_filename)
        else:
            extaddr_map = {}

        router_table_data = fetch_and_parse_router_table(extaddr_map)
        save_path = data_file_path(
            "td-otbr-cli-router-table.json", td_data_dir)
        save_json_atomic(router_table_data, save_path)
        logging.debug("Raw router table data as JSON:\n%s",
                      json.dumps(router_table_data, indent=4))

    except FileNotFoundError as e:
        logging.error(f"Error: File not found - {e}")
    except json.JSONDecodeError as e:
        logging.error(f"Error: Invalid JSON - {e}")
    except IOError as e:
        logging.error(f"Error: I/O error - {e}")
    except Exception as e:
        logging.error(f"Error: {e}")


if __name__ == "__main__":
    sys.exit(main())
