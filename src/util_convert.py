import base64
import binascii


def b64_to_extended_address(b64_str, reverse=False):
    """
    Converts a base64-encoded extended address to hexadecimal format.

    Args:
        b64_str: Base64 encoded string (may contain escaped slashes \\/)
        reverse: If True, reverses byte order for 802.15.4 little-endianness

    Returns:
        Hexadecimal string representation of the extended address
    """
    if not isinstance(b64_str, str) or not b64_str:
        raise ValueError(
            f"b64_to_extended_address: expected a non-empty string, got {b64_str!r}"
        )

    # 1. Clean JSON escaped slashes
    clean_b64 = b64_str.replace(r"\/", "/")

    # 2. Decode to bytes
    try:
        raw_bytes = base64.b64decode(clean_b64)
    except binascii.Error as e:
        raise ValueError(
            f"b64_to_extended_address: invalid base64 input {b64_str!r}: {e}"
        ) from e

    # 3. Handle 802.15.4 little-endianness if needed
    if reverse:
        raw_bytes = raw_bytes[::-1]

    return raw_bytes.hex()


def extended_address_to_b64(hex_str, reverse=False):
    """
    Converts a hexadecimal extended address to a base64-encoded string.

    Args:
        hex_str: Hexadecimal string representation of the extended address
        reverse: If True, reverses byte order for 802.15.4 little-endianness

    Returns:
        Base64 encoded string (with escaped slashes if needed)
    """
    if not isinstance(hex_str, str) or not hex_str:
        raise ValueError(
            f"extended_address_to_b64: expected a non-empty string, got {hex_str!r}"
        )

    # 1. Convert hex string to bytes
    try:
        raw_bytes = bytes.fromhex(hex_str)
    except ValueError as e:
        raise ValueError(
            f"extended_address_to_b64: invalid hex input {hex_str!r}: {e}"
        ) from e

    # 2. Handle 802.15.4 little-endianness if needed
    if reverse:
        raw_bytes = raw_bytes[::-1]

    # 3. Encode to Base64
    b64_str = base64.b64encode(raw_bytes).decode("utf-8")

    # 4. Escape slashes for JSON if needed
    escaped_b64_str = b64_str.replace("/", r"\/")

    return escaped_b64_str


def extaddr_hex_to_base64(hex_number, reverse=False):
    """Backward-compatible alias for hex extaddr to Base64 conversion."""
    return extended_address_to_b64(hex_number, reverse=reverse)
