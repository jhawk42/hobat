def test_activity_contract(node_run) -> None:
    result = node_run("tests/js/run-activity-contract.mjs")
    assert result.stdout.strip() == "activity contracts passed"
