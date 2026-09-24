"""Shared Extended PAN ID canonicalization contract."""

import pytest

from td_network_identity import canonical_ext_pan_id, network_id_from_ext_pan_id
from td_network_identity import NetworkScope, resolve_network_scope
from util_data import read_network_scope, write_network_scope


def test_scope_sidecar_is_bound_to_snapshot(tmp_path):
    snapshot = tmp_path / "td-mdns-scopes-br.json"
    snapshot.write_text("[]", encoding="utf-8")
    scope = NetworkScope("78b9775b001c1cbe", None, "observed", None, "2026-01-01T00:00:00Z", (snapshot.name,))
    write_network_scope(snapshot, scope)
    assert read_network_scope(snapshot)[0]["extPanId"] == scope.ext_pan_id
    snapshot.write_text("[{}]", encoding="utf-8")
    assert read_network_scope(snapshot) == (None, "digest-mismatch")


def test_scope_sidecar_rejects_known_provenance_without_id(tmp_path):
    snapshot = tmp_path / "td-mdns-scopes-matter.json"
    snapshot.write_text("[]", encoding="utf-8")
    write_network_scope(snapshot, NetworkScope(None, None, "observed", None, "now", (snapshot.name,)))
    assert read_network_scope(snapshot) == (None, "invalid-sidecar")


def test_scope_resolver_prefers_observation_and_refuses_ambiguous_mdns(tmp_path, caplog):
    snapshot = tmp_path / "td-mdns-scopes-br.json"
    record = {"scope": "_meshcop._udp.local.", "serviceInfo": {"properties": {"xp": {"hex": "78b9775b001c1cbe"}}}}
    scope = resolve_network_scope(snapshot, [record], "0x1234567890123456")
    assert (scope.ext_pan_id, scope.provenance) == ("78b9775b001c1cbe", "observed")
    assert "ignored" in caplog.text
    other = {**record, "extPanId": "1111111111111111"}
    scope = resolve_network_scope(snapshot, [record, other], "0x1234567890123456")
    assert scope.provenance == "unknown"
    assert "multiple-instances-in-scope" in scope.reason


def test_scope_resolver_operator_fallback(tmp_path):
    scope = resolve_network_scope(tmp_path / "td-mdns-scopes-matter.json", [], "0x78B9775B001C1CBE")
    assert (scope.ext_pan_id, scope.provenance) == ("78b9775b001c1cbe", "operator")
    assert resolve_network_scope(tmp_path / "td-mdns-scopes-matter.json", [], "bad").provenance == "unknown"


def test_ha_scope_uses_cached_collection_topology(tmp_path):
    from td_const import HA_MATTER_WS_TOPOLOGY_FILENAME

    (tmp_path / HA_MATTER_WS_TOPOLOGY_FILENAME).write_text(
        '[{"extPanId":"0x78B9775B001C1CBE"}]', encoding="utf-8"
    )
    scope = resolve_network_scope(tmp_path / "td-ha-matter-ws-server-info.json", {"status": "ready"})
    assert scope.ext_pan_id == "78b9775b001c1cbe"
    assert scope.sources == (HA_MATTER_WS_TOPOLOGY_FILENAME,)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("78b9775b001c1cbe", "78b9775b001c1cbe"),
        ("78B9775B001C1CBE", "78b9775b001c1cbe"),
        ("0x78B9775B001C1CBE", "78b9775b001c1cbe"),
        ("78:b9:77:5b:00:1c:1c:be", "78b9775b001c1cbe"),
        (8699115387970395326, "78b9775b001c1cbe"),
        ("8699115387970395326", "78b9775b001c1cbe"),
        ("1234567890123456", "1234567890123456"),
    ],
)
def test_canonical_ext_pan_id(value: object, expected: str) -> None:
    assert canonical_ext_pan_id(value) == expected
    assert network_id_from_ext_pan_id(value) == f"extpan:{expected}"


@pytest.mark.parametrize("value", ["0000000000000000", "island_27db", -1, True])
def test_rejects_invalid_network_identity(value: object) -> None:
    with pytest.raises(ValueError):
        canonical_ext_pan_id(value)