import logging
import json
from typing import Sequence
from td_json_key_normalizer import convert_keys_to_camel_case
from td_const import OTBR_CLI_THREAD_NETWORK_INFO_FILENAME
import util_network
from util_data import data_file_path, parse_datadir_from_argv, resolve_data_dir, save_json_atomic


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    td_data_dir = resolve_data_dir(data_dir=parse_datadir_from_argv(argv))
    try:
        thread_network_info = util_network.fetch_thread_network_info()
        save_json_path = data_file_path(
            OTBR_CLI_THREAD_NETWORK_INFO_FILENAME, td_data_dir
        )
        save_json_atomic(
            convert_keys_to_camel_case(thread_network_info),
            save_json_path,
        )
        logging.debug("Saved thread network info data into %s as JSON:\n%s",
                save_json_path, json.dumps(thread_network_info, indent=4))
        logging.info(
            f"Saved thread network info with {len(thread_network_info)} entries into {save_json_path}."
        )
        return 0
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logging.error(f"Invalid payload while collecting thread-network-info: {exc}")
        return 5
    except Exception as exc:
        logging.error(f"Runtime failure while collecting thread-network-info: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
