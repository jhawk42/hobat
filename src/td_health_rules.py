"""Strict machine-readable Thread health rule catalog."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


RULE_CATALOG_PATH = Path(__file__).with_name("td-health-rules.json")
_SCOPES = frozenset({"network", "device", "relationship", "external"})
_MATERIALITY = frozenset({"informational", "device", "relationship", "network"})


class HealthRuleCatalogError(ValueError):
    """Raised when the health rule catalog violates its contract."""


@dataclass(frozen=True)
class HealthRule:
    rule_id: str
    order: int
    title: str
    variants: Mapping[str, str]
    description: str
    evidence_kind: str
    scopes: frozenset[str]
    roles: frozenset[str]
    relationship_types: frozenset[str]
    required_capability: str | None
    materiality: str
    threshold_keys: frozenset[str]
    action: str
    verify: str

    def title_for(self, variant: str | None = None) -> str:
        if variant is None:
            return self.title
        try:
            return self.variants[variant]
        except KeyError as exc:
            raise HealthRuleCatalogError(
                f"Unknown presentation variant {variant!r} for {self.rule_id}"
            ) from exc


class HealthRuleCatalog:
    def __init__(self, rules: tuple[HealthRule, ...]):
        self.rules = rules
        self._by_id = MappingProxyType({rule.rule_id: rule for rule in rules})

    def rule(self, rule_id: str) -> HealthRule:
        try:
            return self._by_id[rule_id]
        except KeyError as exc:
            raise HealthRuleCatalogError(f"Unknown health rule {rule_id!r}") from exc

    @property
    def rule_ids(self) -> frozenset[str]:
        return frozenset(self._by_id)

    @property
    def threshold_keys(self) -> frozenset[str]:
        return frozenset(
            key for rule in self.rules for key in rule.threshold_keys
        )


def _string(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise HealthRuleCatalogError(f"Rule requires non-empty {key}")
    return value


def _strings(raw: Mapping[str, object], key: str) -> frozenset[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise HealthRuleCatalogError(f"Rule requires string array {key}")
    if len(value) != len(set(value)):
        raise HealthRuleCatalogError(f"Rule contains duplicate {key}")
    return frozenset(value)


def load_health_rule_catalog(path: Path = RULE_CATALOG_PATH) -> HealthRuleCatalog:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HealthRuleCatalogError(f"Cannot load health rule catalog: {exc}") from exc
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        raise HealthRuleCatalogError("Health rule catalog requires schemaVersion 1")
    raw_rules = document.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise HealthRuleCatalogError("Health rule catalog requires rules")
    rules: list[HealthRule] = []
    seen_ids: set[str] = set()
    seen_orders: set[int] = set()
    for raw in raw_rules:
        if not isinstance(raw, dict):
            raise HealthRuleCatalogError("Each health rule must be an object")
        rule_id = _string(raw, "ruleId")
        order = raw.get("order")
        if rule_id in seen_ids:
            raise HealthRuleCatalogError(f"Duplicate health rule {rule_id}")
        if not isinstance(order, int) or isinstance(order, bool) or order < 0:
            raise HealthRuleCatalogError(f"Invalid order for {rule_id}")
        if order in seen_orders:
            raise HealthRuleCatalogError(f"Duplicate health rule order {order}")
        variants = raw.get("variants", {})
        if not isinstance(variants, dict) or not all(
            isinstance(key, str) and key and isinstance(value, str) and value
            for key, value in variants.items()
        ):
            raise HealthRuleCatalogError(f"Invalid variants for {rule_id}")
        scopes = _strings(raw, "scopes")
        materiality = _string(raw, "materiality")
        if not scopes or not scopes <= _SCOPES:
            raise HealthRuleCatalogError(f"Invalid scopes for {rule_id}")
        if materiality not in _MATERIALITY:
            raise HealthRuleCatalogError(f"Invalid materiality for {rule_id}")
        required_capability = raw.get("requiredCapability")
        if required_capability is not None and not isinstance(required_capability, str):
            raise HealthRuleCatalogError(f"Invalid requiredCapability for {rule_id}")
        rules.append(
            HealthRule(
                rule_id=rule_id,
                order=order,
                title=_string(raw, "title"),
                variants=MappingProxyType(dict(variants)),
                description=_string(raw, "description"),
                evidence_kind=_string(raw, "evidenceKind"),
                scopes=scopes,
                roles=_strings(raw, "roles"),
                relationship_types=_strings(raw, "relationshipTypes"),
                required_capability=required_capability,
                materiality=materiality,
                threshold_keys=_strings(raw, "thresholdKeys"),
                action=_string(raw, "action"),
                verify=_string(raw, "verify"),
            )
        )
        seen_ids.add(rule_id)
        seen_orders.add(order)
    return HealthRuleCatalog(tuple(sorted(rules, key=lambda rule: rule.order)))


HEALTH_RULE_CATALOG = load_health_rule_catalog()