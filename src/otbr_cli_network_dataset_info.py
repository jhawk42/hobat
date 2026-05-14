import logging
import json
import os
from typing import Sequence
import util_network
from util_data import data_file_path, parse_datadir_from_argv, resolve_data_dir, save_json_atomic


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    td_data_dir = resolve_data_dir(
        data_dir=parse_datadir_from_argv(argv))
    network_dataset_info = util_network.fetch_network_dataset_info()
    save_json_path = data_file_path(
        "td-otbr-cli-network-dataset-info.json", td_data_dir
    )
    save_json_atomic(network_dataset_info, save_json_path)
    logging.debug("Raw network dataset info as JSON:\n%s",
                  json.dumps(network_dataset_info, indent=4))


if __name__ == "__main__":
    raise SystemExit(main())
