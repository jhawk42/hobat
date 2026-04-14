import base64
from util_convert import b64_to_ext_address

# Your raw strings from the JSON
b64_list = [
    "0sazLADIFJ4=", "VqKynscC0tI=", r"hg\/hn+qrKlU=", "jjs2nfZelJY=",
    "QlB146VTFRQ=", "qvJwk3MAmFM=", "emv0Jau9vjM=", "RpUpMF3ecJo=",
    "FsJO4QnpC6Y=", "Gn+\/BDTk8EM="
]

for item in b64_list:
    hexnumber = b64_to_ext_address(item)
    print(f"Base64: {item:15} -> Hex: {hexnumber}")
