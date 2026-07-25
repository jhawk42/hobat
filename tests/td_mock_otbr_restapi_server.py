from __future__ import annotations

import argparse
import json
import logging
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18081
LIVE_DEFAULT_HOST = "127.0.0.1"
LIVE_DEFAULT_PORT = 8081
JSON_API = "application/vnd.api+json"
JSON = "application/json"
TEXT = "text/plain"


@dataclass
class CapturedRequest:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes = b""


@dataclass
class MockOTBRStore:
    node_state: str = "router"
    active_dataset_json: dict = field(default_factory=dict)
    active_dataset_tlv: str = "0E080000000000010000000300001235060004001FFFE00208AABBCCDDEEFF001122334455667788"
    node_item: dict = field(default_factory=dict)
    devices: dict[str, dict] = field(default_factory=dict)
    diagnostics: dict[str, dict] = field(default_factory=dict)
    actions: dict[str, dict] = field(default_factory=dict)
    requests: list[CapturedRequest] = field(default_factory=list)
    queued_action_sequences: list[list[dict]] = field(default_factory=list)
    action_sequences: dict[str, list[dict]] = field(default_factory=dict)
    enqueue_reject_statuses: list[int] = field(default_factory=list)
    enqueue_response_statuses: list[int] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def build(cls) -> "MockOTBRStore":
        node_item = {
            "id": "96518e5497d5b9f3",
            "type": "threadBorderRouter",
            "attributes": {
                "rloc16": "0xf000",
                "extAddress": "96518e5497d5b9f3",
                "mlEidIid": "731f529f1266a17d",
                "omrIpv6Address": ["fd11:22:0:0:92de:b397:5758:368"],
                "hostname": "otbr.local",
                "eui": "9035eafffef3e09c",
                "role": "router",
                "mode": {
                    "deviceTypeFTD": True,
                    "rxOnWhenIdle": True,
                    "fullNetworkData": True,
                },
                "baId": "e11e23c164311ce642f93297b095b2f8",
                "routerCount": 2,
                "rlocAddress": "fd7a:9882:1777:a344:0:ff:fe00:f000",
                "networkName": "OpenThread-1234",
                "routerId": 0,
                "leaderData": {
                    "partitionId": 1794764107,
                    "weighting": 64,
                    "dataVersion": 97,
                    "stableDataVersion": 176,
                    "leaderRouterId": 78,
                },
                "extPanId": "a7b7d5d07d9ec2fa",
                "created": "2026-04-04T10:00:00Z",
            },
        }

        child_item = {
            "id": "2a55d952bc7b4008",
            "type": "threadDevice",
            "attributes": {
                "extAddress": "2a55d952bc7b4008",
                "mlEidIid": "3abd123497a87083",
                "omrIpv6Address": ["fd11:22:0:0:3abd:e522:97a8:7083"],
                "hostname": "sensor-01.local",
                "eui": "f4ce36dbdca16d79",
                "role": "child",
                "mode": {
                    "deviceTypeFTD": False,
                    "rxOnWhenIdle": False,
                    "fullNetworkData": True,
                },
                "created": "2026-04-04T10:05:00Z",
            },
        }

        diagnostics = {
            "fd428d18-8528-45cf-8a2d-f191bef39b5d": {
                "id": "fd428d18-8528-45cf-8a2d-f191bef39b5d",
                "type": "threadNetworkDiagnostic",
                "attributes": {
                    "created": "2026-04-04T10:10:00Z",
                    "extAddress": "96518e5497d5b9f3",
                    "rloc16": "0xf000",
                    "ipv6Addresses": ["fd11:22:0:0:92de:b397:5758:368"],
                    "vendorName": "MockVendor",
                    "vendorModel": "MockOTBR",
                    "threadVersion": 4,
                },
            },
            "688f881a-b3d5-4261-949c-9c18dfdd7fca": {
                "id": "688f881a-b3d5-4261-949c-9c18dfdd7fca",
                "type": "energyScanReport",
                "attributes": {
                    "origin": "96518e5497d5b9f3",
                    "report": [
                        {"channel": 11, "maxRssi": [-45, -55, -50]},
                        {"channel": 12, "maxRssi": [-48, -53, -51]},
                    ],
                    "created": "2026-04-04T10:11:00Z",
                },
            },
        }

        initial_action_id = "1211547c-6207-4833-a629-8992ead4068c"
        actions = {
            initial_action_id: {
                "id": initial_action_id,
                "type": "updateDeviceCollectionTask",
                "attributes": {
                    "maxAge": 30,
                    "maxRetries": 5,
                    "deviceCount": 10,
                    "timeout": 93,
                    "status": "completed",
                },
            }
        }

        active_dataset_json = {
            "activeTimestamp": {"seconds": 1, "ticks": 0, "authoritative": False},
            "networkKey": "08277229F21FB7342D705D3CEFDC042A",
            "networkName": "OpenThread-1234",
            "extPanId": "996D3BEE320097A3",
            "meshLocalPrefix": "fd33:d3b9:89e3:72e4::/64",
            "panId": 4660,
            "channel": 21,
            "pskc": "FD943ECA225A28979B991EFAC1218A72",
        }

        return cls(
            node_state="router",
            active_dataset_json=active_dataset_json,
            node_item=node_item,
            devices={node_item["id"]: node_item, child_item["id"]: child_item},
            diagnostics=diagnostics,
            actions=actions,
        )


def make_handler(store: MockOTBRStore):
    class MockOTBRRequestHandler(BaseHTTPRequestHandler):
        server_version = "MockOTBR/1.0"

        def do_GET(self) -> None:
            self._handle_request("GET")

        def do_POST(self) -> None:
            self._handle_request("POST")

        def do_PUT(self) -> None:
            self._handle_request("PUT")

        def do_DELETE(self) -> None:
            self._handle_request("DELETE")

        def log_message(self, format: str, *args) -> None:
            return

        def _handle_request(self, method: str) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            accept = self._preferred_accept()
            captured = CapturedRequest(
                method=method,
                path=self.path,
                headers={key.lower(): value for key, value in self.headers.items()},
            )
            with store.lock:
                store.requests.append(captured)
            self._captured_request = captured

            if method == "GET" and path == "/api/node":
                return self._send_node(accept)
            if method == "GET" and path == "/node/state":
                return self._send_json(store.node_state)
            if method == "PUT" and path == "/node/state":
                return self._set_node_state()
            if method == "GET" and path == "/node/dataset/active":
                return self._send_active_dataset(accept)
            if method == "PUT" and path == "/node/dataset/active":
                return self._set_active_dataset()
            if method == "GET" and path == "/api/devices":
                return self._send_collection(list(store.devices.values()), accept)
            if method == "GET" and path.startswith("/api/devices/"):
                return self._send_item_by_id(
                    store.devices, path.split("/")[-1], accept, "device"
                )
            if method == "GET" and path == "/api/diagnostics":
                return self._send_collection(list(store.diagnostics.values()), accept)
            if method == "GET" and path.startswith("/api/diagnostics/"):
                return self._send_item_by_id(
                    store.diagnostics, path.split("/")[-1], accept, "diagnostic"
                )
            if method == "GET" and path == "/api/actions":
                return self._send_collection(
                    list(store.actions.values()), accept, pending=True
                )
            if method == "GET" and path.startswith("/api/actions/"):
                return self._send_action(path.split("/")[-1], accept)
            if method == "POST" and path == "/api/actions":
                return self._enqueue_actions()
            if method == "DELETE" and path.startswith("/api/actions/"):
                return self._delete_item(
                    store.actions,
                    path.split("/")[-1],
                    store.action_sequences,
                )
            if method == "DELETE" and path == "/api/actions":
                return self._delete_collection(store.actions, store.action_sequences)
            if method == "DELETE" and path == "/api/devices":
                return self._delete_collection(store.devices)
            if method == "DELETE" and path == "/api/diagnostics":
                return self._delete_collection(store.diagnostics)

            self._send_error_document(404, "Not Found", f"Unknown path: {path}", accept)

        def _preferred_accept(self) -> str:
            header = self.headers.get("Accept", JSON_API)
            if TEXT in header:
                return TEXT
            if JSON in header and JSON_API not in header:
                return JSON
            return JSON_API

        def _read_body(self) -> bytes:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0:
                return b""
            body = self.rfile.read(content_length)
            self._captured_request.body = body
            return body

        def _delete_collection(
            self,
            items: dict[str, dict],
            sequences: dict[str, list[dict]] | None = None,
        ) -> None:
            with store.lock:
                items.clear()
                if sequences is not None:
                    sequences.clear()
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _delete_item(
            self,
            items: dict[str, dict],
            item_id: str,
            sequences: dict[str, list[dict]] | None = None,
        ) -> None:
            with store.lock:
                if item_id not in items:
                    return self._send_error_document(
                        404,
                        "Not Found",
                        "No action matches the requested ID.",
                        JSON_API,
                    )
                del items[item_id]
                if sequences is not None:
                    sequences.pop(item_id, None)
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send_active_dataset(self, accept: str) -> None:
            if accept == TEXT:
                return self._send_text(store.active_dataset_tlv)
            return self._send_json(store.active_dataset_json)

        def _set_node_state(self) -> None:
            body = self._read_body()
            try:
                value = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                return self._send_error_document(
                    400, "Bad Request", "Invalid JSON body for node state", JSON
                )

            if value == "enable":
                store.node_state = "router"
            elif value == "disable":
                store.node_state = "disabled"
            else:
                return self._send_error_document(
                    400, "Bad Request", "State must be enable or disable", JSON
                )

            self._send_json({"state": store.node_state})

        def _set_active_dataset(self) -> None:
            content_type = self.headers.get("Content-Type", JSON)
            body = self._read_body()
            if TEXT in content_type:
                store.active_dataset_tlv = body.decode("utf-8").strip()
                self._send_json({"updated": True, "format": "text"})
                return

            try:
                store.active_dataset_json = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                return self._send_error_document(
                    400, "Bad Request", "Invalid JSON body for active dataset", JSON
                )

            self._send_json({"updated": True, "format": "json"})

        def _send_node(self, accept: str) -> None:
            item = deepcopy(store.node_item)
            item["attributes"]["role"] = store.node_state
            if accept == JSON_API:
                self._send_jsonapi_document(item)
                return

            self._send_json(item["attributes"])

        def _send_collection(
            self, items: list[dict], accept: str, pending: bool = False
        ) -> None:
            materialized = [deepcopy(item) for item in items]
            for item in materialized:
                if item["id"] == store.node_item["id"] and "role" in item.get(
                    "attributes", {}
                ):
                    item["attributes"]["role"] = store.node_state

            if accept == JSON_API:
                meta = {
                    "collection": {
                        "offset": 0,
                        "limit": len(materialized),
                        "total": len(materialized),
                    }
                }
                if pending:
                    meta["collection"]["pending"] = sum(
                        1
                        for item in materialized
                        if item.get("attributes", {}).get("status") == "pending"
                    )
                self._send_jsonapi_document(materialized, meta=meta)
                return

            self._send_json([item.get("attributes", {}) for item in materialized])

        def _send_item_by_id(
            self, items: dict[str, dict], item_id: str, accept: str, label: str
        ) -> None:
            item = items.get(item_id)
            if item is None:
                return self._send_error_document(
                    404, "Not Found", f"No {label} matches the requested ID.", accept
                )

            materialized = deepcopy(item)
            if item_id == store.node_item["id"] and "role" in materialized.get(
                "attributes", {}
            ):
                materialized["attributes"]["role"] = store.node_state

            if accept == JSON_API:
                return self._send_jsonapi_document(materialized)
            return self._send_json(materialized.get("attributes", {}))

        def _send_action(self, action_id: str, accept: str) -> None:
            with store.lock:
                item = store.actions.get(action_id)
                sequence = store.action_sequences.get(action_id)
                if item is not None and sequence:
                    transition = sequence.pop(0)
                    item.setdefault("attributes", {}).update(
                        deepcopy(transition.get("attributes", transition))
                    )
                    if "relationships" in transition:
                        item["relationships"] = deepcopy(transition["relationships"])
            return self._send_item_by_id(
                store.actions, action_id, accept, "action"
            )

        def _enqueue_actions(self) -> None:
            body = self._read_body()
            try:
                payload = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                return self._send_error_document(
                    400, "Bad Request", "Invalid JSON body for actions", JSON_API
                )

            tasks = payload.get("data")
            if not isinstance(tasks, list) or not tasks:
                return self._send_error_document(
                    422,
                    "Unprocessable Content",
                    "Request must contain a non-empty data list.",
                    JSON_API,
                )

            with store.lock:
                reject_status = (
                    store.enqueue_reject_statuses.pop(0)
                    if store.enqueue_reject_statuses
                    else None
                )
            if reject_status is not None:
                return self._send_error_document(
                    reject_status,
                    "Service Unavailable",
                    "Scripted enqueue rejection before action processing.",
                    JSON_API,
                )

            created = []
            with store.lock:
                for task in tasks:
                    task_type = task.get("type")
                    attributes = deepcopy(task.get("attributes", {}))
                    action_id = str(uuid.uuid4())
                    attributes["status"] = "pending"
                    if (
                        task_type in {"getNetworkDiagnosticTask", "getEnergyScanTask"}
                        and store.diagnostics
                    ):
                        first_diagnostic_id = next(iter(store.diagnostics.keys()))
                        created_item = {
                            "id": action_id,
                            "type": task_type,
                            "attributes": attributes,
                            "relationships": {
                                "result": {
                                    "data": {
                                        "type": "diagnostics",
                                        "id": first_diagnostic_id,
                                    }
                                }
                            },
                        }
                    else:
                        created_item = {
                            "id": action_id,
                            "type": task_type,
                            "attributes": attributes,
                        }
                    store.actions[action_id] = created_item
                    if store.queued_action_sequences:
                        store.action_sequences[action_id] = deepcopy(
                            store.queued_action_sequences.pop(0)
                        )
                    created.append(created_item)

                response_status = (
                    store.enqueue_response_statuses.pop(0)
                    if store.enqueue_response_statuses
                    else 200
                )

            if response_status != 200:
                return self._send_error_document(
                    response_status,
                    "Service Unavailable" if response_status == 503 else "Internal Server Error",
                    "Scripted enqueue response after action processing.",
                    JSON_API,
                )
            self._send_jsonapi_document(created, status=200)

        def _send_jsonapi_document(
            self, data: dict | list[dict], status: int = 200, meta: dict | None = None
        ) -> None:
            document = {"data": data}
            if meta is not None:
                document["meta"] = meta
            self._send(status, JSON_API, document)

        def _send_json(self, data, status: int = 200) -> None:
            self._send(status, JSON, data)

        def _send_text(self, text: str, status: int = 200) -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", TEXT)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error_document(
            self, status: int, title: str, detail: str, accept: str
        ) -> None:
            if accept == JSON_API:
                payload = {
                    "errors": [{"title": title, "status": status, "detail": detail}]
                }
                self._send(status, JSON_API, payload)
                return
            payload = {"title": title, "status": status, "detail": detail}
            self._send(status, JSON, payload)

        def _send(self, status: int, content_type: str, payload) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return MockOTBRRequestHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Local mock server for the OTBR REST API client. "
            f"Defaults to {DEFAULT_HOST}:{DEFAULT_PORT} so it stays separate from the live OTBR default "
            f"{LIVE_DEFAULT_HOST}:{LIVE_DEFAULT_PORT}."
        )
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    store = MockOTBRStore.build()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store))
    logging.info(f"Mock OTBR REST API listening on http://{args.host}:{args.port}")
    logging.info(
        "Use explicit client overrides to reach the mock server: "
        f"--host {args.host} --port {args.port}. "
        f"The normal client default remains http://{LIVE_DEFAULT_HOST}:{LIVE_DEFAULT_PORT}."
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
