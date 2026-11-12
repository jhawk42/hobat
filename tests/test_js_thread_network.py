def test_thread_network_contract(node_json) -> None:
    result = node_json("tests/js/run-thread-network-model.mjs")
    assert result == {"uniqueLinks": 2, "threadDevices": 4}
