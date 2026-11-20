from pathlib import Path

from node_test_support import run_node


def test_health_purge_mocked_ui(node_executable: str) -> None:
    run_node(node_executable, Path("tests/js/run-health-purge-ui.mjs"))


def test_job_poll_request_deadlines(node_executable: str) -> None:
    run_node(node_executable, Path("tests/js/run-job-poll-deadlines.mjs"))
