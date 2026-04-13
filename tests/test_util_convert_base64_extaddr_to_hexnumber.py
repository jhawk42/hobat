import base64
from util_convert import convert_from_base64_to_ext_address_hexnumber

# The original Base64 string
#base64_string = "qvJwk3MAmFM="
base64_string = "emv0Jau9vjM="

hex_number = convert_from_base64_to_ext_address_hexnumber(base64_string)

print(f"Base64: {base64_string}")
print(f"Hex:    {hex_number}")
# Output: aaf2709373009853
# Output: qvJwk3MAmFM= -> Hex: aaf2709373009853
