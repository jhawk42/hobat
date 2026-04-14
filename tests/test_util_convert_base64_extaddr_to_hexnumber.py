import base64
from util_convert import b64_to_ext_address

# The original Base64 string
#base64_string = "qvJwk3MAmFM="
base64_string = "emv0Jau9vjM="

hex_number = b64_to_ext_address(base64_string)

print(f"Base64: {base64_string}")
print(f"Hex:    {hex_number}")
# Output: aaf2709373009853
# Output: qvJwk3MAmFM= -> Hex: aaf2709373009853
