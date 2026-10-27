from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from td_const import (
    HA_MATTER_WS_NETWORK_TOPOLOGY_FILENAME,
    HA_MATTER_WS_THREAD_BORDER_ROUTERS_FILENAME,
    MDNS_SCOPES_BR_FILENAME,
    OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME,
)
import td_source_capabilities
from td_source_capabilities import SourceCapabilityService
from td_network_identity import NetworkScope
from util_data import write_network_scope
import td_webserver
import td_unified_dataset
from td_dataset_catalog import load_dataset_catalog
from util_data import network_scope_path


@pytest.mark.parametrize("state", ("child", "router", "leader", "detached", "disabled"))
def test_otbr_cli_probe_accepts_documented_states(monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    monkeypatch.setenv("TD_OTBR_CONTAINER_USE", "1")
    monkeypatch.setattr(
        td_source_capabilities.subprocess,
        "run",
        lambda *args, **kwargs: MagicMock(returncode=0, stdout=f"{state}\n".encode()),
    )

    assert asyncio.run(td_source_capabilities._probe_otbr_cli()) is None


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "expected"),
    (
        (1, b"child\n", b"", "command-failed"),
        (1, b"", b"failed to connect to the docker API at unix:///var/run/docker.sock", "docker-unavailable"),
        (0, b"", b"", "invalid-response"),
        (0, b"Error\n", b"", "invalid-response"),
    ),
)
def test_otbr_cli_probe_rejects_failed_or_invalid_responses(
    monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: bytes, stderr: bytes, expected: str
) -> None:
    monkeypatch.setenv("TD_OTBR_CONTAINER_USE", "1")
    monkeypatch.setattr(
        td_source_capabilities.subprocess,
        "run",
        lambda *args, **kwargs: MagicMock(returncode=returncode, stdout=stdout, stderr=stderr),
    )

    assert asyncio.run(td_source_capabilities._probe_otbr_cli()) == expected


def test_cached_evidence_skips_that_source_probe_and_never_writes_files() -> None:
    calls: list[str] = []

    async def probe(source: str) -> str | None:
        calls.append(source)
        return None

    with tempfile.TemporaryDirectory() as directory:
        data_dir = Path(directory)
        (data_dir / OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME).write_text("[]", encoding="utf-8")
        before = {path.name: path.read_bytes() for path in data_dir.iterdir()}
        service = SourceCapabilityService(
            probes={
                "otbr-cli": lambda: probe("otbr-cli"),
                "otbr-restapi": lambda: probe("otbr-restapi"),
                "ha-matter-ws": lambda: probe("ha-matter-ws"),
            }
        )
        result = asyncio.run(service.capabilities(data_dir))

        assert result["sources"]["otbr-cli"]["state"] == "cached"
        assert "otbr-cli" not in calls
        assert result["sources"]["otbr-restapi"]["state"] == "live"
        assert result["sources"]["ha-matter-ws"]["state"] == "live"
        assert before == {path.name: path.read_bytes() for path in data_dir.iterdir()}


def test_always_available_source_retains_cached_file_metadata() -> None:
    with tempfile.TemporaryDirectory() as directory:
        data_dir = Path(directory)
        (data_dir / MDNS_SCOPES_BR_FILENAME).write_text("[]", encoding="utf-8")
        result = asyncio.run(SourceCapabilityService(probes={}).capabilities(data_dir))

    assert result["sources"]["mdns"] == {
        "state": "available",
        "cached": True,
        "configured": False,
        "probe": {"state": "not-applicable"},
    }


def test_capabilities_only_advertise_digest_valid_instance(tmp_path: Path) -> None:
    snapshot = tmp_path / MDNS_SCOPES_BR_FILENAME
    snapshot.write_text("[]", encoding="utf-8")
    write_network_scope(snapshot, NetworkScope("78b9775b001c1cbe", None, "observed", None, "now", (snapshot.name,)))
    service = SourceCapabilityService(probes={})
    result = asyncio.run(service.capabilities(tmp_path))
    assert result["files"][snapshot.name]["networkInstance"]["extPanId"] == "78b9775b001c1cbe"
    snapshot.write_text("[{}]", encoding="utf-8")
    result = asyncio.run(service.capabilities(tmp_path))
    assert "networkInstance" not in result["files"][snapshot.name]


def test_native_ha_matter_ws_files_are_advertised() -> None:
    with tempfile.TemporaryDirectory() as directory:
        result = asyncio.run(SourceCapabilityService(probes={}).capabilities(Path(directory)))

    for filename in (
        HA_MATTER_WS_THREAD_BORDER_ROUTERS_FILENAME,
        HA_MATTER_WS_NETWORK_TOPOLOGY_FILENAME,
    ):
        assert result["files"][filename] == {
            "cached": False,
            "source": "ha-matter-ws",
        }


def test_failed_probe_is_cached_for_its_ttl() -> None:
    calls = 0

    async def failing_probe() -> str:
        nonlocal calls
        calls += 1
        return "unreachable"

    with tempfile.TemporaryDirectory() as directory:
        service = SourceCapabilityService(
            probes={"otbr-cli": failing_probe}, probe_ttl_seconds=60
        )
        first = asyncio.run(service.capabilities(Path(directory)))
        second = asyncio.run(service.capabilities(Path(directory)))

    assert first["sources"]["otbr-cli"]["state"] == "probe-failed"
    assert second["sources"]["otbr-cli"]["probe"]["state"] == "failed"
    assert calls == 1


def test_concurrent_requests_share_one_inflight_probe() -> None:
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed_probe() -> None:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()

    async def run() -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = SourceCapabilityService(probes={"otbr-cli": delayed_probe})
            first = asyncio.create_task(service.capabilities(Path(directory)))
            await started.wait()
            second = asyncio.create_task(service.capabilities(Path(directory)))
            release.set()
            await asyncio.gather(first, second)

    asyncio.run(run())
    assert calls == 1


def test_capability_handler_returns_no_store_response() -> None:
    with tempfile.TemporaryDirectory() as directory:
        request = MagicMock()
        request.app = {
            td_webserver.TD_DATA_DIR_APP_KEY: Path(directory),
            td_webserver.TD_SOURCE_CAPABILITIES_APP_KEY: SourceCapabilityService(
                probes={}
            ),
        }
        response = asyncio.run(td_webserver.handle_capabilities_api(request))

    body = json.loads(response.text)
    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert body["sources"]["otbr-cli"]["state"] == "unavailable"
    assert body["files"][OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME] == {
        "cached": False,
        "source": "otbr-cli",
    }
    assert body["sources"]["mdns"]["state"] == "available"
    assert body["sources"]["system"]["state"] == "available"


def test_each_unified_product_is_inspected_once_and_unchanged_results_are_reused(
    tmp_path, monkeypatch,
):
    inspect = MagicMock(wraps=td_unified_dataset._inspect_unified_cache)
    monkeypatch.setattr(td_unified_dataset, "_inspect_unified_cache", inspect)
    service = SourceCapabilityService(probes={})
    first = asyncio.run(service.capabilities(tmp_path))
    second = asyncio.run(service.capabilities(tmp_path))
    assert first["files"] == second["files"]
    assert first["sources"] == second["sources"]
    assert inspect.call_count == 5
    assert len({call.args[1]["value"] for call in inspect.call_args_list}) == 5
    first["files"].clear()
    assert asyncio.run(service.capabilities(tmp_path))["files"] == second["files"]


def _watched_unified_files():
    names = set()
    for entry in load_dataset_catalog()["datasets"]:
        if "unified" not in entry:
            continue
        recipe = entry["unified"]
        names.update(entry["files"])
        names.update(item["file"] for item in recipe["inputs"])
        names.update(recipe[key] for key in ("reportFile", "identityFile", "outcomeFile")
                     if recipe[key] is not None)
    return sorted(names | {network_scope_path(name).name for name in names})


@pytest.mark.parametrize("filename", _watched_unified_files())
def test_inspection_cache_tracks_every_artifact_input_and_companion(tmp_path, monkeypatch, filename):
    service = SourceCapabilityService(probes={})
    read = MagicMock(wraps=service._read_files)
    monkeypatch.setattr(service, "_read_files", read)
    path = tmp_path / filename
    asyncio.run(service.capabilities(tmp_path))
    path.write_text("[]")
    asyncio.run(service.capabilities(tmp_path))
    previous = path.stat()
    path.write_text("{}")
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    changed = asyncio.run(service.capabilities(tmp_path))
    fresh = asyncio.run(SourceCapabilityService(probes={}).capabilities(tmp_path))
    assert changed["files"] == fresh["files"]
    assert changed["sources"] == fresh["sources"]
    path.unlink()
    asyncio.run(service.capabilities(tmp_path))
    assert read.call_count == 4


def test_inspection_cache_tracks_catalog_and_directory(tmp_path, monkeypatch):
    service = SourceCapabilityService(probes={})
    catalog = load_dataset_catalog()
    monkeypatch.setattr(td_source_capabilities, "load_dataset_catalog", lambda: deepcopy(catalog))
    read = MagicMock(wraps=service._read_files)
    monkeypatch.setattr(service, "_read_files", read)
    asyncio.run(service.capabilities(tmp_path))
    catalog["authority"]["freshnessSeconds"]["test"] = 1
    asyncio.run(service.capabilities(tmp_path))
    other = tmp_path / "other"
    other.mkdir()
    asyncio.run(service.capabilities(other))
    assert read.call_count == 3


def test_failed_inspection_is_shared_and_next_request_recovers(tmp_path, monkeypatch):
    async def run():
        service = SourceCapabilityService(probes={})
        original = service._read_files
        started = threading.Event()
        release = threading.Event()

        def fail(*args):
            started.set()
            assert release.wait(5)
            raise OSError("inspection failed")

        read = MagicMock(side_effect=fail)
        monkeypatch.setattr(service, "_read_files", read)
        first = asyncio.create_task(service.capabilities(tmp_path))
        assert await asyncio.to_thread(started.wait, 5)
        second = asyncio.create_task(service.capabilities(tmp_path))
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        assert all(isinstance(result, OSError) for result in results)
        assert read.call_count == 1
        monkeypatch.setattr(service, "_read_files", original)
        assert (await service.capabilities(tmp_path))["files"]

    asyncio.run(run())


def test_cancelled_waiter_does_not_cancel_shared_inspection(tmp_path, monkeypatch):
    async def run():
        service = SourceCapabilityService(probes={})
        original = service._read_files
        started = threading.Event()
        release = threading.Event()

        def delayed(*args):
            started.set()
            assert release.wait(5)
            return original(*args)

        read = MagicMock(side_effect=delayed)
        monkeypatch.setattr(service, "_read_files", read)
        first = asyncio.create_task(service.capabilities(tmp_path))
        assert await asyncio.to_thread(started.wait, 5)
        second = asyncio.create_task(service.capabilities(tmp_path))
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        result = await second
        assert (await service.capabilities(tmp_path))["files"] == result["files"]
        assert read.call_count == 1

    asyncio.run(run())


def test_changing_inputs_are_not_cached_as_stable(tmp_path, monkeypatch):
    service = SourceCapabilityService(probes={})
    original = service._read_files
    path = tmp_path / OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME

    def changing(*args):
        files = original(*args)
        path.write_text("[]" if not path.exists() else path.read_text() + " ")
        return files

    monkeypatch.setattr(service, "_read_files", changing)
    with pytest.raises(td_unified_dataset.UnifiedDatasetError, match="changed during inspection"):
        asyncio.run(service.capabilities(tmp_path))
    monkeypatch.setattr(service, "_read_files", original)
    assert asyncio.run(service.capabilities(tmp_path))["files"][path.name]["cached"]


def test_one_input_change_during_inspection_retries_before_publication(tmp_path, monkeypatch):
    service = SourceCapabilityService(probes={})
    original = service._read_files
    path = tmp_path / OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME

    def changing_once(*args):
        files = original(*args)
        if not path.exists():
            path.write_text("[]")
        return files

    read = MagicMock(side_effect=changing_once)
    monkeypatch.setattr(service, "_read_files", read)
    assert asyncio.run(service.capabilities(tmp_path))["files"][path.name]["cached"]
    assert asyncio.run(service.capabilities(tmp_path))["files"][path.name]["cached"]
    assert read.call_count == 2


def test_catalog_change_during_inspection_fails_explicitly_then_recovers(tmp_path, monkeypatch):
    service = SourceCapabilityService(probes={})
    catalog = load_dataset_catalog()
    monkeypatch.setattr(td_source_capabilities, "load_dataset_catalog", lambda: deepcopy(catalog))
    original = service._read_files

    def changing_catalog(*args):
        files = original(*args)
        catalog["authority"]["freshnessSeconds"]["test"] = 1
        return files

    monkeypatch.setattr(service, "_read_files", changing_catalog)
    with pytest.raises(td_unified_dataset.UnifiedDatasetError, match="catalog changed"):
        asyncio.run(service.capabilities(tmp_path))
    monkeypatch.setattr(service, "_read_files", original)
    assert asyncio.run(service.capabilities(tmp_path))["files"]