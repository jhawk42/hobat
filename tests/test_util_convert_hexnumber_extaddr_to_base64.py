import base64
import logging
from util_convert import extended_address_to_b64

# The original hex string
hex_number = "aaf2709373009853"
base64_string = extended_address_to_b64(hex_number)

logging.info(f"Hex:    {hex_number}")
logging.info(f"Base64: {base64_string}")


# Output: aaf2709373009853 -> Base64: qvJwk3MAmFM=


