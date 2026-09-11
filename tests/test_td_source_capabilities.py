from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from td_const import MDNS_SCOPES_BR_FILENAME, OTBR_CLI_MESHDIAG_TOPOLOGY_FILENAME
from td_source_capabilities import SourceCapabilityService
import td_webserver


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