import os
import re

import pytest

from node_test_support import run_node, run_node_json


def test_evaluated_node_script_receives_arguments(node_executable):
    assert run_node_json(
        node_executable, "console.log(JSON.stringify(process.argv.slice(1)))",
        '{"input": "kept"}', "second", evaluate=True,
    ) == ['{"input": "kept"}', "second"]


def test_nonzero_node_exit_reports_both_streams(node_executable) -> None:
    with pytest.raises(pytest.fail.Exception) as failure:
        run_node(
            node_executable,
            'console.log("output context"); console.error("error context"); process.exit(3);',
            evaluate=True,
        )
    assert "exit status 3" in str(failure.value)
    assert "output context" in str(failure.value)
    assert "error context" in str(failure.value)


def test_invalid_json_reports_output(node_executable) -> None:
    with pytest.raises(pytest.fail.Exception, match="invalid JSON") as failure:
        run_node_json(node_executable, 'console.log("not JSON")', evaluate=True)
    assert "not JSON" in str(failure.value)


def test_timeout_reports_and_reaps_child(node_executable) -> None:
    with pytest.raises(pytest.fail.Exception, match="timed out") as failure:
        run_node(
            node_executable,
            'console.log(`child-pid:${process.pid}`); console.error("waiting"); setInterval(() => {}, 1000);',
            evaluate=True,
            timeout=2,
        )
    message = str(failure.value)
    assert "waiting" in message
    match = re.search(r"child-pid:(\d+)", message)
    assert match is not None, message
    pid = int(match[1])
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
