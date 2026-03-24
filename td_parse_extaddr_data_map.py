import json


def parse_extaddr_nodename_mapping(path):
    """
    Parses extended address to node name mapping from threadstatic-extaddr.json.
    
    Args:
        path: Path to threadstatic-extaddr.json file
    
    Returns:
        Dictionary mapping extaddr (lowercase) to node_name
    """

    mapping = {}
    with open(path) as f:
        data = json.load(f)
    for item in data:
        extaddr = item.get("extaddr", "").lower()
        node_name = item.get("node_name", "")
        if extaddr:
            mapping[extaddr] = node_name

    return mapping
