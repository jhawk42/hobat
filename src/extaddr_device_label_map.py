import json
import logging

from const import EXTADDR_DEVICE_LABEL_MAP_FILENAME


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

    for item in data:
        extaddr = item.get("extaddr", "").lower()
        device_label = item.get("device_label", "")
        if not extaddr:
            logging.warning(f"Skipping entry missing 'extaddr': {item!r}")
            continue
        if not device_label:
            logging.warning(
                f"Skipping entry missing 'device_label' for extaddr {extaddr!r}: {item!r}"
            )
            continue
        mapping[extaddr] = device_label

    return mapping
