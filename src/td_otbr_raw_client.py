from __future__ import annotations

from typing import Any, Mapping, Sequence

from td_otbr_client import (
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
        )

    def get_node(
        self,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        *,
        raw: bool = True,
    ) -> Any:
        return super().get_node(fields=fields, raw=raw)

    def get_active_dataset(self, *, plain_text: bool = False, raw: bool = True) -> Any:
        return super().get_active_dataset(plain_text=plain_text, raw=raw)

    def list_devices(
        self,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        *,
        raw: bool = True,
        with_meta: bool = False,
    ) -> Any:
        return super().list_devices(fields=fields, raw=raw, with_meta=with_meta)

    def get_device(
        self,
        device_id: str,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        *,
        raw: bool = True,
    ) -> Any:
        return super().get_device(device_id=device_id, fields=fields, raw=raw)

    def list_diagnostics(
        self,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        *,
        raw: bool = True,
        with_meta: bool = False,
    ) -> Any:
        return super().list_diagnostics(fields=fields, raw=raw, with_meta=with_meta)

    def get_diagnostic(self, diagnostics_id: str, *, raw: bool = True) -> Any:
        return super().get_diagnostic(diagnostics_id=diagnostics_id, raw=raw)

    def list_actions(
        self,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        *,
        raw: bool = True,
        with_meta: bool = False,
    ) -> Any:
        return super().list_actions(fields=fields, raw=raw, with_meta=with_meta)

    def get_action(self, action_id: str, *, raw: bool = True) -> Any:
        return super().get_action(action_id=action_id, raw=raw)

    def enqueue_actions(self, tasks: Sequence[Mapping[str, Any]], *, raw: bool = True) -> Any:
        return super().enqueue_actions(tasks=tasks, raw=raw)

    def enqueue_add_thread_device_task(
        self,
        *,
        pskd: str,
        eui: str | None = None,
        discerner: str | None = None,
        joiner_id: str | None = None,
        timeout: int | None = None,
        raw: bool = True,
    ) -> Any:
        return super().enqueue_add_thread_device_task(
            pskd=pskd,
            eui=eui,
            discerner=discerner,
            joiner_id=joiner_id,
            timeout=timeout,
            raw=raw,
        )

    def enqueue_get_network_diagnostic_task(
        self,
        *,
        destination: str,
        types: Sequence[str | int],
        timeout: int | None = None,
        destination_type: str | None = None,
        raw: bool = True,
    ) -> Any:
        return super().enqueue_get_network_diagnostic_task(
            destination=destination,
            types=types,
            timeout=timeout,
            destination_type=destination_type,
            raw=raw,
        )

    def enqueue_reset_network_diag_counter_task(
        self,
        *,
        types: Sequence[str | int],
        destination: str | None = None,
        timeout: int | None = None,
        destination_type: str | None = None,
        raw: bool = True,
    ) -> Any:
        return super().enqueue_reset_network_diag_counter_task(
            types=types,
            destination=destination,
            timeout=timeout,
            destination_type=destination_type,
            raw=raw,
        )

    def enqueue_get_energy_scan_task(
        self,
        *,
        destination: str,
        channel_mask: Sequence[int],
        count: int,
        period: int,
        scan_duration: int,
        timeout: int,
        destination_type: str | None = None,
        raw: bool = True,
    ) -> Any:
        return super().enqueue_get_energy_scan_task(
            destination=destination,
            channel_mask=channel_mask,
            count=count,
            period=period,
            scan_duration=scan_duration,
            timeout=timeout,
            destination_type=destination_type,
            raw=raw,
        )

    def enqueue_update_device_collection_task(
        self,
        *,
        max_age: int,
        max_retries: int,
        device_count: int,
        timeout: int,
        raw: bool = True,
    ) -> Any:
        return super().enqueue_update_device_collection_task(
            max_age=max_age,
            max_retries=max_retries,
            device_count=device_count,
            timeout=timeout,
            raw=raw,
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