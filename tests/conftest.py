from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest
from node_test_support import run_node_json as execute_node_json


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_JSON_FIXTURES = (
	"tests/fixtures/device_merge_contract.json",
	"tests/fixtures/thread_device_field_model.json",
	"tests/fixtures/route_routeData_merged_rows.json",
	"tests/fixtures/route_routeData_single_source.json",
	"tests/fixtures/otbr_route_source_categories.json",
)
REQUIRED_TEXT_FIXTURES = (
	"tests/logs/test_tlvs_7c00.txt",
	"tests/logs/test_tlvs_6000.txt",
)
WEBSERVER_TEST_MODULES = {
	"test_td_webserver_cancel.py",
	"test_td_webserver_checkpoint_serve.py",
	"test_td_webserver_concurrency.py",
	"test_td_webserver_device.py",
	"test_td_webserver_job_poll_metadata.py",
	"test_webserver_helpers.py",
	"test_webserver_smoke.py",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
	for item in items:
		if item.path.name.startswith(("test_frontend_", "test_js_")):
			item.add_marker(pytest.mark.frontend)


@pytest.fixture(autouse=True)
def isolate_webserver_state(request: pytest.FixtureRequest):
	if request.path.name not in WEBSERVER_TEST_MODULES:
		yield
		return

	from webserver_test_support import WEBSERVER_STATE_REGISTRIES, reset_webserver_state

	reset_webserver_state()
	yield
	leaked = {
		name: len(getattr(__import__("td_webserver"), name))
		for name in WEBSERVER_STATE_REGISTRIES
		if getattr(__import__("td_webserver"), name)
	}
	reset_webserver_state()
	assert leaked == {}, f"Webserver test leaked module state: {leaked}"


@pytest.fixture(scope="session", autouse=True)
def validate_committed_fixtures() -> None:
	for relative_path in REQUIRED_JSON_FIXTURES:
		path = REPO_ROOT / relative_path
		assert path.is_file(), f"Required committed fixture is missing: {relative_path}"
		try:
			json.loads(path.read_text(encoding="utf-8"))
		except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
			pytest.fail(f"Required committed fixture is malformed: {relative_path}: {exc}")

	for relative_path in REQUIRED_TEXT_FIXTURES:
		path = REPO_ROOT / relative_path
		assert path.is_file(), f"Required committed fixture is missing: {relative_path}"
		assert path.stat().st_size > 0, f"Required committed fixture is empty: {relative_path}"


@pytest.fixture(scope="session")
def node_executable() -> str:
	node_executable = shutil.which("node")
	if node_executable is None:
		pytest.skip("Node.js is required for frontend contract tests")
	return node_executable


@pytest.fixture(scope="session")
def node_json(node_executable: str) -> Callable[..., Any]:

	def run_node_json(
		script: str | Path,
		*args: str,
		evaluate: bool = False,
		timeout: float = 30,
	) -> Any:
		return execute_node_json(
			node_executable,
			script,
			*args,
			evaluate=evaluate,
			timeout=timeout,
		)

	return run_node_json
