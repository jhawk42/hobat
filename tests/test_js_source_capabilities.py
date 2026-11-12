def test_source_capability_contract(node_run) -> None:
    result = node_run("tests/js/run-source-capabilities.mjs")
    assert result.stdout.strip() == "source capability contracts passed"
