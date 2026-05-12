from __future__ import annotations

import argparse
import logging

from typing import Any, Sequence
from util_data import resolve_data_dir

from otbr_restapi_client_cli import (
    EXIT_SUCCESS,
    _get_all_device_ids,
    _parse_dataset_input,
    _parse_mesh_diag_types,
    _parse_typed_values,
    _resolve_types,
    build_parser as build_flattened_parser,
    dispatch,
    emit_error,
    emit_output,
    exit_code_for_exception,
    run_cli,
)
from otbr_restapi_raw_client import OTBRRawRestApiClient, build_fields_mapping
from otbr_restapi_client import (
    DIAG_TLV_CHILDREN,
    DIAG_TLV_CHILD_IPV6_ADDRS,
    DIAG_TLV_ROUTER_NEIGHBORS,
    MESH_DIAGNOSTIC_TLVS,
    DestinationType,
    extract_action_result_id,
)


def build_parser() -> argparse.ArgumentParser:
    parser = build_flattened_parser()
    parser.description = "CLI wrapper for the OpenThread Border Router REST API returning raw server envelopes."
    return parser


def build_client(args: argparse.Namespace) -> OTBRRawRestApiClient:
    return OTBRRawRestApiClient(
        host=args.host,
        port=args.port,
        base_url=args.base_url,
        timeout=args.timeout,
        accept=args.accept,
    )


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(build_parser, dispatch, build_client, argv)


if __name__ == "__main__":
    raise SystemExit(main())

