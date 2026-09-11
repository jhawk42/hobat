from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import td_webserver


WEBSERVER_STATE_REGISTRIES = (
    "_active_processes",
    "_source_locks",
    "_job_registry",
    "_job_runtime_registry",
    "_job_id_by_task",
    "_background_tasks",
    "_device_action_job_registry",
    "_device_action_runtime_registry",
    "_device_action_job_id_by_task",
    "_device_action_background_tasks",
)


def reset_webserver_state() -> None:
    for registry_name in WEBSERVER_STATE_REGISTRIES:
        getattr(td_webserver, registry_name).clear()


def make_webserver_app(data_dir: Path) -> dict:
    return {td_webserver.TD_DATA_DIR_APP_KEY: data_dir}


def make_data_request(
    filename: str,
    app: object,
    *,
    no_cache: bool = False,
) -> MagicMock:
    request = MagicMock()
    request.match_info = {"filename": filename}
    request.app = app
    request.headers = {"Cache-Control": "no-cache"} if no_cache else {}
    return request