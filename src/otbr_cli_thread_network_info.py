import logging
import json
import sys
import time
from pathlib import Path
from typing import Sequence
from td_logging import log_event
from td_json_key_normalizer import convert_keys_to_camel_case
from td_const import OTBR_CLI_THREAD_NETWORK_INFO_FILENAME
import util_network
from util_data import (
    CollectionWriteOutcome,
    data_file_path,
    parse_datadir_from_argv,
    resolve_data_dir,
    save_final_json,
    save_json_atomic,
)


def collect_thread_network_info(output_path: Path | None = None, ext_pan_id: object = None):
    started_at = time.monotonic()
    normal_return = False
    collection_elapsed_ms = None
    fields = None
    final = "not_requested" if output_path is None else "not_attempted"
    try:
        thread_network_info = util_network.fetch_thread_network_info()
        collection_elapsed_ms = max(0, round((time.monotonic() - started_at) * 1000))
        fields = (
            len(thread_network_info)
            if isinstance(thread_network_info, dict)
            else None
        )
        if output_path is not None:
            converted = convert_keys_to_camel_case(thread_network_info)
            write_returned = False
            try:
                written = save_final_json(
                    converted,
                    output_path,
                    CollectionWriteOutcome.complete(),
                    writer=save_json_atomic,
                    ext_pan_id=ext_pan_id,
                )
                write_returned = True
            finally:
                if write_returned:
                    final = "saved" if written else "retained_previous"
                    log_event(
                        "write", source="otbr-cli", command="thread-network-info",
                        stage="final", output=str(output_path), fields=fields,
                        disposition=final,
                    )
                else:
                    error = sys.exc_info()[1]
                    final = "failed"
                    log_event(
                        "write", source="otbr-cli", command="thread-network-info",
                        stage="final", output=str(output_path), fields=fields,
                        disposition="failed",
                        error_type=type(error).__name__ if error is not None else None,
                    )
            if written:
                logging.debug(
                    "Saved thread network info data into %s as JSON:\n%s",
                    output_path,
                    json.dumps(thread_network_info, indent=4),
                )
                logging.info(
                    "Saved thread network info with %d entries into %s.",
                    len(thread_network_info),
                    output_path,
                )
            else:
                final = "retained_previous"
        normal_return = True
        return thread_network_info
    finally:
        log_event(
            "collector_summary", source="otbr-cli", command="thread-network-info",
            stage="metadata", fields=fields,
            elapsed_ms=(
                collection_elapsed_ms
                if collection_elapsed_ms is not None
                else max(0, round((time.monotonic() - started_at) * 1000))
            ),
            final=final, state="returned" if normal_return else "failed",
        )


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Collect OTBR Thread network info")
    parser.add_argument("--datadir", default=None)
    parser.add_argument("--ext-pan-id", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s"
    )

    td_data_dir = resolve_data_dir(data_dir=args.datadir)
    try:
        save_json_path = data_file_path(
            OTBR_CLI_THREAD_NETWORK_INFO_FILENAME, td_data_dir
        )
        collect_thread_network_info(save_json_path, ext_pan_id=args.ext_pan_id)
        return 0
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logging.error(f"Invalid payload while collecting thread-network-info: {exc}")
        return 5
    except Exception as exc:
        logging.error(f"Runtime failure while collecting thread-network-info: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
