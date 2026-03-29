import td_util_ot_ctl


def _extract_prefix_token(command_output):
    """Extracts the first token (prefix) from ot-ctl command output."""
    command_output = command_output.strip()
    return command_output.split()[0] if command_output else ""

def _normalize_prefix_base(prefix):
    """Normalizes prefix by removing mask and trailing colon(s)."""
    return prefix.split("/")[0].rstrip(":")

def _run_prefix_command(command, debug_label):
    """Runs an ot-ctl prefix command and returns the extracted prefix token."""
    command_output = td_util_ot_ctl.run_ot_ctl_stdio(command)
    # extract the prefix token from the command output and print it for debugging
    prefix = _extract_prefix_token(command_output)
    print(f"[DEBUG] {debug_label}: {prefix}\n")
    return prefix

def _format_prefix_for_kind(prefix, kind):
    """Formats a prefix for a specific address kind."""
    base_prefix = _normalize_prefix_base(prefix)

    if kind == "meshlocal":
        return base_prefix + ":0:ff:fe00:"
    if kind == "omr":
        return base_prefix

    raise ValueError(f"Unsupported prefix kind: {kind}")

def get_prefix_meshlocal():
    """
    Retrieves the mesh-local prefix from the Thread network.
    Runs: ot-ctl prefix meshlocal
    Returns: mesh-local prefix string (e.g., "fdde:ad00:beef:0::/64")
    """
    return _run_prefix_command("prefix meshlocal", "Mesh-Local Prefix")

def format_prefix_meshlocal_into_ipv6adrr_prefix(meshlocal_prefix):
    """
    Converts a mesh-local prefix into an IPv6 rloc16 address prefix.
    
    Mesh-Local-Prefix + 0000:00ff:fe00: + rloc16
    Example: fde5:8dba:82e1:1::/64 + 0x401 = fde5:8dba:82e1:1:0:ff:fe00:0401
    
    Args:
        meshlocal_prefix: Mesh-local prefix string (e.g., "fdde:ad00:beef:0::/64")
    
    Returns:
        IPv6 RLOC address prefix string (e.g., "fdde:ad00:beef:0:0:ff:fe00:")
    """
    return _format_prefix_for_kind(meshlocal_prefix, "meshlocal")

def conform_rloc_hex_strip(rloc):
    """
    Strips the '0x' prefix from an rloc16 value.
    
    Args:
        rloc: rloc16 value string (e.g., "0x5000")
    
    Returns:
        Hex string without '0x' prefix (e.g., "5000")
    """
    return rloc[2:]


def merge_ipv6_rloc_prefix_rloc_hex(ipv6_rloc_prefix, rloc_hex):
    """
    Merges IPv6 RLOC prefix with rloc16 hex value to form complete IPv6 RLOC address.
    
    Args:
        ipv6_rloc_prefix: IPv6 RLOC prefix string (e.g., "fdde:ad00:beef:0:0:ff:fe00:")
        rloc_hex: rloc16 hex value without '0x' prefix (e.g., "5000")
    
    Returns:
        Complete IPv6 RLOC address (e.g., "fdde:ad00:beef:0:0:ff:fe00:5000")
    """
    return f"{ipv6_rloc_prefix}{rloc_hex}"


def get_prefix_omr():
    """
    Retrieves the On-Mesh Routable (OMR) prefix from the Thread network.
    Runs: ot-ctl br omrprefix favored
    Returns: OMR prefix string (e.g., "fda5:494c:9a12:0::/64")
    """
    return _run_prefix_command("br omrprefix favored", "OMR Prefix")

def format_prefix_omr_into_ipv6adrr_prefix(omr_prefix):
    """
    Converts an OMR (On-Mesh Routable) prefix into an IPv6 address prefix.
    
    OMR-Prefix fda5:494c:9a12:0::/64
    Format Example OMR-Prefix fda5:494c:9a12:0:

    Args:
        omr_prefix: OMR prefix string (e.g., "fda5:494c:9a12:0::/64")
    
    Returns:
        IPv6 OMR address prefix string (e.g., "fda5:494c:9a12:0:")
    """
    return _format_prefix_for_kind(omr_prefix, "omr")


def get_dataset_active(hideSensitiveInfo=True):
    """
    Retrieves the active Thread dataset from the network.
    Runs: ot-ctl dataset active
    
    Returns:
        Dictionary with keys:
            - active_timestamp: Active timestamp value
            - channel: Current channel number
            - wakeup_channel: Wake-up channel number
            - channel_mask: Channel mask in hex format
            - ext_pan_id: Extended PAN ID
            - mesh_local_prefix: Mesh-local prefix
            - network_key: Network key (hex)
            - network_name: Network name
            - pan_id: PAN ID in hex format
            - pskc: Pre-Shared Key for the Commissioner (hex)
            - security_policy: Security policy info
    """
    
    # hideSensitiveInfo set to True to exclude sensitive info like network key and PSKc in the output
    command = "dataset active"
    if hideSensitiveInfo:
        command += " -ns"  # Add -ns flag to hide sensitive info in the output
    dataset_output = td_util_ot_ctl.run_ot_ctl_stdio(command).strip()
    print(f"[DEBUG] Dataset Active Output:\n{dataset_output}\n")
    
    dataset_info = {}
    
    # Parse key: value pairs from output
    for line in dataset_output.split('\n'):
        line = line.strip()
        
        # Skip empty lines and "Done" line
        if not line or line == "Done":
            continue
        
        # Split by the first colon
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip().lower().replace(' ', '_').replace('-', '_')
            value = value.strip()
            dataset_info[key] = value
    
    print(f"[DEBUG] Parsed Dataset Info: {dataset_info}\n")
    return dataset_info


def get_network_dataset_info():
    """
    Retrieves and formats complete network dataset info from the Thread network.
    
    Returns:
        Dictionary with keys:
            - prefix_meshlocal: Mesh-local prefix string
            - prefix_meshlocal_ipv6addr_prefix: Formatted IPv6 RLOC address prefix
            - prefix_omr: OMR (On-Mesh Routable) prefix string
            - prefix_omr_ipv6addr_prefix: Formatted IPv6 OMR address prefix
            - dataset_active: Dictionary containing active Thread dataset info:
                - active_timestamp: Active timestamp value
                - channel: Current channel number
                - wakeup_channel: Wake-up channel number
                - channel_mask: Channel mask in hex format
                - ext_pan_id: Extended PAN ID
                - mesh_local_prefix: Mesh-local prefix
                - network_key: Network key (hex)
                - network_name: Network name
                - pan_id: PAN ID in hex format
                - pskc: Pre-Shared Key for the Commissioner (hex)
                - security_policy: Security policy info
    """
    network_dataset_info = {}
    
    # Get mesh-local prefix
    prefix_meshlocal = get_prefix_meshlocal()
    network_dataset_info["prefix_meshlocal"] = prefix_meshlocal
    
    # Format mesh-local prefix into IPv6 address prefix
    prefix_meshlocal_ipv6addr_prefix = format_prefix_meshlocal_into_ipv6adrr_prefix(prefix_meshlocal)
    network_dataset_info["prefix_meshlocal_ipv6addr_prefix"] = prefix_meshlocal_ipv6addr_prefix
    
    # Get OMR prefix
    prefix_omr = get_prefix_omr()
    network_dataset_info["prefix_omr"] = prefix_omr
    network_dataset_info["prefix_omr_ipv6addr_prefix"] = format_prefix_omr_into_ipv6adrr_prefix(prefix_omr)
    
    # Get active dataset information and add individual fields to network_dataset_info
    dataset_active = get_dataset_active()
    network_dataset_info.update(dataset_active)
    
    return network_dataset_info
