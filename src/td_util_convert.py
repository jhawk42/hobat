import base64

def b64_to_extaddr_hex(b64_str, reverse=False):
    """
    Converts a base64-encoded extended address to hexadecimal format.
    
    Args:
        b64_str: Base64 encoded string (may contain escaped slashes \\/)
        reverse: If True, reverses byte order for 802.15.4 little-endianness
    
    Returns:
        Hexadecimal string representation of the extended address
    """
    # 1. Clean JSON escaped slashes
    clean_b64 = b64_str.replace(r'\/', '/')
    
    # 2. Decode to bytes
    raw_bytes = base64.b64decode(clean_b64)
    
    # 3. Handle 802.15.4 little-endianness if needed
    if reverse:
        raw_bytes = raw_bytes[::-1]
        
    return raw_bytes.hex()


def extaddr_hex_to_b64(hex_str, reverse=False):
    """
    Converts a hexadecimal extended address to a base64-encoded string.
    
    Args:
        hex_str: Hexadecimal string representation of the extended address
        reverse: If True, reverses byte order for 802.15.4 little-endianness
    
    Returns:
        Base64 encoded string (with escaped slashes if needed)
    """
    # 1. Convert hex string to bytes
    raw_bytes = bytes.fromhex(hex_str)
    
    # 2. Handle 802.15.4 little-endianness if needed
    if reverse:
        raw_bytes = raw_bytes[::-1]
    
    # 3. Encode to Base64
    b64_str = base64.b64encode(raw_bytes).decode('utf-8')
    
    # 4. Escape slashes for JSON if needed
    escaped_b64_str = b64_str.replace('/', r'\/')
    
    return escaped_b64_str


# Backward-compatible aliases
convert_from_base64_to_ext_address_hexnumber = b64_to_extaddr_hex
convert_hexnumber_extaddr_to_base64 = extaddr_hex_to_b64
