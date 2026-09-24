"""Shared source defaults and roster field overrides from the dataset catalog."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from td_dataset_catalog import load_dataset_catalog
from td_health_manifest import RosterPolicy


@dataclass(frozen=True)
class AuthorityTable:
    source_defaults: Mapping[str, int]
    field_overrides: Mapping[str, Mapping[str, int]]

    def source_rank(self, filename: str) -> int:
        return self.source_defaults.get(filename, 0)

    def field_rank(self, field: str, filename: str) -> int:
        return self.field_overrides.get(field, {}).get(filename, self.source_rank(filename))


def load_authority_table(manifest: dict | None = None, *, policy: RosterPolicy | None = None) -> AuthorityTable:
    catalog = manifest if manifest is not None else load_dataset_catalog()
    defaults = catalog["authority"]["sourceDefaults"]
    if any(not isinstance(name, str) or type(rank) is not int or rank <= 0
           for name, rank in defaults.items()):
        raise ValueError("Invalid catalog source authority")
    overrides = policy.sources if policy is not None else catalog["authority"]["fieldOverrides"]
    return AuthorityTable(MappingProxyType(dict(defaults)), overrides)


AUTHORITY = load_authority_table()


def source_rank(filename: str) -> int:
    return AUTHORITY.source_rank(filename)


def field_rank(field: str, filename: str, *, policy: RosterPolicy | None = None) -> int:
    if policy is not None:
        return policy.sources.get(field, {}).get(filename, source_rank(filename))
    return AUTHORITY.field_rank(field, filename)