from __future__ import annotations

from typing import Any, Mapping, Sequence

import logging

from otbr_restapi_client import (
    DEFAULT_ACCEPT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    OTBRConnectionError,
    OTBRClientError,
    OTBRErrorDetail,
    OTBRHTTPError,
    OTBRInvalidResponseError,
    OTBRRestApiClient,
    OTBRUsageError,
    build_fields_mapping,
    error_to_dict,
)


class OTBRRawRestApiClient(OTBRRestApiClient):
    """OTBR REST client that defaults to returning raw server envelopes."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        base_url: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        accept: str = DEFAULT_ACCEPT,
        user_agent: str = "td-otbr-restapi-raw-client/1.0",
    ) -> None:
        super().__init__(
            host=host,
            port=port,
            base_url=base_url,
            timeout=timeout,
            accept=accept,
            user_agent=user_agent,
            default_raw=True,
        )


__all__ = [
    "DEFAULT_ACCEPT",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_TIMEOUT",
    "OTBRClientError",
    "OTBRConnectionError",
    "OTBRErrorDetail",
    "OTBRHTTPError",
    "OTBRInvalidResponseError",
    "OTBRRawRestApiClient",
    "OTBRUsageError",
    "build_fields_mapping",
    "error_to_dict",
]
