import json
import sys
from typing import Iterable, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HOST = "127.0.0.1"
PORT = 8081
BASE_URL = f"http://{HOST}:{PORT}"
HEADERS = {"Accept": "application/vnd.api+json"}

# (endpoint path, output file)
DOWNLOAD_TARGETS: Iterable[Tuple[str, str]] = [
    ("/node/dataset/active", "td-otbr-restapi-dataset.json"),
    ("/api/devices", "td-otbr-restapi-devices.json"),
    ("/api/diagnostics", "td-otbr-restapi-diagnostics.json"),
]


def download_json(url: str, headers: dict, output_file: str, timeout: int = 10) -> bool:
    """Download JSON from a URL and save it to a file."""
    request = Request(url=url, headers=headers, method="GET")

    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            payload = response.read().decode(charset)

        data = json.loads(payload)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

        print(f"OK: {url} -> {output_file}")
        # print the json data in a human readable format
        print(json.dumps(data, indent=4))
        return True
    except HTTPError as e:
        print(f"HTTP error for {url}: {e.code} {e.reason}")
    except URLError as e:
        print(f"Network error for {url}: {e.reason}")
    except json.JSONDecodeError as e:
        print(f"Invalid JSON from {url}: {e}")
    except OSError as e:
        print(f"File write error for {output_file}: {e}")
    except Exception as e:
        print(f"Unexpected error for {url}: {e}")

    return False

def restapi_downloads() -> int:
    failures = 0

    for endpoint, output_file in DOWNLOAD_TARGETS:
        url = f"{BASE_URL}{endpoint}"
        ok = download_json(url, HEADERS, output_file)
        if not ok:
            failures += 1

    if failures:
        print(f"Completed with {failures} failure(s).")
        return 1

    print("All downloads completed successfully.")
    return 0

def main() -> int:
    return restapi_downloads()

if __name__ == "__main__":
    sys.exit(main())
