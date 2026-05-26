from __future__ import annotations

import json
import logging
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Reference: https://github.com/openthread/ot-br-posix/blob/main/src/rest/openapi.yaml

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8081
DEFAULT_TIMEOUT = 10
DEFAULT_RETRIES = 3
DEFAULT_ACCEPT = "application/vnd.api+json"
JSON_CONTENT_TYPES = {
    "application/json",
    "application/vnd.api+json",
}


@dataclass(frozen=True)
class OTBRErrorDetail:
    title: str
    status: int | None = None
    detail: str | None = None
    links: Any | None = None


class OTBRClientError(Exception):
    """Base exception for OTBR REST client failures."""


class OTBRConnectionError(OTBRClientError):
    """Raised when the OTBR server cannot be reached."""


class OTBRInvalidResponseError(OTBRClientError):
    """Raised when the OTBR server returns an unexpected payload."""


class OTBRUsageError(OTBRClientError):
    """Raised when client-side input is invalid before any request is sent."""


class OTBRHTTPError(OTBRClientError):
    """Raised when the OTBR server returns an HTTP error status."""

    def __init__(
        self,
        status_code: int,
        reason: str,
        url: str,
        errors: Sequence[OTBRErrorDetail] | None = None,
        payload: Any | None = None,
        body: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.reason = reason
        self.url = url
        self.errors = list(errors or [])
        self.payload = payload
        self.body = body

        message = f"HTTP {status_code} {reason} for {url}"
        if self.errors:
            detail_parts = []
            for error in self.errors:
                segment = error.title
                if error.detail:
                    segment = f"{segment}: {error.detail}"
                detail_parts.append(segment)
            message = f"{message} ({'; '.join(detail_parts)})"

        super().__init__(message)


# ---------------------------------------------------------------------------
# Action Lifecycle Exception Types
# ---------------------------------------------------------------------------

class OTBRActionError(OTBRClientError):
    """Base for action execution errors."""

    def __init__(self, message: str, action_id: str, status: str, action: Any = None) -> None:
        self.action_id = action_id
        self.status = status
        self.action = action
        super().__init__(message)


class OTBRActionFailedError(OTBRActionError):
    """Raised when an action reaches status 'failed' or 'stopped'."""


class OTBRActionTimeoutError(OTBRActionError):
    """Raised when wait_for_action() exceeds its wall-clock timeout."""


# ---------------------------------------------------------------------------
# TLV Catalog & Protocol Constants
# ---------------------------------------------------------------------------

# 1.1 – Standard network-diagnostic TLV name constants (mirrors diagnostic_types.hpp)
DIAG_TLV_EXT_ADDRESS = "extAddress"        # TLV 0
DIAG_TLV_RLOC16 = "rloc16"             # TLV 1
DIAG_TLV_MODE = "mode"               # TLV 2
DIAG_TLV_TIMEOUT = "timeout"            # TLV 3 (omittable)
DIAG_TLV_CONNECTIVITY = "connectivity"       # TLV 4
DIAG_TLV_ROUTE = "route"              # TLV 5
DIAG_TLV_LEADER_DATA = "leaderData"         # TLV 6
DIAG_TLV_NETWORK_DATA = "networkData"        # TLV 7
DIAG_TLV_IPV6_ADDRESSES = "ipv6Addresses"      # TLV 8
DIAG_TLV_MAC_COUNTERS = "macCounters"        # TLV 9 (resettable)
DIAG_TLV_BATTERY_LEVEL = "batteryLevel"       # TLV 14 (omittable)
DIAG_TLV_SUPPLY_VOLTAGE = "supplyVoltage"      # TLV 15 (omittable)
DIAG_TLV_CHILD_TABLE = "childTable"         # TLV 16
DIAG_TLV_CHANNEL_PAGES = "channelPages"       # TLV 17
DIAG_TLV_MAX_CHILD_TIMEOUT = "maxChildTimeout"    # TLV 19 (omittable)
DIAG_TLV_LDEV_ID_SUBJECT = "lDevIdSubject"      # TLV 20
DIAG_TLV_IDEV_ID_CERT = "iDevIdCert"         # TLV 21
DIAG_TLV_EUI64 = "eui64"              # TLV 23
DIAG_TLV_VERSION = "version"            # TLV 24
DIAG_TLV_VENDOR_NAME = "vendorName"         # TLV 25
DIAG_TLV_VENDOR_MODEL = "vendorModel"        # TLV 26
DIAG_TLV_VENDOR_SW_VERSION = "vendorSwVersion"    # TLV 27
DIAG_TLV_THREAD_STACK_VER = "threadStackVersion"  # TLV 28
DIAG_TLV_MLE_COUNTERS = "mleCounters"        # TLV 34 (resettable)

# Mesh-diagnostic query TLVs (require additional otMeshDiag round-trip, slower)
DIAG_TLV_CHILDREN = "children"           # TLV 29
DIAG_TLV_CHILD_IPV6_ADDRS = "childIpv6Addresses"  # TLV 30
DIAG_TLV_ROUTER_NEIGHBORS = "routerNeighbors"    # TLV 31

# 1.2 – Recommended TLV preset lists

# Comprehensive set for per-device diagnostics (no mesh-diag query types)
RECOMMENDED_DIAGNOSTIC_TLVS: list[str] = [
    DIAG_TLV_EXT_ADDRESS,
    DIAG_TLV_RLOC16,
    DIAG_TLV_MODE,
    DIAG_TLV_IPV6_ADDRESSES,
    DIAG_TLV_MAC_COUNTERS,
    DIAG_TLV_MLE_COUNTERS,
    DIAG_TLV_CHILD_TABLE,
    DIAG_TLV_THREAD_STACK_VER,
    DIAG_TLV_EUI64,
    DIAG_TLV_VERSION,
    DIAG_TLV_VENDOR_NAME,
    DIAG_TLV_VENDOR_MODEL,
    DIAG_TLV_VENDOR_SW_VERSION,
    DIAG_TLV_CONNECTIVITY,
    DIAG_TLV_ROUTE,
    DIAG_TLV_LEADER_DATA
#    DIAG_TLV_CHANNEL_PAGES,
]

# Includes mesh-diag query types for full topology detail (slower)
FULL_DIAGNOSTIC_TLVS: list[str] = RECOMMENDED_DIAGNOSTIC_TLVS + [
    DIAG_TLV_CHILDREN,
    DIAG_TLV_CHILD_IPV6_ADDRS,
    DIAG_TLV_ROUTER_NEIGHBORS,
]

# Minimal lightweight set for quick enumeration
MINIMAL_DIAGNOSTIC_TLVS: list[str] = [
    DIAG_TLV_EXT_ADDRESS,
    DIAG_TLV_RLOC16,
    DIAG_TLV_MODE,
    DIAG_TLV_IPV6_ADDRESSES,
    DIAG_TLV_EUI64,
    DIAG_TLV_THREAD_STACK_VER,
]

# Minimal lightweight set for quick enumeration
BASIC_DIAGNOSTIC_TLVS: list[str] = [
    DIAG_TLV_EXT_ADDRESS,
    DIAG_TLV_RLOC16,
    DIAG_TLV_MODE,
    DIAG_TLV_IPV6_ADDRESSES,
    DIAG_TLV_EUI64
]

# Mesh-diagnostic TLVs as a frozenset for validation
MESH_DIAGNOSTIC_TLVS: frozenset[str] = frozenset({
    DIAG_TLV_CHILDREN,
    DIAG_TLV_CHILD_IPV6_ADDRS,
    DIAG_TLV_ROUTER_NEIGHBORS,
})

# Only these TLVs can be reset via resetNetworkDiagCounterTask (server enforces this)
RESETTABLE_DIAGNOSTIC_TLVS: frozenset[str] = frozenset({
    DIAG_TLV_MAC_COUNTERS,   # TLV 9
    DIAG_TLV_MLE_COUNTERS,   # TLV 34
})

# 1.3 – Protocol string constants


class ActionStatus:
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"
    # addThreadDeviceTask-specific
    UNDISCOVERED = "undiscovered"
    ATTEMPTED = "attempted"

    TERMINAL: frozenset[str] = frozenset({COMPLETED, STOPPED, FAILED})


class DestinationType:
    EXTENDED   = "extended"  # extAddress, 16-char hex — wire value: "extended"
    ML_EID_IID = "mleid"     # Mesh-Local EID IID, 16-char hex — wire value: "mleid"
    RLOC       = "rloc"      # RLOC16, 6-char hex (e.g. "f000") — wire value: "rloc"


class DeviceType:
    THREAD_DEVICE = "threadDevice"
    THREAD_BORDER_ROUTER = "threadBorderRouter"


class DiagnosticType:
    NETWORK_DIAGNOSTICS = "networkDiagnostics"
    ENERGY_SCAN_REPORT = "energyScanReport"


class ActionType:
    ADD_THREAD_DEVICE        = "addThreadDeviceTask"
    GET_NETWORK_DIAGNOSTIC   = "getNetworkDiagnosticTask"
    RESET_DIAG_COUNTERS      = "resetNetworkDiagCounterTask"
    GET_ENERGY_SCAN          = "getEnergyScanTask"
    UPDATE_DEVICE_COLLECTION = "updateDeviceCollectionTask"
    # discoverThreadNetworksTask — listed as TODO in openapi.yaml; not yet implemented on server


# ---------------------------------------------------------------------------
# Sentinel used by _resolve_raw: means "use instance default_raw, not an explicit value"
_RAW_UNSET = object()


class OTBRRestApiClient:
    """Minimal OTBR REST client with flattened JSON:API responses by default."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        base_url: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        accept: str = DEFAULT_ACCEPT,
        user_agent: str = "td-otbr-restapi-client/1.0",
        default_raw: bool = False,
    ) -> None:
        self.base_url = (base_url or f"http://{host}:{port}").rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.accept = accept
        self.user_agent = user_agent
        self._default_raw = default_raw

    def _resolve_raw(self, raw: object) -> bool:
        """Resolve the raw parameter: if _RAW_UNSET, use the instance default_raw."""
        if raw is _RAW_UNSET:
            return self._default_raw
        return bool(raw)

    def get_node(
        self,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        *,
        raw: object = _RAW_UNSET,
    ) -> Any:
        raw = self._resolve_raw(raw)
        return self._request(
            "/api/node",
            query=self._build_fields_query(fields),
            raw=raw,
        )

    def get_node_state(self) -> str:
        return self._request("/node/state", accept="application/json")

    def set_node_state(self, value: str) -> Any:
        normalized = value.strip().lower()
        if normalized not in {"enable", "disable"}:
            raise OTBRUsageError("value must be 'enable' or 'disable'")
        return self._request(
            "/node/state",
            method="PUT",
            data=normalized,
            accept="application/json",
            content_type="application/json",
            raw=True,
        )

    def get_node_ba_id(self) -> str:
        return self._request("/node/ba-id", accept="application/json", raw=True)

    def get_node_rloc(self) -> str:
        return self._request("/node/rloc", accept="application/json", raw=True)

    def get_node_rloc16(self) -> int:
        return self._request("/node/rloc16", accept="application/json", raw=True)

    def get_node_ext_address(self) -> str:
        return self._request("/node/ext-address", accept="application/json", raw=True)

    def get_node_network_name(self) -> str:
        return self._request("/node/network-name", accept="application/json", raw=True)

    def get_node_leader_data(self) -> dict:
        return self._request("/node/leader-data", accept="application/json", raw=True)

    def get_node_ext_panid(self) -> str:
        return self._request("/node/ext-panid", accept="application/json", raw=True)

    def get_node_num_of_router(self) -> int:
        return self._request("/node/num-of-router", accept="application/json", raw=True)

    def get_node_coprocessor_version(self) -> str:
        return self._request("/node/coprocessor/version", accept="application/json", raw=True)

    def get_pending_dataset(self, *, plain_text: bool = False, raw: object = _RAW_UNSET) -> Any:
        raw = self._resolve_raw(raw)
        accept = "text/plain" if plain_text else "application/json"
        return self._request("/node/dataset/pending", accept=accept, raw=raw)

    def set_pending_dataset(self, dataset: Mapping[str, Any] | str) -> Any:
        if isinstance(dataset, str):
            content_type = "text/plain"
            body: Any = dataset
        else:
            content_type = "application/json"
            body = dataset
        return self._request(
            "/node/dataset/pending",
            method="PUT",
            data=body,
            accept="application/json",
            content_type=content_type,
            raw=True,
        )

    def get_commissioner_state(self) -> str:
        return self._request("/node/commissioner/state", accept="application/json", raw=True)

    def get_active_dataset(self, *, plain_text: bool = False, raw: object = _RAW_UNSET) -> Any:
        raw = self._resolve_raw(raw)
        accept = "text/plain" if plain_text else "application/json"
        return self._request("/node/dataset/active", accept=accept, raw=raw)

    def set_active_dataset(self, dataset: Mapping[str, Any] | str) -> Any:
        if isinstance(dataset, str):
            content_type = "text/plain"
            body: Any = dataset
        else:
            content_type = "application/json"
            body = dataset

        return self._request(
            "/node/dataset/active",
            method="PUT",
            data=body,
            accept="application/json",
            content_type=content_type,
            raw=True,
        )

    def list_devices(
        self,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        *,
        raw: object = _RAW_UNSET,
        with_meta: bool = False,
    ) -> Any:
        raw = self._resolve_raw(raw)
        return self._request(
            "/api/devices",
            query=self._build_fields_query(fields),
            raw=raw,
            with_meta=with_meta,
        )

    def get_device(
        self,
        device_id: str,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        *,
        raw: object = _RAW_UNSET,
    ) -> Any:
        raw = self._resolve_raw(raw)
        return self._request(
            f"/api/devices/{device_id}",
            query=self._build_fields_query(fields),
            raw=raw,
        )

    def list_diagnostics(
        self,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        *,
        raw: object = _RAW_UNSET,
        with_meta: bool = False,
    ) -> Any:
        raw = self._resolve_raw(raw)
        return self._request(
            "/api/diagnostics",
            query=self._build_fields_query(fields),
            raw=raw,
            with_meta=with_meta,
        )

    def get_diagnostic(self, diagnostics_id: str, *, raw: object = _RAW_UNSET) -> Any:
        raw = self._resolve_raw(raw)
        return self._request(f"/api/diagnostics/{diagnostics_id}", raw=raw)

    def list_actions(
        self,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        *,
        raw: object = _RAW_UNSET,
        with_meta: bool = False,
    ) -> Any:
        raw = self._resolve_raw(raw)
        return self._request(
            "/api/actions",
            query=self._build_fields_query(fields),
            raw=raw,
            with_meta=with_meta,
        )

    def get_action(
        self,
        action_id: str,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        *,
        raw: object = _RAW_UNSET,
    ) -> Any:
        raw = self._resolve_raw(raw)
        return self._request(
            f"/api/actions/{action_id}",
            query=self._build_fields_query(fields),
            raw=raw,
        )

    # -----------------------------------------------------------------------
    # DELETE methods
    # -----------------------------------------------------------------------

    def delete_all_actions(self) -> None:
        self._request("/api/actions", method="DELETE", raw=True)

    def delete_all_devices(self) -> None:
        self._request("/api/devices", method="DELETE", raw=True)

    def delete_device(self, device_id: str) -> None:
        self._validate_non_empty_string(device_id, "device_id")
        self._request(f"/api/devices/{device_id}", method="DELETE", raw=True)

    def delete_all_diagnostics(self) -> None:
        self._request("/api/diagnostics", method="DELETE", raw=True)

    def delete_diagnostic(self, diagnostics_id: str) -> None:
        self._validate_non_empty_string(diagnostics_id, "diagnostics_id")
        self._request(f"/api/diagnostics/{diagnostics_id}", method="DELETE", raw=True)

    def factory_reset_node(self) -> None:
        """DELETE /node — performs a factory reset of the Thread node.

        WARNING: This is a destructive, irreversible operation. It wipes all
        Thread network configuration and device state on the border router.
        """
        self._request("/node", method="DELETE", raw=True)

    def enqueue_actions(
        self, tasks: Sequence[Mapping[str, Any]], *, raw: object = _RAW_UNSET
    ) -> Any:
        raw = self._resolve_raw(raw)
        payload = {"data": list(tasks)}
        return self._request(
            "/api/actions",
            method="POST",
            data=payload,
            accept="application/vnd.api+json",
            content_type="application/vnd.api+json",
            raw=raw,
        )

    def enqueue_add_thread_device_task(
        self,
        *,
        pskd: str,
        eui: str | None = None,
        discerner: str | None = None,
        joiner_id: str | None = None,
        timeout: int | None = None,
        raw: object = _RAW_UNSET,
    ) -> Any:
        raw = self._resolve_raw(raw)
        identity_fields = [value for value in (
            eui, discerner, joiner_id) if value]
        if len(identity_fields) != 1:
            raise OTBRUsageError(
                "exactly one of eui, discerner, or joiner_id is required"
            )

        self._validate_non_empty_string(pskd, "pskd")

        attributes: dict[str, Any] = {"pskd": pskd}
        if eui:
            attributes["eui"] = eui
        if discerner:
            attributes["discerner"] = discerner
        if joiner_id:
            attributes["joinerId"] = joiner_id
        if timeout is not None:
            attributes["timeout"] = timeout

        return self.enqueue_actions(
            [{"type": "addThreadDeviceTask", "attributes": attributes}],
            raw=raw,
        )

    def enqueue_get_network_diagnostic_task(
        self,
        *,
        destination: str,
        types: Sequence[str | int],
        timeout: int | None = None,
        destination_type: str | None = None,
        raw: object = _RAW_UNSET,
    ) -> Any:
        raw = self._resolve_raw(raw)
        self._validate_non_empty_string(destination, "destination")
        attributes = self._build_destination_attributes(
            destination=destination,
            destination_type=destination_type,
        )
        attributes["types"] = self._validate_non_empty_sequence(types, "types")
        if timeout is not None:
            attributes["timeout"] = timeout

        return self.enqueue_actions(
            [{"type": "getNetworkDiagnosticTask", "attributes": attributes}],
            raw=raw,
        )

    def enqueue_reset_network_diag_counter_task(
        self,
        *,
        types: Sequence[str | int],
        destination: str | None = None,
        timeout: int | None = None,
        destination_type: str | None = None,
        raw: object = _RAW_UNSET,
    ) -> Any:
        raw = self._resolve_raw(raw)
        validated = self._validate_non_empty_sequence(types, "types")
        non_resettable = [
            t for t in validated
            if isinstance(t, str) and t not in RESETTABLE_DIAGNOSTIC_TLVS
        ]
        if non_resettable:
            raise OTBRUsageError(
                f"Non-resettable TLV(s): {non_resettable!r}. "
                f"Only {sorted(RESETTABLE_DIAGNOSTIC_TLVS)!r} can be reset."
            )
        attributes: dict[str, Any] = {"types": validated}
        if destination is not None:
            attributes.update(
                self._build_destination_attributes(
                    destination=destination,
                    destination_type=destination_type,
                )
            )
        if timeout is not None:
            attributes["timeout"] = timeout

        return self.enqueue_actions(
            [{"type": "resetNetworkDiagCounterTask", "attributes": attributes}],
            raw=raw,
        )

    def enqueue_get_energy_scan_task(
        self,
        *,
        destination: str,
        channel_mask: Sequence[int],
        count: int | None = None,
        period: int | None = None,
        scan_duration: int | None = None,
        timeout: int | None = None,
        destination_type: str | None = None,
        raw: object = _RAW_UNSET,
    ) -> Any:
        raw = self._resolve_raw(raw)
        self._validate_non_empty_string(destination, "destination")
        attributes = self._build_destination_attributes(
            destination=destination,
            destination_type=destination_type,
        )
        attributes["channelMask"] = self._validate_non_empty_sequence(
            channel_mask, "channel_mask"
        )
        if count is not None:
            attributes["count"] = count
        if period is not None:
            attributes["period"] = period
        if scan_duration is not None:
            attributes["scanDuration"] = scan_duration
        if timeout is not None:
            attributes["timeout"] = timeout

        return self.enqueue_actions(
            [{"type": "getEnergyScanTask", "attributes": attributes}],
            raw=raw,
        )

    def enqueue_update_device_collection_task(
        self,
        *,
        max_age: int,
        max_retries: int,
        device_count: int,
        timeout: int,
        raw: object = _RAW_UNSET,
    ) -> Any:
        raw = self._resolve_raw(raw)
        attributes = {
            "maxAge": max_age,
            "maxRetries": max_retries,
            "deviceCount": device_count,
            "timeout": timeout,
        }

        return self.enqueue_actions(
            [{"type": "updateDeviceCollectionTask", "attributes": attributes}],
            raw=raw,
        )

    # -----------------------------------------------------------------------
    # Action Lifecycle: Polling Helper
    # -----------------------------------------------------------------------

    def wait_for_action(
        self,
        action_id: str,
        *,
        poll_interval: float = 2.0,
        poll_timeout: float = 120.0,
        raise_on_stopped: bool = True,
        raw: object = _RAW_UNSET,
    ) -> Any:
        """
        Poll GET /api/actions/{action_id} until the action reaches a terminal
        status (completed, stopped, or failed), then return the action item.

        Args:
            action_id: UUID returned when the action was enqueued.
            poll_interval: Seconds between polls (default 2.0).
            poll_timeout: Wall-clock seconds before raising OTBRActionTimeoutError
                          (default 120.0).
            raise_on_stopped: If True (default), raise OTBRActionFailedError when
                              status is 'stopped' or 'failed'.
            raw: If True, return raw JSON:API envelope; else return flattened item.

        Returns:
            The action item dict at terminal state.

        Raises:
            OTBRActionTimeoutError: poll_timeout exceeded.
            OTBRActionFailedError: Action stopped or failed (when raise_on_stopped=True).
            OTBRConnectionError, OTBRHTTPError, OTBRInvalidResponseError: propagated.
        """
        raw = self._resolve_raw(raw)
        deadline = time.monotonic() + poll_timeout

        while True:
            action = self.get_action(action_id, raw=raw)

            if raw:
                data_node = action.get("data") if isinstance(
                    action, dict) else None
                attrs = data_node.get("attributes", {}) if isinstance(
                    data_node, dict) else {}
                status = attrs.get("status")
            else:
                status = action.get("status") if isinstance(
                    action, dict) else None

            if status is None:
                raise OTBRInvalidResponseError(
                    f"Action {action_id} response has no 'status' field; "
                    "server response may be malformed or missing attributes"
                )

            if status in ActionStatus.TERMINAL:
                if raise_on_stopped and status in (ActionStatus.STOPPED, ActionStatus.FAILED):
                    raise OTBRActionFailedError(
                        f"Action {action_id} ended with status '{status}'",
                        action_id=action_id,
                        status=status,
                        action=action,
                    )
                return action

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OTBRActionTimeoutError(
                    f"Action {action_id} did not complete within {poll_timeout}s",
                    action_id=action_id,
                    status=status or "unknown",
                    action=action,
                )

            time.sleep(min(poll_interval, remaining))

    # -----------------------------------------------------------------------
    # Device Collection Workflow Methods
    # -----------------------------------------------------------------------

    def trigger_and_wait_device_collection(
        self,
        *,
        device_count: int = 255,
        max_age: int = 60,
        max_retries: int = 2,
        task_timeout: int = 6, 
        poll_interval: float = 2.0,
        poll_timeout: float = 6.0,
        raise_on_stopped: bool = False,
        raw: object = _RAW_UNSET,
    ) -> Any:
        """
        Enqueue an updateDeviceCollectionTask, wait for completion, and return
        the action item.

        Does NOT return the device list itself — call list_devices() after this
        to retrieve devices. Use fetch_device_collection() for the combined
        enqueue + wait + list workflow.

        Args:
            device_count: Maximum number of devices to discover.
            max_age: Maximum age (seconds) for cached device entries.
            max_retries: Maximum retries per device.
            task_timeout: Task timeout passed to the server (seconds).
            poll_interval: Seconds between status polls.
            poll_timeout: Wall-clock seconds before OTBRActionTimeoutError.
            raise_on_stopped: If True, raise OTBRActionFailedError on stopped/failed.
            raw: Return raw action item.
        """
        raw = self._resolve_raw(raw)
        enqueued = self.enqueue_update_device_collection_task(
            max_age=max_age,
            max_retries=max_retries,
            device_count=device_count,
            timeout=task_timeout,
            raw=False,
        )
        # enqueued is a list of flattened action items
        action_id: str = enqueued[0]["id"]

        return self.wait_for_action(
            action_id,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raise_on_stopped=raise_on_stopped,
            raw=raw,
        )

    def fetch_device_collection(
        self,
        *,
        device_count: int = 255,
        max_age: int = 60,
        max_retries: int = 2,
        task_timeout: int = 6,
        poll_interval: float = 2.0,
        poll_timeout: float = 6.0,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        with_meta: bool = False,
        raw: object = _RAW_UNSET,
    ) -> Any:
        """
        Convenience workflow: enqueue updateDeviceCollectionTask → wait for
        completion → return the device list.

        Equivalent to:
            trigger_and_wait_device_collection(...)
            list_devices(fields=fields, with_meta=with_meta, raw=raw)
        """
        raw = self._resolve_raw(raw)
        try:
            action = self.trigger_and_wait_device_collection(
                device_count=device_count,
                max_age=max_age,
                max_retries=max_retries,
                task_timeout=task_timeout,
                poll_interval=poll_interval,
                poll_timeout=poll_timeout,
                raise_on_stopped=False,
                raw=False,
            )
            status = action.get("status") if isinstance(action, dict) else None
            if status in (ActionStatus.STOPPED, ActionStatus.FAILED):
                logging.warning(
                    "updateDeviceCollectionTask ended with status '%s'; "
                    "returning partial device list",
                    status,
                )
        except OTBRActionTimeoutError as exc:
            logging.warning(
                "updateDeviceCollectionTask timed out (%s); "
                "returning partial device list",
                exc,
            )

        return self.list_devices(fields=fields, with_meta=with_meta, raw=raw)

    # -----------------------------------------------------------------------
    # Network Diagnostics Workflow Methods
    # -----------------------------------------------------------------------

    def fetch_device_diagnostics(
        self,
        device_id: str,
        *,
        types: Sequence[str | int] = RECOMMENDED_DIAGNOSTIC_TLVS,
        destination_type: str = DestinationType.EXTENDED,
        task_timeout: int = 6,
        poll_interval: float = 2.0,
        poll_timeout: float = 6.0,
        raw: object = _RAW_UNSET,
    ) -> Any:
        """
        Enqueue getNetworkDiagnosticTask for device_id, wait for completion,
        then fetch and return the resulting diagnostic item from /api/diagnostics.

        Args:
            device_id: Device extAddress (16-char hex), the item ID from /api/devices.
            types: TLV name list. Defaults to RECOMMENDED_DIAGNOSTIC_TLVS.
            destination_type: Addressing mode. Use DestinationType.EXTENDED (default)
                              for device extAddress IDs.
            task_timeout: Server-side task timeout in seconds (default 5s).
            poll_interval: Seconds between action status polls.
            poll_timeout: Wall-clock seconds before OTBRActionTimeoutError is raised.
            raw: If True, return raw JSON:API envelope for the diagnostic item.

        Returns:
            Flattened diagnostic item dict (or raw envelope when raw=True).

        Raises:
            OTBRActionFailedError: Action stopped or failed.
            OTBRActionTimeoutError: Polling timed out.
            OTBRHTTPError: HTTP-level error from server.
            OTBRConnectionError: Server unreachable.
        """
        raw = self._resolve_raw(raw)
        enqueued = self.enqueue_get_network_diagnostic_task(
            destination=device_id,
            types=list(types),
            timeout=task_timeout,
            destination_type=destination_type,
            raw=False,
        )
        action_id: str = enqueued[0]["id"]

        action = self.wait_for_action(
            action_id,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raise_on_stopped=True,
        )

        result_id = extract_action_result_id(action)
        if not result_id:
            msg = f"Completed action {action_id} has no result relationship"
            if destination_type != DestinationType.EXTENDED:
                msg += (
                    f" (server bug: destinationType='{destination_type}' triggers"
                    " uninitialized extAddr in FillDiagnosticCollection —"
                    " diagnostic data was discarded; use destinationType='extended'"
                    " with the device extAddress as device_id to work around this)"
                )
            raise OTBRInvalidResponseError(msg)

        return self.get_diagnostic(result_id, raw=raw)

    def fetch_all_devices_diagnostics(
        self,
        device_ids: Sequence[str],
        *,
        types: Sequence[str | int] = RECOMMENDED_DIAGNOSTIC_TLVS,
        destination_type: str = DestinationType.EXTENDED,
        task_timeout: int = 6,
        poll_interval: float = 2.0,
        poll_timeout: float = 6.0,
        skip_on_failure: bool = True,
        on_progress: Callable[[int, int, str, float, str], None] | None = None,
        raw: object = _RAW_UNSET,
    ) -> list[Any]:
        """
        Fetch diagnostics for a list of device IDs, one device at a time.

        Args:
            device_ids: List of device extAddress strings.
            types: TLV name list.
            destination_type: Addressing mode for all devices.
            task_timeout: Server-side task timeout per device.
            poll_interval: Seconds between polls per device action.
            poll_timeout: Wall-clock seconds per device before timeout.
            skip_on_failure: If True (default), log and skip devices that fail or
                             time out; if False, raise on first failure.
            raw: Return raw diagnostic envelopes.

        Returns:
            List of diagnostic items, one per successfully queried device.
            Failed devices are omitted when skip_on_failure=True.
        """
        raw = self._resolve_raw(raw)
        results: list[Any] = []
        total = len(device_ids)
        for idx, device_id in enumerate(device_ids, start=1):
            t_start = time.monotonic()
            status = "completed"
            try:
                logging.debug("Fetching diagnostics for device %s (%d/%d) types: %s", device_id, idx, total, " ".join(map(str, types)))
                diag = self.fetch_device_diagnostics(
                    device_id,
                    types=types,
                    destination_type=destination_type,
                    task_timeout=task_timeout,
                    poll_interval=poll_interval,
                    poll_timeout=poll_timeout,
                    raw=raw,
                )
                results.append(diag)
            except (OTBRActionFailedError, OTBRActionTimeoutError) as exc:
                status = "skipped"
                if not skip_on_failure:
                    raise
                logging.warning(
                    "Skipping device %s: %s", device_id, exc
                )
            finally:
                if on_progress is not None:
                    on_progress(idx, total, device_id, time.monotonic() - t_start, status)
        return results

    def fetch_network_diagnostics_all_devices(
        self,
        *,
        update_devices: bool = True,
        device_count: int = 200,
        types: Sequence[str | int] = RECOMMENDED_DIAGNOSTIC_TLVS,
        destination_type: str = DestinationType.EXTENDED,
        task_timeout: int = 6,
        poll_interval: float = 2.0,
        poll_timeout: float = 6.0,
        skip_on_failure: bool = True,
        raw: object = _RAW_UNSET,
    ) -> tuple[list[Any], list[Any]]:
        """
        Full workflow:
        1. Optionally trigger updateDeviceCollectionTask and wait for it.
        2. GET /api/devices to get the device list.
        3. For each device, enqueue getNetworkDiagnosticTask, wait, fetch result.

        Returns:
            Tuple of (devices, diagnostics):
            - devices: list of device items from /api/devices
            - diagnostics: list of diagnostic items, one per device that responded
        """
        raw = self._resolve_raw(raw)
        if update_devices:
            devices = self.fetch_device_collection(
                device_count=device_count, raw=False)
        else:
            devices = self.list_devices(raw=False)

        device_ids = [d["id"]
                      for d in devices if isinstance(d, dict) and d.get("id")]

        diagnostics = self.fetch_all_devices_diagnostics(
            device_ids,
            types=types,
            destination_type=destination_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            skip_on_failure=skip_on_failure,
            raw=raw,
        )

        return devices, diagnostics

    # -----------------------------------------------------------------------
    # Mesh Diagnostics Method
    # -----------------------------------------------------------------------

    def fetch_mesh_diagnostics(
        self,
        device_id: str,
        *,
        types: Sequence[str] = (
            DIAG_TLV_CHILDREN,
            DIAG_TLV_CHILD_IPV6_ADDRS,
            DIAG_TLV_ROUTER_NEIGHBORS,
        ),
        destination_type: str = DestinationType.EXTENDED,
        task_timeout: int = 6,
        poll_interval: float = 2.0,
        poll_timeout: float = 6.0,
        raw: object = _RAW_UNSET,
    ) -> Any:
        """
        Enqueue getNetworkDiagnosticTask restricted to mesh-diagnostic TLVs
        (children, childIpv6Addresses, routerNeighbors), wait for completion,
        then fetch and return the resulting diagnostic item.

        These TLVs require an additional otMeshDiag round-trip on the server and
        have higher latency than standard diagnostic TLVs. The default task_timeout
        (5s) and poll_timeout (6s) reflect this.

        Args:
            device_id: Device extAddress (16-char hex), the item ID from /api/devices.
            types: Subset of {"children", "childIpv6Addresses", "routerNeighbors"}.
                   Defaults to all three. Passing any other TLV name raises OTBRUsageError.
            destination_type: Addressing mode. Defaults to DestinationType.EXTENDED.
            task_timeout: Server-side task timeout in seconds (default 5s).
            poll_interval: Seconds between action status polls (default 3.0).
            poll_timeout: Wall-clock seconds before OTBRActionTimeoutError (default 6.0).
            raw: If True, return raw JSON:API envelope.

        Returns:
            Flattened diagnostic item dict containing requested mesh-diagnostic fields
            (or raw envelope when raw=True).

        Raises:
            OTBRUsageError: Any item in types is not a mesh-diagnostic TLV.
            OTBRActionFailedError: Action stopped or failed.
            OTBRActionTimeoutError: Polling timed out.
            OTBRHTTPError, OTBRConnectionError: propagated from HTTP layer.
        """
        raw = self._resolve_raw(raw)
        invalid = [t for t in types if t not in MESH_DIAGNOSTIC_TLVS]
        if invalid:
            raise OTBRUsageError(
                f"Invalid mesh-diagnostic TLV(s): {invalid!r}. "
                f"Allowed: {sorted(MESH_DIAGNOSTIC_TLVS)!r}"
            )
        if not types:
            raise OTBRUsageError(
                "types must contain at least one mesh-diagnostic TLV")

        return self.fetch_device_diagnostics(
            device_id,
            types=list(types),
            destination_type=destination_type,
            task_timeout=task_timeout,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raw=raw,
        )

    def fetch_mesh_diagnostics_all_devices(
        self,
        device_ids: Sequence[str],
        *,
        types: Sequence[str] = (
            DIAG_TLV_CHILDREN,
            DIAG_TLV_CHILD_IPV6_ADDRS,
            DIAG_TLV_ROUTER_NEIGHBORS,
        ),
        destination_type: str = DestinationType.EXTENDED,
        task_timeout: int = 6,
        poll_interval: float = 2.0,
        poll_timeout: float = 6.0,
        skip_on_failure: bool = True,
        on_progress: Callable[[int, int, str, float, str], None] | None = None,
        raw: object = _RAW_UNSET,
    ) -> list[Any]:
        """
        Fetch mesh diagnostics for a list of device IDs, one device at a time.

        Thin wrapper: iterates device_ids and calls fetch_mesh_diagnostics() for each.
        Same skip_on_failure semantics as fetch_all_devices_diagnostics().
        """
        raw = self._resolve_raw(raw)
        results: list[Any] = []
        total = len(device_ids)
        for idx, device_id in enumerate(device_ids, start=1):
            t_start = time.monotonic()
            status = "completed"
            try:
                diag = self.fetch_mesh_diagnostics(
                    device_id,
                    types=types,
                    destination_type=destination_type,
                    task_timeout=task_timeout,
                    poll_interval=poll_interval,
                    poll_timeout=poll_timeout,
                    raw=raw,
                )
                results.append(diag)
            except (OTBRActionFailedError, OTBRActionTimeoutError) as exc:
                status = "skipped"
                if not skip_on_failure:
                    raise
                logging.warning(
                    "Skipping device %s (mesh diagnostics): %s", device_id, exc
                )
            finally:
                if on_progress is not None:
                    on_progress(idx, total, device_id, time.monotonic() - t_start, status)
        return results

    # -----------------------------------------------------------------------
    # Energy Scan Workflow Method
    # -----------------------------------------------------------------------

    def fetch_energy_scan(
        self,
        *,
        destination: str,
        channel_mask: Sequence[int],
        count: int | None = None,
        period: int | None = None,
        scan_duration: int | None = None,
        destination_type: str | None = None,
        task_timeout: int | None = None,
        poll_interval: float = 2.0,
        poll_timeout: float = 6.0,
        raw: object = _RAW_UNSET,
    ) -> Any:
        """
        Enqueue getEnergyScanTask, wait for completion, and return the
        resulting energyScanReport diagnostic item.

        Args:
            destination: Target device address (hex string).
            channel_mask: List of channel numbers to scan.
            count: Number of scans per channel (server default: 1).
            period: Time between scans in ms (server default: 32).
            scan_duration: Duration per channel scan in ms (server default: 0).
            destination_type: Addressing mode (default: server auto-detects).
            task_timeout: Server-side task timeout in seconds (default 5s).
            poll_interval: Seconds between action status polls.
            poll_timeout: Wall-clock seconds before OTBRActionTimeoutError (default 6s).
            raw: If True, return raw JSON:API envelope for the diagnostic item.

        Returns:
            Flattened energyScanReport diagnostic item (or raw envelope).

        Raises:
            OTBRActionFailedError: Action stopped or failed.
            OTBRActionTimeoutError: Polling timed out.
            OTBRInvalidResponseError: Completed action has no result relationship.
        """
        raw = self._resolve_raw(raw)
        enqueued = self.enqueue_get_energy_scan_task(
            destination=destination,
            channel_mask=channel_mask,
            count=count,
            period=period,
            scan_duration=scan_duration,
            timeout=task_timeout,
            destination_type=destination_type,
            raw=False,
        )
        action_id: str = enqueued[0]["id"]

        action = self.wait_for_action(
            action_id,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            raise_on_stopped=True,
        )

        result_id = extract_action_result_id(action)
        if not result_id:
            raise OTBRInvalidResponseError(
                f"Completed energy-scan action {action_id} has no result relationship"
            )
        return self.get_diagnostic(result_id, raw=raw)

    # -----------------------------------------------------------------------
    # Node Convenience Method
    # -----------------------------------------------------------------------

    def get_node_info(self) -> dict[str, Any]:
        """
        Fetch commonly-needed node attributes from the /api/node endpoint.

        Returns a flattened dict with rloc16, extAddress, mlEidIid, role, etc.
        Equivalent to get_node() with default (flattened) output.
        """
        result = self.get_node(raw=False)
        return result if isinstance(result, dict) else {}

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        query: Mapping[str, str] | None = None,
        data: Any | None = None,
        accept: str | None = None,
        content_type: str | None = None,
        raw: bool = False,
        with_meta: bool = False,
        timeout: int | None = None,
        retries: int | None = None,
    ) -> Any:
        url = self._build_url(path, query)
        body = self._encode_body(data, content_type)
        request = Request(
            url=url,
            data=body,
            headers=self._build_headers(
                accept=accept, content_type=content_type),
            method=method,
        )
        
        # Log request details for debugging
        logging.debug(
            "HTTP Request: method=%s, url=%s, headers=%s, body_len=%s",
            method,
            url,
            dict(request.headers),
            len(body) if body else 0,
        )
        if body:
            logging.debug("HTTP Request body: %s", body.decode("utf-8", errors="replace"))
        
        effective_retries = retries if retries is not None else self.retries
        last_exc: Exception | None = None
        last_exc_body: bytes = b""

        for attempt in range(max(1, effective_retries)):
            try:
                with urlopen(request, timeout=timeout or self.timeout) as response:
                    response_body = response.read()
                    media_type = self._parse_media_type(
                        response.headers.get("Content-Type")
                    )
                    
                    # Log response details for debugging
                    logging.debug(
                        "HTTP Response: status=%s, headers=%s, body_len=%s",
                        response.status,
                        dict(response.headers),
                        len(response_body),
                    )
                    if response_body:
                        logging.debug(
                            "HTTP Response body: %s",
                            response_body.decode("utf-8", errors="replace"),
                        )

                if not response_body:
                    return None

                payload = self._decode_response_body(response_body, media_type)
                if raw:
                    return payload

                return self._normalize_response_payload(
                    payload, media_type, with_meta=with_meta
                )
            except HTTPError as exc:
                if exc.code < 500:
                    # 4xx errors are not retried — re-raise immediately
                    error_body = exc.read()
                    media_type = self._parse_media_type(
                        exc.headers.get("Content-Type")
                    )
                    
                    # Log error response details for debugging
                    logging.debug(
                        "HTTP Error Response: status=%s, headers=%s, body_len=%s",
                        exc.code,
                        dict(exc.headers),
                        len(error_body),
                    )
                    if error_body:
                        logging.debug(
                            "HTTP Error Response body: %s",
                            error_body.decode("utf-8", errors="replace"),
                        )
                    
                    payload = None
                    body_text = None
                    if error_body:
                        body_text = error_body.decode(
                            "utf-8", errors="replace")
                        payload = self._parse_payload_from_text(
                            body_text, media_type)
                    raise OTBRHTTPError(
                        status_code=exc.code,
                        reason=exc.reason,
                        url=url,
                        errors=self._parse_error_details(
                            payload, exc.code, exc.reason
                        ),
                        payload=payload,
                        body=body_text,
                    ) from exc
                last_exc = exc
                last_exc_body = exc.read()
                logging.debug(
                    "HTTP Error Response: status=%s, headers=%s, body_len=%s (will retry)",
                    exc.code,
                    dict(exc.headers),
                    len(last_exc_body),
                )
                if last_exc_body:
                    logging.debug(
                        "HTTP Error Response body: %s",
                        last_exc_body.decode("utf-8", errors="replace"),
                    )
                logging.warning(
                    "HTTP %d on attempt %d/%d for %s",
                    exc.code,
                    attempt + 1,
                    effective_retries,
                    url,
                )
            except URLError as exc:
                last_exc = exc
                logging.warning(
                    "URLError on attempt %d/%d for %s: %s",
                    attempt + 1,
                    effective_retries,
                    url,
                    exc.reason,
                )

            if attempt < effective_retries - 1:
                time.sleep(2**attempt)

        if isinstance(last_exc, HTTPError):
            exc = last_exc
            error_body = last_exc_body  # body was cached during retry loop
            media_type = self._parse_media_type(
                exc.headers.get("Content-Type"))
            payload = None
            body_text = None
            if error_body:
                body_text = error_body.decode("utf-8", errors="replace")
                payload = self._parse_payload_from_text(body_text, media_type)
            raise OTBRHTTPError(
                status_code=exc.code,
                reason=exc.reason,
                url=url,
                errors=self._parse_error_details(
                    payload, exc.code, exc.reason),
                payload=payload,
                body=body_text,
            ) from last_exc
        raise OTBRConnectionError(
            f"Failed to reach OTBR API at {url}: {last_exc}"
        ) from last_exc

    def _build_url(self, path: str, query: Mapping[str, str] | None = None) -> str:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        return url

    def _build_headers(
        self, *, accept: str | None = None, content_type: str | None = None
    ) -> dict[str, str]:
        headers = {
            "Accept": accept or self.accept,
            "User-Agent": self.user_agent,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _encode_body(self, data: Any | None, content_type: str | None) -> bytes | None:
        if data is None:
            return None
        if content_type == "text/plain":
            if not isinstance(data, str):
                raise TypeError("text/plain request bodies must be strings")
            return data.encode("utf-8")
        if content_type in JSON_CONTENT_TYPES or content_type == "application/json":
            return json.dumps(data).encode("utf-8")
        raise OTBRUsageError(
            f"Unsupported request content type: {content_type}")

    def _decode_response_body(
        self, response_body: bytes, media_type: str | None
    ) -> Any:
        body_text = response_body.decode("utf-8", errors="replace")
        payload = self._parse_payload_from_text(body_text, media_type)
        if payload is None:
            return body_text
        return payload

    def _parse_payload_from_text(
        self, body_text: str, media_type: str | None
    ) -> Any | None:
        stripped = body_text.strip()
        if not stripped:
            return None
        if media_type in JSON_CONTENT_TYPES or stripped[0] in '[{"':
            try:
                return json.loads(body_text)
            except json.JSONDecodeError as exc:
                raise OTBRInvalidResponseError(
                    f"Invalid JSON response: {exc}") from exc
        return None

    def _normalize_response_payload(
        self, payload: Any, media_type: str | None, *, with_meta: bool
    ) -> Any:
        if media_type == "application/vnd.api+json" and isinstance(payload, dict):
            return self._flatten_jsonapi_document(payload, with_meta=with_meta)
        return payload

    def _flatten_jsonapi_document(
        self, payload: Mapping[str, Any], *, with_meta: bool
    ) -> Any:
        data = payload.get("data")
        if isinstance(data, list):
            items = [self._flatten_jsonapi_item(item) for item in data]
            if with_meta:
                return {"items": items, "meta": payload.get("meta")}
            return items
        if isinstance(data, dict):
            item = self._flatten_jsonapi_item(data)
            if with_meta and "meta" in payload:
                item["_meta"] = payload["meta"]
            return item
        return dict(payload)

    def _flatten_jsonapi_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        flattened = {
            "id": item.get("id"),
            "type": item.get("type"),
        }

        attributes = item.get("attributes")
        if isinstance(attributes, dict):
            flattened.update(attributes)

        relationships = item.get("relationships")
        if relationships:
            flattened["relationships"] = relationships

        meta = item.get("meta")
        if meta:
            flattened["_meta"] = meta

        links = item.get("links")
        if links:
            flattened["_links"] = links

        return flattened

    def _parse_error_details(
        self,
        payload: Any,
        status_code: int,
        reason: str,
    ) -> list[OTBRErrorDetail]:
        if isinstance(payload, dict):
            if isinstance(payload.get("errors"), list):
                details: list[OTBRErrorDetail] = []
                for error in payload["errors"]:
                    if isinstance(error, dict):
                        details.append(
                            OTBRErrorDetail(
                                title=str(error.get("title", reason)),
                                status=self._coerce_int(error.get("status"))
                                or status_code,
                                detail=error.get("detail"),
                                links=error.get("links"),
                            )
                        )
                if details:
                    return details

            if "title" in payload or "detail" in payload:
                return [
                    OTBRErrorDetail(
                        title=str(payload.get("title", reason)),
                        status=self._coerce_int(
                            payload.get("status")) or status_code,
                        detail=payload.get("detail"),
                        links=payload.get("links"),
                    )
                ]

        return [OTBRErrorDetail(title=reason, status=status_code)]

    def _build_fields_query(
        self,
        fields: Mapping[str, str | Sequence[str] | None] | None,
    ) -> dict[str, str] | None:
        if not fields:
            return None

        query: dict[str, str] = {}
        for resource_type, value in fields.items():
            key = f"fields[{resource_type}]"
            if value is None:
                query[key] = ""
            elif isinstance(value, str):
                query[key] = value
            else:
                query[key] = ",".join(value)
        return query

    _DEST_TYPE_LENGTHS: dict[str, int] = {
        "extended": 16,
        "mleid": 16,
        "rloc": 6,
    }

    def _build_destination_attributes(
        self,
        *,
        destination: str,
        destination_type: str | None = None,
    ) -> dict[str, Any]:
        self._validate_non_empty_string(destination, "destination")
        if destination_type and destination_type in self._DEST_TYPE_LENGTHS:
            expected = self._DEST_TYPE_LENGTHS[destination_type]
            if len(destination) != expected:
                raise OTBRUsageError(
                    f"destination must be {expected} hex chars for type "
                    f"'{destination_type}', got {len(destination)}"
                )
        attributes: dict[str, Any] = {"destination": destination}
        if destination_type:
            attributes["destinationType"] = destination_type
        return attributes

    def _validate_non_empty_sequence(
        self, values: Sequence[Any], field_name: str
    ) -> list[Any]:
        items = list(values)
        if not items:
            raise OTBRUsageError(
                f"{field_name} must contain at least one item")
        return items

    def _validate_non_empty_string(self, value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise OTBRUsageError(f"{field_name} must be a non-empty string")
        return value

    def _parse_media_type(self, content_type: str | None) -> str | None:
        if not content_type:
            return None
        return content_type.split(";", 1)[0].strip().lower()

    def _coerce_int(self, value: Any) -> int | None:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None


def extract_action_result_id(action: Any) -> str | None:
    """
    Extract the result item ID from a completed action item (flattened or raw).

    Works with both flattened items (where relationships is preserved as a dict)
    and raw JSON:API items (where the envelope structure is intact).

    Returns the result UUID string, or None if not present.
    """
    if not isinstance(action, dict):
        return None

    # Flattened form: action["relationships"]["result"]["data"]["id"]
    relationships = action.get("relationships")
    if isinstance(relationships, dict):
        result = relationships.get("result")
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, dict):
                result_id = data.get("id")
                # Treat empty string as absent: server bug (non-ext destinationType)
                # causes FillDiagnosticCollection() to discard the result and leave id="".
                if result_id:
                    return result_id

    # Raw JSON:API form: action["data"]["relationships"]["result"]["data"]["id"]
    data_node = action.get("data")
    if isinstance(data_node, dict):
        raw_relationships = data_node.get("relationships")
        if isinstance(raw_relationships, dict):
            result = raw_relationships.get("result")
            if isinstance(result, dict):
                inner_data = result.get("data")
                if isinstance(inner_data, dict):
                    # Treat empty string as absent (same server bug guard as above).
                    return inner_data.get("id") or None

    return None


def build_fields_mapping(items: Iterable[str] | None) -> dict[str, str] | None:
    """Convert CLI field selectors like 'threadDevice=hostname,role' into query mappings."""
    if not items:
        return None

    fields: dict[str, str] = {}
    for item in items:
        if "=" in item:
            resource_type, value = item.split("=", 1)
            fields[resource_type] = value
        else:
            fields[item] = ""
    return fields


def error_to_dict(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, OTBRHTTPError):
        return {
            "error": {
                "type": "http",
                "status": exc.status_code,
                "reason": exc.reason,
                "url": exc.url,
                "details": [detail.__dict__ for detail in exc.errors],
            }
        }
    if isinstance(exc, OTBRUsageError):
        return {"error": {"type": "usage", "message": str(exc)}}
    if isinstance(exc, OTBRConnectionError):
        return {"error": {"type": "connection", "message": str(exc)}}
    if isinstance(exc, OTBRInvalidResponseError):
        return {"error": {"type": "invalid-response", "message": str(exc)}}
    if isinstance(exc, OTBRActionTimeoutError):
        return {
            "error": {
                "type": "action-timeout",
                "action_id": exc.action_id,
                "status": exc.status,
                "message": str(exc),
            }
        }
    if isinstance(exc, OTBRActionFailedError):
        return {
            "error": {
                "type": "action-failed",
                "action_id": exc.action_id,
                "status": exc.status,
                "message": str(exc),
            }
        }
    if isinstance(exc, OTBRActionError):
        return {
            "error": {
                "type": "action-error",
                "action_id": exc.action_id,
                "status": exc.status,
                "message": str(exc),
            }
        }
    if isinstance(exc, OTBRClientError):
        return {"error": {"type": "client", "message": str(exc)}}
    return {"error": {"type": "unexpected", "message": str(exc)}}


# ---------------------------------------------------------------------------
# CLI Helper Functions
# ---------------------------------------------------------------------------

def add_common_rest_client_args(parser) -> None:
    """Add common OTBR REST API client arguments to an ArgumentParser.
    
    Adds the following standard arguments:
    - --host: OTBR REST API host (default: 127.0.0.1)
    - --port: OTBR REST API port (default: 8081)
    - --base-url: Override host/port with full base URL
    - --timeout: HTTP timeout in seconds (default: 10)
    - --accept: Accept header (default: application/vnd.api+json)
    - --datadir: Data directory for output files (optional)
    
    Args:
        parser: argparse.ArgumentParser or subparser to augment
    
    Usage Example:
        >>> import argparse
        >>> from otbr_restapi_util import add_common_rest_client_args
        >>> parser = argparse.ArgumentParser()
        >>> add_common_rest_client_args(parser)
        >>> args = parser.parse_args(['--host', '192.168.1.1', '--port', '8080'])
        >>> args.host
        '192.168.1.1'
        >>> args.port
        8080
    
    Notes:
        - The --base-url argument takes precedence over --host and --port when constructing the client
        - --accept defaults to JSON:API format but can be overridden
        - --datadir is optional and typically used for output file resolution
    """
    from td_const import TD_DATA_DIR_ARG_HELP
    
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"OTBR REST API host (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"OTBR REST API port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--base-url",
        help="Override host/port with a full base URL (e.g., http://10.0.0.1:8081)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--accept",
        default=DEFAULT_ACCEPT,
        help=f"Accept header for HTTP requests (default: {DEFAULT_ACCEPT})",
    )
    parser.add_argument(
        "--datadir",
        default=None,
        help=TD_DATA_DIR_ARG_HELP,
    )


def build_rest_client_from_args(args, **kwargs) -> OTBRRestApiClient:
    """Construct OTBRRestApiClient from parsed CLI arguments.
    
    Builds a client instance using standard arguments added by add_common_rest_client_args().
    Handles precedence: --base-url overrides --host and --port if provided.
    
    Args:
        args: argparse.Namespace with host, port, base_url, timeout, accept attributes
        **kwargs: Additional keyword arguments to pass to OTBRRestApiClient constructor
                  (e.g., retries, user_agent, default_raw)
    
    Returns:
        Configured OTBRRestApiClient instance ready for API calls
    
    Usage Example:
        >>> import argparse
        >>> from otbr_restapi_util import add_common_rest_client_args, build_rest_client_from_args
        >>> parser = argparse.ArgumentParser()
        >>> add_common_rest_client_args(parser)
        >>> args = parser.parse_args(['--host', '192.168.1.1'])
        >>> client = build_rest_client_from_args(args)
        >>> client.base_url
        'http://192.168.1.1:8081'
    
    Notes:
        - If args.base_url is provided, it takes precedence over host/port
        - Additional kwargs are forwarded to the OTBRRestApiClient constructor
        - Default values come from the DEFAULT_* constants in otbr_restapi_util
    
    Raises:
        AttributeError: If required arguments (host, port, timeout, accept) are missing from args
    """
    # Extract standard client parameters from args
    client_params = {
        "host": args.host,
        "port": args.port,
        "base_url": args.base_url,
        "timeout": args.timeout,
        "accept": args.accept,
    }
    
    # Merge with any additional kwargs
    client_params.update(kwargs)
    
    return OTBRRestApiClient(**client_params)


# ---------------------------------------------------------------------------
# Output and Exit Code Helpers
# ---------------------------------------------------------------------------

def emit_rest_payload_output(
    payload: Any,
    output_path: str | Path | None,
    logger = None,
) -> None:
    """Save REST API payload to JSON file and log the operation.
    
    Centralizes the common pattern of saving JSON data and logging success/failure.
    Used by REST API CLI and download modules to standardize output handling.
    
    Args:
        payload: Data to serialize as JSON (dict, list, or JSON-serializable object)
        output_path: Path to output file, or None to skip file write
        logger: Optional logger instance for info/debug logging (uses root logger if None)
    
    Usage Example:
        >>> import logging
        >>> from pathlib import Path
        >>> from otbr_restapi_util import emit_rest_payload_output
        >>> 
        >>> data = {"devices": [{"id": "abc123", "rloc16": "0x8001"}]}
        >>> output_file = Path("/tmp/devices.json")
        >>> logger = logging.getLogger(__name__)
        >>> 
        >>> emit_rest_payload_output(data, output_file, logger)
        # Saves JSON to /tmp/devices.json and logs success
    
    Raises:
        OSError: If file write fails (logged as error before raising)
        TypeError: If payload is not JSON-serializable
    
    Notes:
        - Uses save_json_atomic() for safe atomic writes
        - Logs info message with file path on success
        - Logs debug message with JSON content for troubleshooting
        - Does nothing if output_path is None
    """
    from util_data import save_json_atomic
    
    if output_path is None:
        return
    
    if logger is None:
        import logging
        logger = logging.getLogger(__name__)
    
    output_file = Path(output_path)
    
    try:
        save_json_atomic(payload, output_file)
        logger.info("Saved: %s", output_file)
        logger.debug(
            "Saved data into %s as JSON:\n%s",
            output_file,
            json.dumps(payload, indent=4),
        )
    except OSError as exc:
        logger.error("File write error for %s: %s", output_file, exc)
        raise


def exit_code_for_rest_exception(exc: Exception) -> int:
    """Map REST API exceptions to CLI exit codes.
    
    Provides standardized exit code mapping for OTBR REST API exceptions.
    Used by CLI modules to ensure consistent exit behavior across tools.
    
    Args:
        exc: Exception to map to exit code
    
    Returns:
        Integer exit code:
        - 0: Not an error (should not be called with success)
        - 1: Unexpected error or generic OTBRClientError
        - 3: Connection error (network/connectivity issues)
        - 4: HTTP error or Action error (server returned error response)
        - 5: Invalid response (malformed JSON or unexpected structure)
    
    Usage Example:
        >>> from otbr_restapi_util import OTBRConnectionError, exit_code_for_rest_exception
        >>> 
        >>> try:
        ...     # ... REST API operation ...
        ...     pass
        ... except OTBRConnectionError as exc:
        ...     exit_code = exit_code_for_rest_exception(exc)
        ...     print(f"Exiting with code {exit_code}")
        ...     sys.exit(exit_code)
        # Output: Exiting with code 3
    
    Notes:
        - Matches exit code constants from otbr_restapi_cli (EXIT_*)
        - More specific exception types take precedence
        - Falls back to exit code 1 for unexpected exceptions
        - Action errors (OTBRActionError) map to HTTP error code 4
    """
    # Connection issues
    if isinstance(exc, OTBRConnectionError):
        return 3  # EXIT_CONNECTION
    
    # HTTP and Action errors
    if isinstance(exc, (OTBRHTTPError, OTBRActionError)):
        return 4  # EXIT_HTTP
    
    # Invalid response structure
    if isinstance(exc, OTBRInvalidResponseError):
        return 5  # EXIT_INVALID_RESPONSE
    
    # Generic client error or unexpected exception
    if isinstance(exc, OTBRClientError):
        return 1  # EXIT_UNEXPECTED
    
    # Fallback for non-OTBR exceptions
    return 1  # EXIT_UNEXPECTED
