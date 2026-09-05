import ast
import json
import re
from pathlib import Path

import pytest

from td_health_policy import POLICY_THRESHOLD_KEYS
from td_health_evaluator import EVALUATOR_THRESHOLD_OWNERS
from td_health_rules import (
    HEALTH_RULE_CATALOG,
    HealthRuleCatalogError,
    load_health_rule_catalog,
)


def _write_catalog(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_catalog_has_unique_stable_order_and_complete_policy_ownership():
    rules = HEALTH_RULE_CATALOG.rules

    assert tuple(rule.order for rule in rules) == tuple(sorted(rule.order for rule in rules))
    assert len({rule.rule_id for rule in rules}) == len(rules)
    assert len({rule.order for rule in rules}) == len(rules)
    assert HEALTH_RULE_CATALOG.threshold_keys == POLICY_THRESHOLD_KEYS
    assert frozenset(EVALUATOR_THRESHOLD_OWNERS) == POLICY_THRESHOLD_KEYS
    for threshold_key, rule_ids in EVALUATOR_THRESHOLD_OWNERS.items():
        assert rule_ids
        assert all(
            threshold_key in HEALTH_RULE_CATALOG.rule(rule_id).threshold_keys
            for rule_id in rule_ids
        )


def test_catalog_covers_every_evaluator_rule_id():
    source = (Path(__file__).parents[1] / "src" / "td_health_evaluator.py").read_text(
        encoding="utf-8"
    )
    literal_rule_ids = set(re.findall(r'rule_id="([^"]+)"', source))
    metric_rule_ids = {
        "device.missing",
        "device.parentChanges",
        "device.partitionIdChanges",
        "device.betterPartitionAttachAttempts",
        "device.totalParentPartitionChanges",
        "device.routerRolePercent",
        "device.detachedDisabledPercent",
        "device.totalMacErrorRatio",
        "device.totalMacDiscardRatio",
    }

    assert literal_rule_ids | metric_rule_ids == HEALTH_RULE_CATALOG.rule_ids


def test_evaluator_finding_calls_do_not_duplicate_catalog_copy():
    source = (Path(__file__).parents[1] / "src" / "td_health_evaluator.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    forbidden = {"title", "why", "action", "verify"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "_finding":
                assert forbidden.isdisjoint(
                    keyword.arg for keyword in node.keywords if keyword.arg
                )


def test_catalog_resolves_presentation_variant():
    rule = HEALTH_RULE_CATALOG.rule("relationship.directional-quality")

    assert rule.title_for() == "Link Quality or Delivery Degradation"
    assert (
        rule.title_for("delivery-errors-adequate-signal")
        == "High Delivery Errors Despite Acceptable Signal"
    )
    with pytest.raises(HealthRuleCatalogError, match="Unknown presentation variant"):
        rule.title_for("missing")


def test_catalog_exposes_effective_source_and_denominator_requirements():
    observed = HEALTH_RULE_CATALOG.rule("device.observed")
    mac = HEALTH_RULE_CATALOG.rule("device.totalMacErrorRatio")
    mle = HEALTH_RULE_CATALOG.rule("device.parentChanges")

    assert observed.source_requirements == frozenset()
    assert observed.requires_denominator is False
    assert mac.source_requirements == frozenset({"macCounters"})
    assert mac.requires_denominator is True
    assert mle.source_requirements == frozenset({"mleCounters"})
    assert observed.evidence_kind == "snapshot"
    assert mle.evidence_kind == "since-reset"
    assert mac.required_evidence == (
        "metric",
        "value",
        "denominator",
        "unstableThreshold",
    )
    assert mac.action_key == "health.device.totalMacErrorRatio.action"
    assert mac.verification_key == "health.device.totalMacErrorRatio.verify"


def test_operator_documentation_matches_catalog_metadata():
    documentation = (
        Path(__file__).parents[1] / "doc" / "thread_network_health.md"
    ).read_text(encoding="utf-8")
    catalog_section = documentation.split("## Finding Catalog", 1)[1].split(
        "\n## ", 1
    )[0]
    documented_rules = {
        rule_id: (title.strip(), description.strip())
        for rule_id, title, description in re.findall(
            r"^\| `([^`]+)` \| ([^|]+) \| ([^|]+) \|$",
            catalog_section,
            flags=re.MULTILINE,
        )
    }

    assert documented_rules == {
        rule.rule_id: (rule.title, rule.description)
        for rule in HEALTH_RULE_CATALOG.rules
    }


def test_catalog_rejects_duplicate_rule_ids(tmp_path):
    rule = {
        "ruleId": "device.test",
        "order": 1,
        "title": "Test",
        "description": "Test rule.",
        "evidenceKind": "snapshot",
        "scopes": ["device"],
        "roles": [],
        "relationshipTypes": [],
        "requiredCapability": None,
        "materiality": "device",
        "thresholdKeys": [],
        "action": "Inspect.",
        "verify": "Collect again."
    }
    path = _write_catalog(
        tmp_path,
        {
            "schemaVersion": 1,
            "defaults": {
                "sourceRequirements": [],
                "requiresDenominator": False,
                    "actionKeyTemplate": "health.{ruleId}.action",
                    "verificationKeyTemplate": "health.{ruleId}.verify",
            },
                "requiredEvidence": {"device.test": ["value"]},
            "rules": [rule, {**rule, "order": 2}],
        },
    )

    with pytest.raises(HealthRuleCatalogError, match="Duplicate health rule"):
        load_health_rule_catalog(path)