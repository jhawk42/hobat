from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_HOST = "192.168.4.77"
DEFAULT_PORT = 8081
DEFAULT_TIMEOUT = 10
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


class OTBRRestApiClient:
    """Minimal OTBR REST client with flattened JSON:API responses by default."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        base_url: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        accept: str = DEFAULT_ACCEPT,
        user_agent: str = "td-otbr-restapi-client/1.0",
    ) -> None:
        self.base_url = (base_url or f"http://{host}:{port}").rstrip("/")
        self.timeout = timeout
        self.accept = accept
        self.user_agent = user_agent

    def get_node(
        self,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        *,
        raw: bool = False,
    ) -> Any:
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

    def get_active_dataset(self, *, plain_text: bool = False, raw: bool = False) -> Any:
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
        raw: bool = False,
        with_meta: bool = False,
    ) -> Any:
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
        raw: bool = False,
    ) -> Any:
        return self._request(
            f"/api/devices/{device_id}",
            query=self._build_fields_query(fields),
            raw=raw,
        )

    def list_diagnostics(
        self,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        *,
        raw: bool = False,
        with_meta: bool = False,
    ) -> Any:
        return self._request(
            "/api/diagnostics",
            query=self._build_fields_query(fields),
            raw=raw,
            with_meta=with_meta,
        )

    def get_diagnostic(self, diagnostics_id: str, *, raw: bool = False) -> Any:
        return self._request(f"/api/diagnostics/{diagnostics_id}", raw=raw)

    def list_actions(
        self,
        fields: Mapping[str, str | Sequence[str] | None] | None = None,
        *,
        raw: bool = False,
        with_meta: bool = False,
    ) -> Any:
        return self._request(
            "/api/actions",
            query=self._build_fields_query(fields),
            raw=raw,
            with_meta=with_meta,
        )

    def get_action(self, action_id: str, *, raw: bool = False) -> Any:
        return self._request(f"/api/actions/{action_id}", raw=raw)

    def enqueue_actions(self, tasks: Sequence[Mapping[str, Any]], *, raw: bool = False) -> Any:
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
        raw: bool = False,
    ) -> Any:
        identity_fields = [value for value in (eui, discerner, joiner_id) if value]
        if len(identity_fields) != 1:
            raise OTBRUsageError("exactly one of eui, discerner, or joiner_id is required")

        self._require_non_empty_string(pskd, "pskd")

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
        raw: bool = False,
    ) -> Any:
        self._require_non_empty_string(destination, "destination")
        attributes = self._build_destination_attributes(
            destination=destination,
            destination_type=destination_type,
        )
        attributes["types"] = self._require_non_empty_sequence(types, "types")
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
        raw: bool = False,
    ) -> Any:
        attributes: dict[str, Any] = {"types": self._require_non_empty_sequence(types, "types")}
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
        count: int,
        period: int,
        scan_duration: int,
        timeout: int,
        destination_type: str | None = None,
        raw: bool = False,
    ) -> Any:
        self._require_non_empty_string(destination, "destination")
        attributes = self._build_destination_attributes(
            destination=destination,
            destination_type=destination_type,
        )
        attributes.update(
            {
                "channelMask": self._require_non_empty_sequence(channel_mask, "channel_mask"),
                "count": count,
                "period": period,
                "scanDuration": scan_duration,
                "timeout": timeout,
            }
        )

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
        raw: bool = False,
    ) -> Any:
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
    ) -> Any:
        url = self._build_url(path, query)
        body = self._encode_body(data, content_type)
        request = Request(
            url=url,
            data=body,
            headers=self._build_headers(accept=accept, content_type=content_type),
            method=method,
        )

        try:
            with urlopen(request, timeout=timeout or self.timeout) as response:
                response_body = response.read()
                media_type = self._extract_media_type(response.headers.get("Content-Type"))

            if not response_body:
                return None

            payload = self._decode_response_body(response_body, media_type)
            if raw:
                return payload

            return self._normalize_response_payload(payload, media_type, with_meta=with_meta)
        except HTTPError as exc:
            error_body = exc.read()
            media_type = self._extract_media_type(exc.headers.get("Content-Type"))
            payload = None
            body_text = None
            if error_body:
                body_text = error_body.decode("utf-8", errors="replace")
                payload = self._decode_payload_from_text(body_text, media_type)
            raise OTBRHTTPError(
                status_code=exc.code,
                reason=exc.reason,
                url=url,
                errors=self._extract_error_details(payload, exc.code, exc.reason),
                payload=payload,
                body=body_text,
            ) from exc
        except URLError as exc:
            raise OTBRConnectionError(f"Failed to reach OTBR API at {url}: {exc.reason}") from exc

    def _build_url(self, path: str, query: Mapping[str, str] | None = None) -> str:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        return url

    def _build_headers(self, *, accept: str | None = None, content_type: str | None = None) -> dict[str, str]:
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
        raise OTBRUsageError(f"Unsupported request content type: {content_type}")

    def _decode_response_body(self, response_body: bytes, media_type: str | None) -> Any:
        body_text = response_body.decode("utf-8", errors="replace")
        payload = self._decode_payload_from_text(body_text, media_type)
        if payload is None:
            return body_text
        return payload

    def _decode_payload_from_text(self, body_text: str, media_type: str | None) -> Any | None:
        stripped = body_text.strip()
        if not stripped:
            return None
        if media_type in JSON_CONTENT_TYPES or stripped[0] in "[{\"":
            try:
                return json.loads(body_text)
            except json.JSONDecodeError as exc:
                raise OTBRInvalidResponseError(f"Invalid JSON response: {exc}") from exc
        return None

    def _normalize_response_payload(self, payload: Any, media_type: str | None, *, with_meta: bool) -> Any:
        if media_type == "application/vnd.api+json" and isinstance(payload, dict):
            return self._flatten_jsonapi_document(payload, with_meta=with_meta)
        return payload

    def _flatten_jsonapi_document(self, payload: Mapping[str, Any], *, with_meta: bool) -> Any:
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

    def _extract_error_details(
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
                                status=self._coerce_int(error.get("status")) or status_code,
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
                        status=self._coerce_int(payload.get("status")) or status_code,
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

    def _build_destination_attributes(
        self,
        *,
        destination: str,
        destination_type: str | None = None,
    ) -> dict[str, Any]:
        self._require_non_empty_string(destination, "destination")
        attributes: dict[str, Any] = {"destination": destination}
        if destination_type:
            attributes["destinationType"] = destination_type
        return attributes

    def _require_non_empty_sequence(self, values: Sequence[Any], field_name: str) -> list[Any]:
        items = list(values)
        if not items:
            raise OTBRUsageError(f"{field_name} must contain at least one item")
        return items

    def _require_non_empty_string(self, value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise OTBRUsageError(f"{field_name} must be a non-empty string")
        return value

    def _extract_media_type(self, content_type: str | None) -> str | None:
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
    if isinstance(exc, OTBRClientError):
        return {"error": {"type": "client", "message": str(exc)}}
    return {"error": {"type": "unexpected", "message": str(exc)}}