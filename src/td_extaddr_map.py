import json


def load_extaddr_map(path):
    """
    Parses extended address to node name mapping from td-static-extaddr-device-label.json.
    
    Args:
        path: Path to td-static-extaddr-device-label.json file
    
    Returns:
        Dictionary mapping extaddr (lowercase) to device_label
    """

    mapping = {}
    with open(path) as f:
        data = json.load(f)
    for item in data:
        extaddr = item.get("extaddr", "").lower()
        device_label = item.get("device_label", "")
        if extaddr:
            mapping[extaddr] = device_label

    return mapping


# Backward-compatible alias
parse_extaddr_nodename_mapping = load_extaddr_map
