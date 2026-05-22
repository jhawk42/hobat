# Test Coverage Improvement Proposal

## Baseline

- Test command: `PYTHONPATH=/tmp/workspace/jhawk42/tdash/src python -m unittest discover -s tests`
- Existing suite has broad coverage in `td_webserver`, `util_data`, `util_convert`, and selected CLI flows.
- Several source modules are still untested or only indirectly tested.

## Priority Gaps

1. `src/mdns_thread_scopes.py`
   - Add tests for decoder/formatter helpers, enrichment helpers, and listener behavior.

2. `src/otbr_cli_networkdiag_topology.py`
   - Add parser fixture tests (mode, counters, child table, multicast output) and merge-path tests.

3. `src/otbr_restapi_cli.py`
   - Add tests for parser branches, dispatch behavior, output/error handling, and exit-code mapping.

4. `src/util_network.py`
   - Add tests for prefix parsing/building, router detection, and ot-ctl wrapper behavior via mocks.

## Secondary Gaps

- OTBR helper modules (`otbr_cli_meshdiag_*`, `otbr_cli_router_table.py`, `otbr_cli_thread_network_info.py`, `util_ot_ctl.py`)
- REST topology driver (`otbr_restapi_topology.py`)
- Data utilities (`eve_parse.py`, `extaddr_device_label_map.py`) and broader `dataset_merge.py` edge cases

## Immediate Improvements

1. Fix broken imports in current OTBR REST API test modules so they execute in CI/local runs.
2. Add table-driven negative tests (malformed input, missing fields, subprocess/API failures).
3. Add realistic parser fixtures to lock behavior against regressions.
