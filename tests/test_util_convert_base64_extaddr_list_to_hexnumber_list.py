import base64
from util_convert import convert_from_base64_to_ext_address_hexnumber

# Your raw strings from the JSON
b64_list = [
    "0sazLADIFJ4=", "VqKynscC0tI=", r"hg\/hn+qrKlU=", "jjs2nfZelJY=",
    "QlB146VTFRQ=", "qvJwk3MAmFM=", "emv0Jau9vjM=", "RpUpMF3ecJo=",
    "FsJO4QnpC6Y=", "Gn+\/BDTk8EM="
]

for item in b64_list:
    hexnumber = convert_from_base64_to_ext_address_hexnumber(item)
    print(f"Base64: {item:15} -> Hex: {hexnumber}")
