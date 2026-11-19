import json
import logging
import re
from typing import Any

from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME
from td_device_fields import EXT_ADDRESS_ALIASES, normalize_identifier_text


EXTADDR_FIELD_ALIASES = EXT_ADDRESS_ALIASES
_HISTORY_ADDRESS = re.compile(r"[0-9a-f]{16}")


def _include_previous_addresses(
    mapping: dict[str, str], rows: list[tuple[str, str, object]]
) -> None:
    owners: dict[str, tuple[str, str]] = {}
    ambiguous: set[str] = set()
    for primary, label, previous in rows:
        if not isinstance(previous, list):
            continue
        for value in previous:
            if not isinstance(value, str):
                continue
            address = normalize_extaddr(value)
            if address in mapping or not _HISTORY_ADDRESS.fullmatch(address):
                continue
            if address in owners and owners[address][0] != primary:
                ambiguous.add(address)
            owners[address] = (primary, label)
    mapping.update({address: label for address, (_, label) in owners.items()
                    if address not in ambiguous})


def normalize_extaddr(value: Any) -> str:
    """Normalize extaddr value to lowercase string.
    
    Args:
        value: Raw extaddr value (any type)
    
    Returns:
        Normalized extaddr (lowercase, stripped) or empty string if invalid.
    
    Examples:
        >>> normalize_extaddr("AA11BB22CC33DD44")
        "aa11bb22cc33dd44"
        
        >>> normalize_extaddr("  AA11BB22CC33DD44  ")
        "aa11bb22cc33dd44"
        
        >>> normalize_extaddr(None)
        ""
    """
    return normalize_identifier_text(value)


def get_extaddr_from_record(record: dict[str, Any], aliases: tuple[str, ...] = EXTADDR_FIELD_ALIASES) -> str:
    """Extract and normalize extaddr from record, checking multiple field aliases.
    
    Args:
        record: Dictionary containing extaddr data
        aliases: Tuple of field names to check (in order of priority)
    
    Returns:
        Normalized extaddr string or empty string if not found.
    
    Examples:
        >>> get_extaddr_from_record({"extaddr": "AA11BB22CC33DD44"})
        "aa11bb22cc33dd44"
        
        >>> get_extaddr_from_record({"extAddress": "AA11BB22CC33DD44"})
        "aa11bb22cc33dd44"
        
        >>> get_extaddr_from_record({"Extended MAC": "AA11BB22CC33DD44"})
        "aa11bb22cc33dd44"
    """
    for field_name in aliases:
        value = normalize_extaddr(record.get(field_name))
        if value:
            return value
    return ""


def load_extaddr_device_label_map_flexible(
    path: str,
    extaddr_aliases: tuple[str, ...] = EXTADDR_FIELD_ALIASES,
) -> dict[str, str]:
    """Load extaddr->device_label mapping from JSON file (flexible format).
    
    Supports both list and dict JSON formats, with flexible extaddr field names.
    This is the recommended loader for new code.
    
    Args:
        path: Path to JSON file containing extaddr mappings
        extaddr_aliases: Tuple of field names to check for extaddr (default: EXTADDR_FIELD_ALIASES)
    
    Returns:
        Dictionary mapping normalized extaddr (lowercase) to device_label.
        Returns empty dict on error.
    
    Supported formats:
        List format:
            [
                {"extaddr": "AA11BB22CC33DD44", "device_label": "Kitchen"},
                {"extAddress": "BB22CC33DD44EE55", "device_label": "Bedroom"}
            ]
        
        Dict format:
            {
                "device1": {"extaddr": "AA11BB22CC33DD44", "device_label": "Kitchen"},
                "device2": {"extAddress": "BB22CC33DD44EE55", "device_label": "Bedroom"}
            }
    
    Examples:
        >>> mapping = load_extaddr_device_label_map_flexible("data/map.json")
        >>> mapping.get("aa11bb22cc33dd44")
        "Kitchen"
    """
    mapping: dict[str, str] = {}
    
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        logging.error(f"Failed to open extaddr device label map {path!r}: {e}")
        return mapping
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in extaddr device label map {path!r}: {e}")
        return mapping
    
    if not isinstance(data, (list, dict)):
        logging.error(f"Expected list or dict in {path!r}, got {type(data).__name__}")
        return mapping
    rows = []
    for item in data.values() if isinstance(data, dict) else data:
        if not isinstance(item, dict):
            continue
        extaddr = get_extaddr_from_record(item, extaddr_aliases)
        label = item.get("deviceLabel") or item.get("device_label")
        if extaddr and isinstance(label, str) and label.strip():
            mapping[extaddr] = label.strip()
            rows.append((extaddr, mapping[extaddr], item.get("previousExtAddresses")))
    _include_previous_addresses(mapping, rows)
    return mapping


def load_extaddr_device_label_map(path=EXTADDR_DEVICE_LABEL_MAP_FILENAME):
    """
    Parses extended address to node name mapping from the configured label map file.

    Args:
        path: Path to the extaddr->device_label mapping JSON file

    Returns:
        Dictionary mapping extaddr (lowercase) to device_label
    """

    mapping = {}
    try:
        with open(path) as f:
            data = json.load(f)
    except OSError as e:
        logging.error(f"Failed to open extaddr device label map {path!r}: {e}")
        return mapping
    except json.JSONDecodeError as e:
        logging.error(
            f"Invalid JSON in extaddr device label map {path!r}: {e}")
        return mapping

    if not isinstance(data, list):
        logging.error(
            f"Expected a list in {path!r}, got {type(data).__name__}")
        return mapping

    rows = []
    for item in data:
        if not isinstance(item, dict):
            continue
        # Support both camelCase and snake_case field names
        extaddr = get_extaddr_from_record(item, ("extAddress", "extaddr", "Extended MAC"))
        device_label = item.get("deviceLabel", "") or item.get("device_label")
        if not extaddr:
            logging.warning(f"Skipping entry missing 'extAddress': {item!r}")
            continue
        if not device_label:
            logging.warning(
                f"Skipping entry missing 'device_label' for extaddr {extaddr!r}: {item!r}"
            )
            continue
        mapping[extaddr] = device_label
        if isinstance(device_label, str):
            rows.append((extaddr, device_label, item.get("previousExtAddresses")))

    _include_previous_addresses(mapping, rows)
    return mapping
