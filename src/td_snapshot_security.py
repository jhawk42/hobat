"""Shared credential-field detection for persisted source snapshots."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


SENSITIVE_KEYS = frozenset(
    {
        "accesscontrol",
        "acl",
        "activedataset",
        "certificate",
        "certificates",
        "daccertificate",
        "nocs",
        "networkkey",
        "operationaldataset",
        "trustedrootcertificates",
        "rootpublickey",
        "groupkeymap",
        "groupkeyset",
        "groupepochkey",
        "operationalcredentials",
        "paicertificate",
        "pendingdataset",
        "pskc",
        "threadcredentials",
    }
)


def normalized_security_key(key: object) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())


def contains_sensitive_field(
    value: Any,
    *,
    extra_match: Callable[[str], bool] | None = None,
) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = normalized_security_key(key)
            if normalized in SENSITIVE_KEYS or (
                extra_match is not None and extra_match(normalized)
            ):
                return True
            if contains_sensitive_field(child, extra_match=extra_match):
                return True
    elif isinstance(value, (list, tuple)):
        return any(
            contains_sensitive_field(child, extra_match=extra_match)
            for child in value
        )
    return False
