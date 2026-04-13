import base64
from util_convert import convert_hexnumber_extaddr_to_base64

# The original hex string
hex_number = "aaf2709373009853"
base64_string = convert_hexnumber_extaddr_to_base64(hex_number)

print(f"Hex:    {hex_number}")
print(f"Base64: {base64_string}")
# Output: aaf2709373009853 -> Base64: qvJwk3MAmFM=


