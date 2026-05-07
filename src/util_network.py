import util_ot_ctl
import logging


def _parse_prefix_token(command_output):
    """Extracts the first token (prefix) from ot-ctl command output."""
    command_output = command_output.strip()
    return command_output.split()[0] if command_output else ""


def _strip_prefix_mask(prefix):
    """Normalizes prefix by removing mask and trailing colon(s)."""
    return prefix.split("/")[0].rstrip(":")


def _fetch_prefix_via_ot_ctl(command, debug_label):
    """Runs an ot-ctl prefix command and returns the extracted prefix token."""
    command_output = util_ot_ctl.exec_ot_ctl(command)
    # extract the prefix token from the command output and print it for debugging
    prefix = _parse_prefix_token(command_output)
    logging.debug(f"[DEBUG] {debug_label}: {prefix}\n")
    return prefix


def _build_ipv6_prefix_by_type(prefix, kind):
    """Formats a prefix for a specific address kind."""
    base_prefix = _strip_prefix_mask(prefix)

    if kind == "meshlocal":
        return base_prefix + ":0:ff:fe00:"
    if kind == "omr":
        return base_prefix

    raise ValueError(f"Unsupported prefix kind: {kind}")


def fetch_meshlocal_prefix():
    """
    Retrieves the mesh-local prefix from the Thread network.
    Runs: ot-ctl prefix meshlocal
    Returns: mesh-local prefix string (e.g., "fdde:ad00:beef:0::/64")
    """
    return _fetch_prefix_via_ot_ctl("prefix meshlocal", "Mesh-Local Prefix")


def build_rloc_ipv6_address_prefix(meshlocal_prefix):
    """
    Converts a mesh-local prefix into an IPv6 rloc16 address prefix.

    Mesh-Local-Prefix + 0000:00ff:fe00: + rloc16
    Example: fde5:8dba:82e1:1::/64 + 0x401 = fde5:8dba:82e1:1:0:ff:fe00:0401

    Args:
        meshlocal_prefix: Mesh-local prefix string (e.g., "fdde:ad00:beef:0::/64")

    Returns:
        IPv6 RLOC address prefix string (e.g., "fdde:ad00:beef:0:0:ff:fe00:")
    """
    return _build_ipv6_prefix_by_type(meshlocal_prefix, "meshlocal")


def strip_rloc16_hex_prefix(rloc):
    """
    Strips the '0x' prefix from an rloc16 value.

    Args:
        rloc: rloc16 value string (e.g., "0x5000")

    Returns:
        Hex string without '0x' prefix (e.g., "5000")
    """
    return rloc[2:]


def build_rloc16_ipv6_address(ipv6_rloc_prefix, rloc_hex):
    """
    Merges IPv6 RLOC prefix with rloc16 hex value to form complete IPv6 RLOC address.

    Args:
        ipv6_rloc_prefix: IPv6 RLOC prefix string (e.g., "fdde:ad00:beef:0:0:ff:fe00:")
        rloc_hex: rloc16 hex value without '0x' prefix (e.g., "5000")

    Returns:
        Complete IPv6 RLOC address (e.g., "fdde:ad00:beef:0:0:ff:fe00:5000")
    """
    return f"{ipv6_rloc_prefix}{rloc_hex}"


def fetch_omr_prefix():
    """
    Retrieves the On-Mesh Routable (OMR) prefix from the Thread network.
    Runs: ot-ctl br omrprefix favored
    Returns: OMR prefix string (e.g., "fda5:494c:9a12:0::/64")
    """
    return _fetch_prefix_via_ot_ctl("br omrprefix favored", "OMR Prefix")


def build_omr_ipv6_address_prefix(omr_prefix):
    """
    Converts an OMR (On-Mesh Routable) prefix into an IPv6 address prefix.

    OMR-Prefix fda5:494c:9a12:0::/64
    Format Example OMR-Prefix fda5:494c:9a12:0:

    Args:
        omr_prefix: OMR prefix string (e.g., "fda5:494c:9a12:0::/64")

    Returns:
        IPv6 OMR address prefix string (e.g., "fda5:494c:9a12:0:")
    """
    return _build_ipv6_prefix_by_type(omr_prefix, "omr")


def is_ipv6_address_in_omr_prefix(ipv6_address, omr_ipv6_prefix):
    """
    Checks if a given IPv6 address falls within a specified OMR (On-Mesh Routable) ipv6 prefix.

    Args:
        ipv6_address: The IPv6 address to check (e.g., "fdde:ad00:beef:0:0:ff:fe00:5000")
        omr_ipv6_prefix: The OMR (On-Mesh Routable) IPv6 prefix to check against (e.g., "fdde:ad00:beef:0:0:ff:fe00:")

    Returns:
        True if the IPv6 address is within the prefix, False otherwise.
    """
    return ipv6_address.startswith(omr_ipv6_prefix)


def find_omr_address_in_list(ipv6_addrs, omr_ipv6_prefix):
    """
    Retrieves the OMR (On-Mesh Routable) address from a list of IPv6 addresses based on the OMR prefix.

    Args:
        ipv6_addrs: List of IPv6 address strings to check (e.g., ["fdde:ad00:beef:0:0:ff:fe00:5000", "fdde:ad00:beef:0:0:ff:fe00:6000"])
        omr_ipv6_prefix: The OMR (On-Mesh Routable) IPv6 prefix to check against (e.g., "fdde:ad00:beef:0:0:ff:fe00:")

    Returns:
        The first IPv6 address from the list that matches the OMR prefix, or None if no match is found.
    """
    for addr in ipv6_addrs:
        if is_ipv6_address_in_omr_prefix(addr, omr_ipv6_prefix):
            return addr
    return None


def fetch_dataset_active(hide_sensitive_info=True):
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

    # hide_sensitive_info set to True to exclude sensitive info like network key and PSKc in the output
    command = "dataset active"
    if hide_sensitive_info:
        command += " -ns"  # Add -ns flag to hide sensitive info in the output
    dataset_output = util_ot_ctl.exec_ot_ctl(command).strip()
    logging.debug(f"[DEBUG] Dataset Active Output:\n{dataset_output}\n")

    dataset_info = {}

    # Parse key: value pairs from output
    for line in dataset_output.split("\n"):
        line = line.strip()

        # Skip empty lines and "Done" line
        if not line or line == "Done":
            continue

        # Split by the first colon
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().lower().replace(" ", "_").replace("-", "_")
            value = value.strip()
            dataset_info[key] = value

    logging.debug(f"[DEBUG] Parsed Dataset Info: {dataset_info}\n")
    return dataset_info


def fetch_network_dataset_info():
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
    prefix_meshlocal = fetch_meshlocal_prefix()
    network_dataset_info["prefix_meshlocal"] = prefix_meshlocal

    # Format mesh-local prefix into IPv6 address prefix
    prefix_meshlocal_ipv6addr_prefix = build_rloc_ipv6_address_prefix(
        prefix_meshlocal
    )
    network_dataset_info["prefix_meshlocal_ipv6addr_prefix"] = (
        prefix_meshlocal_ipv6addr_prefix
    )

    # Get OMR prefix
    prefix_omr = fetch_omr_prefix()
    network_dataset_info["prefix_omr"] = prefix_omr
    network_dataset_info["prefix_omr_ipv6addr_prefix"] = (
        build_omr_ipv6_address_prefix(prefix_omr)
    )

    # Get active dataset information and add individual fields to network_dataset_info
    dataset_active = fetch_dataset_active()
    network_dataset_info.update(dataset_active)

    return network_dataset_info
