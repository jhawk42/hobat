import json


def parse_extaddr_nodename_mapping(path):
    """
    Parses extended address to node name mapping from threadstatic-extaddr.json.
    
    Args:
        path: Path to threadstatic-extaddr.json file
    
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
