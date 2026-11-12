from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import td_webserver


WEBSERVER_STATE_REGISTRIES = (
    "_active_processes",
    "_source_locks",
    "_job_registry",
    "_job_runtime_registry",
    "_job_id_by_task",
    "_background_tasks",
    "_health_job_id_by_dataset",
    "_device_action_job_registry",
    "_device_action_runtime_registry",
    "_device_action_job_id_by_task",
    "_device_action_background_tasks",
)


def reset_webserver_state() -> None:
    for registry_name in WEBSERVER_STATE_REGISTRIES:
        getattr(td_webserver, registry_name).clear()


async def cleanup_webserver_state() -> None:
    loop = asyncio.get_running_loop()
    current = asyncio.current_task()
    tasks = set()
    for registry_name in WEBSERVER_STATE_REGISTRIES:
        registry = getattr(td_webserver, registry_name)
        entries = (
            (*registry.keys(), *registry.values())
            if isinstance(registry, dict)
            else tuple(registry)
        )
        for entry in entries:
            task = entry if issubclass(type(entry), asyncio.Task) else getattr(entry, "task", None)
            if issubclass(type(task), asyncio.Task) and task is not current:
                assert task.get_loop() is loop, "Webserver task belongs to another test loop"
                tasks.add(task)
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    reset_webserver_state()


async def run_job_cleanup_sweep() -> None:
    with patch.object(td_webserver.asyncio, "sleep", side_effect=[None, asyncio.CancelledError]):
        task = asyncio.create_task(td_webserver._cleanup_job_registry_loop())
        results = await asyncio.gather(task, return_exceptions=True)
    if not task.cancelled():
        raise AssertionError(f"Cleanup did not finish one sweep: {results!r}")


def make_webserver_app(data_dir: Path) -> dict:
    return {td_webserver.TD_DATA_DIR_APP_KEY: data_dir}


def make_data_request(
    filename: str,
    app: object,
    *,
    no_cache: bool = False,
    cache_control: str | None = None,
) -> MagicMock:
    request = MagicMock()
    request.match_info = {"filename": filename}
    request.app = app
    request.headers = (
        {"Cache-Control": cache_control}
        if cache_control is not None
        else ({"Cache-Control": "no-cache"} if no_cache else {})
    )
    return request