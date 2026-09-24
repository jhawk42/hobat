"""Shared Thread network instance identity and provenance."""

from __future__ import annotations

import re
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from td_const import (
    HA_MATTER_WS_TOPOLOGY_FILENAME,
    OTBR_CLI_THREAD_NETWORK_INFO_FILENAME,
    OTBR_RESTAPI_DATASET_ACTIVE_FILENAME,
)


IDENTITY_PROVENANCE_OBSERVED = "observed"
IDENTITY_PROVENANCE_OPERATOR = "operator"
IDENTITY_PROVENANCE_UNKNOWN = "unknown"

_HEX_EXT_PAN_ID = re.compile(r"[0-9a-fA-F]{16}\Z")
_DECIMAL_EXT_PAN_ID = re.compile(r"[0-9]+\Z")


def canonical_ext_pan_id(value: object) -> str:
    """Return an exact, nonzero 64-bit Extended PAN ID as lowercase hex."""
    if isinstance(value, bool):
        raise ValueError("extPanId must contain exactly 16 hexadecimal digits")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip()
        if text.lower().startswith("0x"):
            digits = text[2:]
            if not _HEX_EXT_PAN_ID.fullmatch(digits):
                raise ValueError("extPanId must contain exactly 16 hexadecimal digits")
            number = int(digits, 16)
        else:
            digits = text.replace(":", "").replace("-", "")
            if _HEX_EXT_PAN_ID.fullmatch(digits):
                number = int(digits, 16)
            elif _DECIMAL_EXT_PAN_ID.fullmatch(text):
                number = int(text, 10)
            else:
                raise ValueError("extPanId must contain exactly 16 hexadecimal digits")
    else:
        raise ValueError("extPanId must contain exactly 16 hexadecimal digits")
    if not 0 < number < 1 << 64:
        raise ValueError("extPanId must be a nonzero 64-bit value")
    return f"{number:016x}"


def network_id_from_ext_pan_id(value: object) -> str:
    return f"extpan:{canonical_ext_pan_id(value)}"


@dataclass(frozen=True)
class NetworkScope:
    ext_pan_id: str | None
    network_name: str | None
    provenance: str
    reason: str | None
    observed_at: str
    sources: tuple[str, ...]


def _observations(data: Any, *, mdns: bool = False) -> tuple[set[str], str | None]:
    values: set[str] = set()
    network_name = None

    def visit(item: Any) -> None:
        nonlocal network_name
        if isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            if mdns:
                if item.get("scope") == "_meshcop._udp.local.":
                    properties = item.get("serviceInfo", item.get("service_info", {})).get("properties", {})
                    value = item.get("extPanId") or properties.get("xp", {}).get("hex")
                    if value is not None:
                        try:
                            values.add(canonical_ext_pan_id(value))
                        except ValueError:
                            pass
                return
            for key in ("extPanIdHex", "extPanId", "extendedPanId", "ext_pan_id"):
                value = item.get(key)
                if value is not None:
                    try:
                        values.add(canonical_ext_pan_id(value))
                    except ValueError:
                        pass
            if isinstance(item.get("networkName"), str) and not network_name:
                network_name = item["networkName"]
            for child in item.values():
                if isinstance(child, (dict, list)):
                    visit(child)

    visit(data)
    return values, network_name


def resolve_network_scope(
    filename: str | os.PathLike, data: Any, operator_value: object = None
) -> NetworkScope:
    import json

    path = Path(filename)
    name = path.name
    mdns = name.startswith("td-mdns-scopes-")
    values, network_name = _observations(data, mdns=mdns)
    source = name
    if not values and not mdns:
        reference = (
            OTBR_CLI_THREAD_NETWORK_INFO_FILENAME if name.startswith("td-otbr-cli-")
            else OTBR_RESTAPI_DATASET_ACTIVE_FILENAME if name.startswith("td-otbr-restapi-")
            else HA_MATTER_WS_TOPOLOGY_FILENAME if name.startswith("td-ha-matter-ws-")
            else None
        )
        if reference and reference != name and (path.parent / reference).exists():
            try:
                values, network_name = _observations(json.loads((path.parent / reference).read_text(encoding="utf-8")))
                if values:
                    source = reference
            except (OSError, ValueError):
                pass
    try:
        operator = canonical_ext_pan_id(operator_value) if operator_value else None
    except ValueError:
        logging.warning("invalid operator ext-pan-id ignored: %s", operator_value)
        operator = None
    observed_at = datetime.now(timezone.utc).isoformat()
    if len(values) > 1:
        return NetworkScope(None, network_name, IDENTITY_PROVENANCE_UNKNOWN,
                            f"multiple-instances-in-scope: {', '.join(sorted(values))}", observed_at, (source,))
    if values:
        value = next(iter(values))
        if operator and operator != value:
            logging.warning("operator ext-pan-id %s ignored; observed %s", operator, value)
        return NetworkScope(value, network_name, IDENTITY_PROVENANCE_OBSERVED, None, observed_at, (source,))
    if operator:
        return NetworkScope(operator, network_name, IDENTITY_PROVENANCE_OPERATOR, None, observed_at, (name,))
    return NetworkScope(None, network_name, IDENTITY_PROVENANCE_UNKNOWN,
                        "no-ext-pan-id-observed", observed_at, (name,))