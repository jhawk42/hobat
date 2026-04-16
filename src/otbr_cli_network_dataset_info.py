import logging
import json
from typing import Sequence
import util_network

def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

    network_dataset_info = util_network.get_network_dataset_info()
    save_json_path = "td-otbr-cli-network-dataset-info.json"
    with open(save_json_path, 'w', encoding='utf-8') as f:
        json.dump(network_dataset_info, f, indent=4)
    print(json.dumps(network_dataset_info, indent=4))


if __name__ == "__main__":
    raise SystemExit(main())    