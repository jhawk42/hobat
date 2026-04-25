import base64
import logging
from util_convert import b64_to_extended_address

# Your raw strings from the JSON
b64_list = [
    "0sazLADIFJ4=",
    "VqKynscC0tI=",
    r"hg\/hn+qrKlU=",
    "jjs2nfZelJY=",
    "QlB146VTFRQ=",
    "qvJwk3MAmFM=",
    "emv0Jau9vjM=",
    "RpUpMF3ecJo=",
    "FsJO4QnpC6Y=",
    r"Gn+\/BDTk8EM=",
]

for item in b64_list:
    hexnumber = b64_to_extended_address(item)
    logging.info(f"Base64: {item:15} -> Hex: {hexnumber}")
