import base64
import logging
from util_convert import b64_to_extended_address

# The original Base64 string
# base64_string = "qvJwk3MAmFM="
base64_string = "emv0Jau9vjM="

hex_number = b64_to_extended_address(base64_string)

logging.info(f"Base64: {base64_string}")
logging.info(f"Hex:    {hex_number}")
# Output: aaf2709373009853
# Output: qvJwk3MAmFM= -> Hex: aaf2709373009853
