"""Verify producer-bound OTBR EUI sweep evidence without running a collector."""

import hashlib
import ipaddress
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from otbr_cli_networkdiag_parsers import parse_diagnostic_tlv_payload


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _time(value: str) -> datetime:
    time = datetime.fromisoformat(value)
    if time.utcoffset() is None:
        raise ValueError("Sweep times must include an offset")
    return time


def _probe(files: dict[str, bytes], name: str, kind: str) -> str:
    lines = files[f"{name}.{kind}.stdout.txt"].decode().splitlines()
    if len(lines) != 2 or lines[1].strip() != "Done" or files[f"{name}.{kind}.stderr.txt"].strip():
        raise ValueError(f"{name}: invalid live {kind} response")
    return lines[0].strip()


def read_sweep(directory: Path, network_id: str) -> tuple[str, str, list[dict]]:
    try:
        return _read_sweep(directory, network_id)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid sweep evidence structure") from exc


def _read_sweep(directory: Path, network_id: str) -> tuple[str, str, list[dict]]:
    inputs_raw = (directory / "inputs.json").read_bytes()
    inputs = json.loads(inputs_raw)
    completion_raw = (directory / "collection-complete.json").read_bytes()
    complete = json.loads(completion_raw)
    if not inputs.get("captureId") or not complete.get("networkReceiptSha256"):
        raise ValueError("Sweep has no producer-bound network receipt")
    receipt_raw = (directory / "network-receipt.json").read_bytes()
    fingerprint = digest_bytes(receipt_raw)
    receipt = json.loads(receipt_raw)
    instance = re.fullmatch(r"([a-f0-9]{64}) (\S+)", inputs["otbrInstance"])
    targets = inputs["rloc16"]
    windows = receipt["windows"]
    tlvs = inputs["requestedTlvs"]
    if (fingerprint != complete["networkReceiptSha256"]
            or receipt["version"] != 1 or receipt["networkId"] != network_id
            or inputs["networkId"] != network_id or not instance
            or receipt["captureId"] != inputs["captureId"]
            or receipt["otbrInstance"] != inputs["otbrInstance"]
            or receipt["inputsSha256"] != digest_bytes(inputs_raw)
            or not isinstance(targets, list) or not 1 <= len(targets) <= 65536
            or any(not re.fullmatch(r"[a-f0-9]{4}", target) for target in targets)
            or len(set(targets)) != len(targets) or len(windows) != len(targets)
            or complete["queryCount"] != len(targets)
            or not isinstance(tlvs, list) or not {0, 23}.issubset(tlvs)
            or any(type(tlv) is not int or not 0 <= tlv <= 255 for tlv in tlvs)):
        raise ValueError("Sweep receipt does not match the selected network or capture inventory")
    started = _time(inputs["startedAt"])
    finished = _time(complete["finishedAt"])
    if not started <= finished <= datetime.now(timezone.utc):
        raise ValueError("Invalid sweep collection bounds")

    prefix = inputs["prefix"]
    previous_end = started
    captures = []
    for rloc, window in zip(targets, windows):
        if window["requestedRloc16"] != rloc:
            raise ValueError("Sweep receipt window order does not match the capture inventory")
        probes = [f"{rloc}.{side}" for side in ("before", "after")]
        streams = [f"{rloc}.stdout.txt", f"{rloc}.stderr.txt"]
        names = [f"{rloc}.json", *streams] + [
            f"{name}.{kind}.{stream}.txt" for name in probes
            for kind in ("extpanid", "mleid") for stream in ("stdout", "stderr")
        ]
        files = {name: (directory / name).read_bytes() for name in names}
        if window["sha256"] != {name: digest_bytes(raw) for name, raw in files.items()}:
            raise ValueError(f"{rloc}: sweep window digest mismatch")
        for name in probes:
            observed = _probe(files, name, "extpanid")
            mesh = ipaddress.IPv6Network((_probe(files, name, "mleid"), 64), strict=False)
            if (not re.fullmatch(r"[a-fA-F0-9]{16}", observed)
                    or "extpan:" + observed.lower() != network_id
                    or ipaddress.IPv6Address(prefix + rloc) not in mesh):
                raise ValueError(f"{rloc}: live network probe disagrees with receipt")
        result = json.loads(files[f"{rloc}.json"])
        command = ["docker", "exec", "-it", instance[1], "/usr/sbin/ot-ctl",
                   "networkdiagnostic", "get", prefix + rloc, *map(str, tlvs)]
        if (result["requestedRloc16"] != rloc or result["command"] != command
                or result["startedAt"] != window["startedAt"] or result["finishedAt"] != window["finishedAt"]):
            raise ValueError(f"{rloc}: inconsistent sweep query")
        bounds = [previous_end, _time(window["before"]["startedAt"]),
                  _time(window["before"]["finishedAt"]), _time(window["startedAt"]),
                  _time(window["finishedAt"]), _time(window["after"]["startedAt"]),
                  _time(window["after"]["finishedAt"]), finished]
        if bounds != sorted(bounds):
            raise ValueError(f"{rloc}: inconsistent sweep time bounds")
        previous_end = bounds[-2]
        for stream in streams:
            for line_number, line in enumerate(files[stream].decode().splitlines(), 1):
                if not line.startswith("DIAG_GET.rsp/ans from "):
                    continue
                match = re.fullmatch(r"DIAG_GET\.rsp/ans from ([0-9a-fA-F:]+): ([0-9a-fA-F]+)\s*", line)
                if match is None:
                    raise ValueError(f"{stream}:{line_number}: malformed raw diagnostic frame")
                parsed = parse_diagnostic_tlv_payload(match[2])
                ids = parsed["received_type_ids"]
                if parsed["status"] != "valid" or len(ids) != len(set(ids)):
                    raise ValueError(f"{stream}:{line_number}: malformed or duplicate diagnostic TLV")
                values = {item["type"]: item["value"].hex() for item in parsed["tlvs"]}
                ext, eui = values.get(0), values.get(23)
                if any(value is not None and not re.fullmatch(r"[0-9a-f]{16}", value)
                       for value in (ext, eui)):
                    raise ValueError(f"{stream}:{line_number}: invalid diagnostic identity length")
                if ext:
                    captures.append({
                        "extAddress": ext, "eui": eui, "startedAt": window["startedAt"],
                        "finishedAt": window["finishedAt"], "stream": stream,
                        "line": line_number, "sha256": window["sha256"][stream],
                    })
    target_set = set(targets)
    returned = {row["extAddress"] for row in captures}
    for row in inputs["merged"]:
        ext, rloc = row.get("extAddress"), row.get("rloc16")
        if (isinstance(ext, str) and re.fullmatch(r"[0-9a-f]{16}", ext)
                and rloc and rloc.lower().removeprefix("0x").zfill(4) in target_set
                and row.get("_networkInstance") == network_id and ext not in returned):
            captures.append({"extAddress": ext, "eui": None})
            returned.add(ext)
    return fingerprint, digest_bytes(completion_raw), captures
