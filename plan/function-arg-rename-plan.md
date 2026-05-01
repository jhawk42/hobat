# Function Argument Rename Plan

## Overview

This document proposes renames (and keep decisions) for all function argument names across
`src/*.py` files. Proposed names must be:

- **Snake case** – `lower_with_underscores`
- **Compact** – no unnecessary words
- **Simple** – easy to understand without extra context

---

## Structured Phases

### Phase 1 – Analysis *(completed)*
- Review all `src/*.py` files
- Extract every unique function argument
- Evaluate against snake_case, compactness, and clarity criteria

### Phase 2 – Review *(current phase — awaiting approval)*
- Present findings in the table below
- Owner reviews and approves / modifies proposals
- **Do not apply any renames until review is complete**

### Phase 3 – Implementation *(pending review)*
- Apply approved renames to each function definition
- Update every call site that passes the renamed argument by keyword
- Run existing tests (`pytest`) to verify no regressions
- Commit and push

---

## Findings Table

> **Legend** – Action column: **Keep** = no change needed; **Rename** = proposed change with reason.

| `.py` file | function name | current argument name | new argument name | action | comment |
|---|---|---|---|---|---|
| `otbr_cli_network_dataset_info.py` | `main` | `argv` | `argv` | Keep | Standard Python entry-point convention |
| `web_server.py` | `TDashHandler.__init__` | `directory` | `directory` | Keep | Inherits from `SimpleHTTPRequestHandler`; must match parent |
| `web_server.py` | `TDashHandler.__init__` | `td_data_dir` | `td_data_dir` | Keep | Clear, descriptive, snake_case |
| `web_server.py` | `_is_json_request` | `request_path` | `request_path` | Keep | Clear, snake_case |
| `web_server.py` | `_resolve_json_file_path` | `request_path` | `request_path` | Keep | Clear, snake_case |
| `web_server.py` | `_serve_json_from_data_dir` | `request_path` | `request_path` | Keep | Clear, snake_case |
| `web_server.py` | `main` | `argv` | `argv` | Keep | Standard |
| `otbr_cli_meshdiag_childip6.py` | `fetch_meshdiag_child_ip6_for_device` | `parent_rloc16` | `parent_rloc16` | Keep | Precise domain term |
| `otbr_cli_meshdiag_childip6.py` | `fetch_meshdiag_child_ip6_for_device` | `router` | `router` | Keep | Simple, clear |
| `otbr_cli_meshdiag_childip6.py` | `fetch_meshdiag_child_ip6_for_device` | `extaddr_map` | `extaddr_map` | Keep | Consistent across codebase |
| `otbr_cli_meshdiag_childip6.py` | `fetch_all_meshdiag_child_ip6_tables` | `extaddr_map` | `extaddr_map` | Keep | Consistent across codebase |
| `otbr_cli_meshdiag_childip6.py` | `main` | `argv` | `argv` | Keep | Standard |
| `util_ot_ctl.py` | `exec_ot_ctl_dispatch` | `ot_command` | `cmd` | Rename | `ot_command` is redundant — the function name already establishes ot-ctl context; `cmd` is compact and clear |
| `util_ot_ctl.py` | `exec_ot_ctl_dispatch` | `container_name` | `container_name` | Keep | Clear, snake_case |
| `util_ot_ctl.py` | `exec_ot_ctl` | `command` | `command` | Keep | Simple, clear |
| `util_ot_ctl.py` | `exec_ot_ctl` | `container_name` | `container_name` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_meshdiag_router_neighbor_table_for_device` | `rloc16` | `rloc16` | Keep | Standard Thread term |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_meshdiag_router_neighbor_table_for_device` | `router` | `router` | Keep | Simple, clear |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_meshdiag_router_neighbor_table_for_device` | `extaddr_map` | `extaddr_map` | Keep | Consistent |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_all_meshdiag_router_neighbor_tables` | `extaddr_map` | `extaddr_map` | Keep | Consistent |
| `otbr_cli_meshdiag_routerneighbortable.py` | `main` | `argv` | `argv` | Keep | Standard |
| `util_data.py` | `_normalize_path` | `path_value` | `path` | Rename | `_value` suffix is redundant; the type annotation already conveys it is a path value |
| `util_data.py` | `_normalize_path` | `cwd` | `cwd` | Keep | Standard abbreviation for current working directory |
| `util_data.py` | `_normalize_optional_path` | `value` | `value` | Keep | Generic, acceptable for private helper |
| `util_data.py` | `parse_datadir_from_argv` | `argv` | `argv` | Keep | Standard |
| `util_data.py` | `resolve_data_dir_with_source` | `datadir_arg` | `data_dir` | Rename | `_arg` suffix is noise; `data_dir` is shorter and equally clear |
| `util_data.py` | `resolve_data_dir_with_source` | `env` | `env` | Keep | Compact, standard |
| `util_data.py` | `resolve_data_dir_with_source` | `cwd` | `cwd` | Keep | Standard abbreviation |
| `util_data.py` | `resolve_data_dir` | `datadir_arg` | `data_dir` | Rename | Same rationale as `resolve_data_dir_with_source` |
| `util_data.py` | `resolve_data_dir` | `env` | `env` | Keep | Compact |
| `util_data.py` | `resolve_data_dir` | `cwd` | `cwd` | Keep | Standard |
| `util_data.py` | `ensure_data_dir_exists` | `path` | `path` | Keep | Simple, clear |
| `util_data.py` | `format_data_dir_log_message` | `resolution` | `resolution` | Keep | Clear, matches the dataclass type |
| `util_data.py` | `data_file_path` | `filename` | `filename` | Keep | Simple, clear |
| `util_data.py` | `data_file_path` | `td_data_dir` | `td_data_dir` | Keep | Consistent across codebase |
| `util_data.py` | `resolve_data_file_path` | `path_or_name` | `file_path` | Rename | `path_or_name` is ambiguous and verbose; `file_path` is direct and compact |
| `util_data.py` | `resolve_data_file_path` | `td_data_dir` | `td_data_dir` | Keep | Consistent |
| `td_cli.py` | `TDHelpFormatter.__init__` | `prog` | `prog` | Keep | Inherits from `argparse`; must match parent signature |
| `td_cli.py` | `_add_otbr_cli_commands` | `subparsers` | `subparsers` | Keep | Standard `argparse` convention |
| `td_cli.py` | `_add_otbr_restapi_commands` | `subparsers` | `subparsers` | Keep | Standard `argparse` convention |
| `td_cli.py` | `_add_process_commands` | `subparsers` | `subparsers` | Keep | Standard `argparse` convention |
| `td_cli.py` | `_add_merge_commands` | `subparsers` | `subparsers` | Keep | Standard `argparse` convention |
| `td_cli.py` | `dispatch` | `args` | `args` | Keep | Standard `argparse` convention |
| `td_cli.py` | `dispatch` | `sub_argv` | `extra_args` | Rename | `sub_argv` conflates two concepts; `extra_args` clearly means unrecognised arguments forwarded to sub-modules |
| `td_cli.py` | `dispatch` | `parser` | `parser` | Keep | Standard `argparse` convention |
| `td_cli.py` | `main` | `argv` | `argv` | Keep | Standard |
| `otbr_restapi_raw_client.py` | `OTBRRawRestApiClient.__init__` | `host` | `host` | Keep | Standard HTTP client term |
| `otbr_restapi_raw_client.py` | `OTBRRawRestApiClient.__init__` | `port` | `port` | Keep | Standard |
| `otbr_restapi_raw_client.py` | `OTBRRawRestApiClient.__init__` | `base_url` | `base_url` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client.py` | `OTBRRawRestApiClient.__init__` | `timeout` | `timeout` | Keep | Standard |
| `otbr_restapi_raw_client.py` | `OTBRRawRestApiClient.__init__` | `accept` | `accept` | Keep | Standard HTTP header name |
| `otbr_restapi_raw_client.py` | `OTBRRawRestApiClient.__init__` | `user_agent` | `user_agent` | Keep | Standard |
| `otbr_restapi_raw_client.py` | `get_node` | `fields` | `fields` | Keep | Clear, compact |
| `otbr_restapi_raw_client.py` | `get_node` | `raw` | `raw` | Keep | Clear flag name |
| `otbr_restapi_raw_client.py` | `get_active_dataset` | `plain_text` | `plain_text` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client.py` | `get_active_dataset` | `raw` | `raw` | Keep | Clear flag name |
| `otbr_restapi_raw_client.py` | `list_devices` | `fields` | `fields` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `list_devices` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `list_devices` | `with_meta` | `with_meta` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client.py` | `get_device` | `device_id` | `device_id` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client.py` | `get_device` | `fields` | `fields` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `get_device` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `list_diagnostics` | `fields` | `fields` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `list_diagnostics` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `list_diagnostics` | `with_meta` | `with_meta` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `get_diagnostic` | `diagnostics_id` | `diagnostics_id` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client.py` | `get_diagnostic` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `list_actions` | `fields` | `fields` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `list_actions` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `list_actions` | `with_meta` | `with_meta` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `get_action` | `action_id` | `action_id` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client.py` | `get_action` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `enqueue_actions` | `tasks` | `tasks` | Keep | Clear, compact |
| `otbr_restapi_raw_client.py` | `enqueue_actions` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `enqueue_add_thread_device_task` | `pskd` | `pskd` | Keep | Domain-specific Thread term |
| `otbr_restapi_raw_client.py` | `enqueue_add_thread_device_task` | `eui` | `eui` | Keep | Domain-specific term (EUI-64) |
| `otbr_restapi_raw_client.py` | `enqueue_add_thread_device_task` | `discerner` | `discerner` | Keep | Domain-specific Thread term |
| `otbr_restapi_raw_client.py` | `enqueue_add_thread_device_task` | `joiner_id` | `joiner_id` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client.py` | `enqueue_add_thread_device_task` | `timeout` | `timeout` | Keep | Standard |
| `otbr_restapi_raw_client.py` | `enqueue_add_thread_device_task` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `enqueue_get_network_diagnostic_task` | `destination` | `destination` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `enqueue_get_network_diagnostic_task` | `types` | `types` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `enqueue_get_network_diagnostic_task` | `timeout` | `timeout` | Keep | Standard |
| `otbr_restapi_raw_client.py` | `enqueue_get_network_diagnostic_task` | `destination_type` | `destination_type` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client.py` | `enqueue_get_network_diagnostic_task` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `enqueue_reset_network_diag_counter_task` | `types` | `types` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `enqueue_reset_network_diag_counter_task` | `destination` | `destination` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `enqueue_reset_network_diag_counter_task` | `timeout` | `timeout` | Keep | Standard |
| `otbr_restapi_raw_client.py` | `enqueue_reset_network_diag_counter_task` | `destination_type` | `destination_type` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client.py` | `enqueue_reset_network_diag_counter_task` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `enqueue_get_energy_scan_task` | `destination` | `destination` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `enqueue_get_energy_scan_task` | `channel_mask` | `channel_mask` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client.py` | `enqueue_get_energy_scan_task` | `count` | `count` | Keep | Simple |
| `otbr_restapi_raw_client.py` | `enqueue_get_energy_scan_task` | `period` | `period` | Keep | Simple |
| `otbr_restapi_raw_client.py` | `enqueue_get_energy_scan_task` | `scan_duration` | `scan_duration` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client.py` | `enqueue_get_energy_scan_task` | `timeout` | `timeout` | Keep | Standard |
| `otbr_restapi_raw_client.py` | `enqueue_get_energy_scan_task` | `destination_type` | `destination_type` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `enqueue_get_energy_scan_task` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_raw_client.py` | `enqueue_update_device_collection_task` | `max_age` | `max_age` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client.py` | `enqueue_update_device_collection_task` | `max_retries` | `max_retries` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client.py` | `enqueue_update_device_collection_task` | `device_count` | `device_count` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client.py` | `enqueue_update_device_collection_task` | `timeout` | `timeout` | Keep | Standard |
| `otbr_restapi_raw_client.py` | `enqueue_update_device_collection_task` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_client_cli.py` | `_add_node_commands` | `subparsers` | `subparsers` | Keep | Standard `argparse` convention |
| `otbr_restapi_client_cli.py` | `_add_devices_commands` | `subparsers` | `subparsers` | Keep | Standard `argparse` convention |
| `otbr_restapi_client_cli.py` | `_add_diagnostics_commands` | `subparsers` | `subparsers` | Keep | Standard `argparse` convention |
| `otbr_restapi_client_cli.py` | `_add_actions_commands` | `subparsers` | `subparsers` | Keep | Standard `argparse` convention |
| `otbr_restapi_client_cli.py` | `_add_fields_argument` | `parser` | `parser` | Keep | Standard `argparse` convention |
| `otbr_restapi_client_cli.py` | `build_client` | `args` | `args` | Keep | Standard `argparse` convention |
| `otbr_restapi_client_cli.py` | `dispatch` | `args` | `args` | Keep | Standard `argparse` convention |
| `otbr_restapi_client_cli.py` | `_parse_dataset_input` | `args` | `args` | Keep | Standard |
| `otbr_restapi_client_cli.py` | `_parse_typed_values` | `values` | `values` | Keep | Simple, clear |
| `otbr_restapi_client_cli.py` | `emit_output` | `result` | `result` | Keep | Simple |
| `otbr_restapi_client_cli.py` | `emit_output` | `output_path` | `output_path` | Keep | Clear, snake_case |
| `otbr_restapi_client_cli.py` | `emit_error` | `exc` | `exc` | Keep | Standard Python convention |
| `otbr_restapi_client_cli.py` | `exit_code_for_exception` | `exc` | `exc` | Keep | Standard |
| `otbr_restapi_client_cli.py` | `main` | `argv` | `argv` | Keep | Standard |
| `util_convert.py` | `b64_to_extended_address` | `b64_str` | `b64` | Rename | `_str` suffix is redundant; type hint conveys it's a string; `b64` is compact and clear |
| `util_convert.py` | `b64_to_extended_address` | `reverse` | `reverse` | Keep | Clear flag |
| `util_convert.py` | `extended_address_to_b64` | `hex_str` | `hex_addr` | Rename | `hex_str` is too generic; `hex_addr` clearly indicates this is a hex-encoded address |
| `util_convert.py` | `extended_address_to_b64` | `reverse` | `reverse` | Keep | Clear flag |
| `util_convert.py` | `extaddr_hex_to_base64` | `hex_number` | `hex_addr` | Rename | Misleading — the value is a hex string, not a number; `hex_addr` is accurate and compact |
| `util_convert.py` | `extaddr_hex_to_base64` | `reverse` | `reverse` | Keep | Clear flag |
| `otbr_restapi_client.py` | `OTBRHTTPError.__init__` | `status_code` | `status_code` | Keep | Standard HTTP term, snake_case |
| `otbr_restapi_client.py` | `OTBRHTTPError.__init__` | `reason` | `reason` | Keep | Standard HTTP term |
| `otbr_restapi_client.py` | `OTBRHTTPError.__init__` | `url` | `url` | Keep | Simple, standard |
| `otbr_restapi_client.py` | `OTBRHTTPError.__init__` | `errors` | `errors` | Keep | Clear |
| `otbr_restapi_client.py` | `OTBRHTTPError.__init__` | `payload` | `payload` | Keep | Standard HTTP term |
| `otbr_restapi_client.py` | `OTBRHTTPError.__init__` | `body` | `body` | Keep | Standard HTTP term |
| `otbr_restapi_client.py` | `OTBRRestApiClient.__init__` | `host` | `host` | Keep | Standard |
| `otbr_restapi_client.py` | `OTBRRestApiClient.__init__` | `port` | `port` | Keep | Standard |
| `otbr_restapi_client.py` | `OTBRRestApiClient.__init__` | `base_url` | `base_url` | Keep | Clear, snake_case |
| `otbr_restapi_client.py` | `OTBRRestApiClient.__init__` | `timeout` | `timeout` | Keep | Standard |
| `otbr_restapi_client.py` | `OTBRRestApiClient.__init__` | `retries` | `retries` | Keep | Clear |
| `otbr_restapi_client.py` | `OTBRRestApiClient.__init__` | `accept` | `accept` | Keep | Standard HTTP header name |
| `otbr_restapi_client.py` | `OTBRRestApiClient.__init__` | `user_agent` | `user_agent` | Keep | Standard HTTP header name, snake_case |
| `otbr_restapi_client.py` | `set_node_state` | `value` | `state` | Rename | `value` is too generic; `state` directly indicates what is being set (e.g., "enable"/"disable") |
| `otbr_restapi_client.py` | `set_active_dataset` | `dataset` | `dataset` | Keep | Clear |
| `otbr_restapi_client.py` | `get_node` | `fields` | `fields` | Keep | Clear |
| `otbr_restapi_client.py` | `get_node` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_client.py` | `get_active_dataset` | `plain_text` | `plain_text` | Keep | Clear, snake_case |
| `otbr_restapi_client.py` | `get_active_dataset` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_client.py` | `_request` | `path` | `path` | Keep | Simple, clear |
| `otbr_restapi_client.py` | `_request` | `method` | `method` | Keep | Standard HTTP term |
| `otbr_restapi_client.py` | `_request` | `query` | `query` | Keep | Standard HTTP term |
| `otbr_restapi_client.py` | `_request` | `data` | `data` | Keep | Simple, standard |
| `otbr_restapi_client.py` | `_request` | `accept` | `accept` | Keep | Standard HTTP header name |
| `otbr_restapi_client.py` | `_request` | `content_type` | `content_type` | Keep | Standard HTTP header name, snake_case |
| `otbr_restapi_client.py` | `_request` | `raw` | `raw` | Keep | Clear |
| `otbr_restapi_client.py` | `_request` | `with_meta` | `with_meta` | Keep | Clear |
| `otbr_restapi_client.py` | `_request` | `timeout` | `timeout` | Keep | Standard |
| `otbr_restapi_client.py` | `_request` | `retries` | `retries` | Keep | Clear |
| `util_network.py` | `_parse_prefix_token` | `command_output` | `output` | Rename | `command_output` is verbose; `output` is compact and equally clear in this private helper |
| `util_network.py` | `_strip_prefix_mask` | `prefix` | `prefix` | Keep | Simple, clear |
| `util_network.py` | `_fetch_prefix_via_ot_ctl` | `command` | `command` | Keep | Simple, clear |
| `util_network.py` | `_fetch_prefix_via_ot_ctl` | `debug_label` | `label` | Rename | `debug_` prefix is redundant noise; `label` is compact and self-evident |
| `util_network.py` | `_build_ipv6_prefix_by_type` | `prefix` | `prefix` | Keep | Simple, clear |
| `util_network.py` | `_build_ipv6_prefix_by_type` | `kind` | `kind` | Keep | Simple, clear |
| `util_network.py` | `build_rloc_ipv6_address_prefix` | `meshlocal_prefix` | `ml_prefix` | Rename | `meshlocal_prefix` is long; `ml_prefix` is a well-known abbreviation (mesh-local) in Thread specs and is compact |
| `util_network.py` | `build_rloc16_ipv6_address` | `ipv6_rloc_prefix` | `rloc_prefix` | Rename | The `ipv6_` qualifier is obvious from context; `rloc_prefix` is compact and clear |
| `util_network.py` | `build_rloc16_ipv6_address` | `rloc_hex` | `rloc_hex` | Keep | Clear, compact |
| `util_network.py` | `build_omr_ipv6_address_prefix` | `omr_prefix` | `omr_prefix` | Keep | Clear, compact |
| `util_network.py` | `is_ipv6_address_in_omr_prefix` | `ipv6_address` | `addr` | Rename | `ipv6_address` is redundant given the function name already says `ipv6_address`; `addr` is compact |
| `util_network.py` | `is_ipv6_address_in_omr_prefix` | `omr_ipv6_prefix` | `omr_prefix` | Rename | `_ipv6_` qualifier is redundant; `omr_prefix` is shorter and consistent with `build_omr_ipv6_address_prefix` parameter |
| `util_network.py` | `find_omr_address_in_list` | `ipv6_addrs` | `ipv6_addrs` | Keep | Clear, compact, consistent with data field names in JSON output |
| `util_network.py` | `find_omr_address_in_list` | `omr_ipv6_prefix` | `omr_prefix` | Rename | Same rationale as `is_ipv6_address_in_omr_prefix`; shorter and consistent |
| `util_network.py` | `fetch_dataset_active` | `hideSensitiveInfo` | `hide_sensitive` | Rename | **Critical**: `hideSensitiveInfo` is camelCase, violating Python snake_case convention; `hide_sensitive` is concise and clear |
| `otbr_cli_networkdiag_topology.py` | `parse_ipv6_address_list` | `output` | `output` | Keep | Simple, clear |
| `otbr_cli_networkdiag_topology.py` | `device_type_from_mode` | `mode` | `mode` | Keep | Simple, clear |
| `otbr_cli_networkdiag_topology.py` | `parse_mode_flags` | `output` | `output` | Keep | Simple, clear |
| `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `output` | `output` | Keep | Simple, clear |
| `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `parent_rloc16` | `parent_rloc16` | Keep | Precise domain term |
| `otbr_cli_networkdiag_topology.py` | `parse_mac_counters` | `output` | `output` | Keep | Simple, clear |
| `otbr_cli_networkdiag_topology.py` | `parse_mle_counters` | `output` | `output` | Keep | Simple, clear |
| `otbr_cli_networkdiag_topology.py` | `parse_time_statistics` | `output` | `output` | Keep | Simple, clear |
| `otbr_cli_networkdiag_topology.py` | `fetch_network_diag_for_device` | `rloc` | `rloc16` | Rename | Inconsistent with rest of codebase which uniformly uses `rloc16`; adds clarity on the address format |
| `otbr_cli_networkdiag_topology.py` | `fetch_network_diag_for_device` | `ipv6_rloc_prefix` | `rloc_prefix` | Rename | Same rationale as `util_network.build_rloc16_ipv6_address`; `rloc_prefix` is compact and unambiguous |
| `otbr_cli_networkdiag_topology.py` | `fetch_network_diag_for_device` | `extaddr_map` | `extaddr_map` | Keep | Consistent across codebase |
| `otbr_cli_networkdiag_topology.py` | `fetch_network_diag_for_device` | `ipv6_addresses` | `ipv6_addresses` | Keep | Clear, descriptive |
| `otbr_cli_networkdiag_topology.py` | `fetch_network_diag_for_device` | `tlv_detail_level` | `tlv_detail_level` | Keep | Descriptive, clearly conveys the level of TLV detail requested |
| `otbr_cli_networkdiag_topology.py` | `fetch_network_diag_topology` | `extaddr_map` | `extaddr_map` | Keep | Consistent |
| `otbr_cli_networkdiag_topology.py` | `fetch_network_diag_topology` | `network_dataset_info` | `dataset_info` | Rename | `network_` prefix is redundant (context is always network); `dataset_info` is compact and clear |
| `otbr_cli_networkdiag_topology.py` | `fetch_network_diag_topology` | `expand_children` | `expand_children` | Keep | Clear, descriptive |
| `dataset_merge.py` | `load_json` | `path` | `path` | Keep | Simple |
| `dataset_merge.py` | `normalize_identifier_text` | `value` | `value` | Keep | Generic, appropriate for text normalisation helper |
| `dataset_merge.py` | `first_normalized_identifier` | `record` | `record` | Keep | Clear |
| `dataset_merge.py` | `first_normalized_identifier` | `keys` | `keys` | Keep | Simple, clear |
| `dataset_merge.py` | `get_canonical_extaddr` | `record` | `record` | Keep | Clear |
| `dataset_merge.py` | `get_canonical_omr` | `record` | `record` | Keep | Clear |
| `dataset_merge.py` | `normalize_record_aliases` | `record` | `record` | Keep | Clear |
| `dataset_merge.py` | `derive_mode_device` | `record` | `record` | Keep | Clear |
| `dataset_merge.py` | `normalize_identifiers` | `record` | `record` | Keep | Clear |
| `dataset_merge.py` | `normalize_identifiers` | `omr_prefix` | `omr_prefix` | Keep | Clear, compact |
| `dataset_merge.py` | `load_extaddr_device_label_map` | `path` | `path` | Keep | Simple |
| `dataset_merge.py` | `extract_records` | `filename` | `filename` | Keep | Clear |
| `dataset_merge.py` | `extract_records` | `data` | `data` | Keep | Simple |
| `dataset_merge.py` | `value_is_empty` | `value` | `value` | Keep | Simple |
| `dataset_merge.py` | `merge_unique_strings` | `existing` | `existing` | Keep | Clear |
| `dataset_merge.py` | `merge_unique_strings` | `incoming` | `incoming` | Keep | Clear |
| `dataset_merge.py` | `values_equivalent` | `left` | `left` | Keep | Clear, standard for comparison params |
| `dataset_merge.py` | `values_equivalent` | `right` | `right` | Keep | Clear, standard for comparison params |
| `dataset_merge.py` | `append_merge_conflict` | `base` | `base` | Keep | Clear |
| `dataset_merge.py` | `append_merge_conflict` | `path` | `path` | Keep | Clear |
| `dataset_merge.py` | `append_merge_conflict` | `current_value` | `cur_val` | Rename | `current_value` is verbose; `cur_val` is compact and consistent with `incoming_value` → `new_val` |
| `dataset_merge.py` | `append_merge_conflict` | `incoming_value` | `new_val` | Rename | `incoming_value` is verbose; `new_val` clearly indicates the newly arriving value being compared |
| `dataset_merge.py` | `merge_lists` | `a_list` | `left` | Rename | `a_list` is non-descriptive; `left` is clear and consistent with `values_equivalent(left, right)` naming |
| `dataset_merge.py` | `merge_lists` | `b_list` | `right` | Rename | `b_list` is non-descriptive; `right` is clear and consistent |
| `dataset_merge.py` | `deep_merge` | `base` | `base` | Keep | Clear, standard for merge target |
| `dataset_merge.py` | `deep_merge` | `incoming` | `incoming` | Keep | Clear |
| `dataset_merge.py` | `deep_merge` | `path_prefix` | `path_prefix` | Keep | Clear, snake_case |
| `dataset_merge.py` | `deep_merge` | `conflict_target` | `conflict_target` | Keep | Clear |
| `dataset_merge.py` | `nested_get` | `record` | `record` | Keep | Clear |
| `dataset_merge.py` | `nested_get` | `dotted_key` | `dotted_key` | Keep | Clear, descriptive |
| `dataset_merge.py` | `collect_merge_identity_values` | `record` | `record` | Keep | Clear |
| `dataset_merge.py` | `find_candidate_node_ids` | `identity_values` | `identity_values` | Keep | Clear |
| `dataset_merge.py` | `find_candidate_node_ids` | `by_rloc16` | `by_rloc16` | Keep | Clear index naming convention |
| `dataset_merge.py` | `find_candidate_node_ids` | `by_extaddr` | `by_extaddr` | Keep | Clear index naming convention |
| `dataset_merge.py` | `find_candidate_node_ids` | `by_omr` | `by_omr` | Keep | Clear index naming convention |
| `dataset_merge.py` | `index_node_identity_values` | `node` | `node` | Keep | Clear |
| `dataset_merge.py` | `index_node_identity_values` | `node_id` | `node_id` | Keep | Clear, snake_case |
| `dataset_merge.py` | `index_node_identity_values` | `by_rloc16` | `by_rloc16` | Keep | Consistent |
| `dataset_merge.py` | `index_node_identity_values` | `by_extaddr` | `by_extaddr` | Keep | Consistent |
| `dataset_merge.py` | `index_node_identity_values` | `by_omr` | `by_omr` | Keep | Consistent |
| `dataset_merge.py` | `add_identifier` | `index` | `index` | Keep | Clear |
| `dataset_merge.py` | `add_identifier` | `key` | `key` | Keep | Simple |
| `dataset_merge.py` | `add_identifier` | `node_id` | `node_id` | Keep | Clear |
| `dataset_merge.py` | `merge_nodes` | `target_id` | `target_id` | Keep | Clear, snake_case |
| `dataset_merge.py` | `merge_nodes` | `source_id` | `source_id` | Keep | Clear, snake_case |
| `dataset_merge.py` | `merge_nodes` | `nodes` | `nodes` | Keep | Clear |
| `dataset_merge.py` | `merge_nodes` | `by_rloc16` | `by_rloc16` | Keep | Consistent |
| `dataset_merge.py` | `merge_nodes` | `by_extaddr` | `by_extaddr` | Keep | Consistent |
| `dataset_merge.py` | `merge_nodes` | `by_omr` | `by_omr` | Keep | Consistent |
| `dataset_merge.py` | `build_merged_records` | `base_dir` | `base_dir` | Keep | Clear, snake_case |
| `dataset_merge.py` | `build_merged_records` | `omr_prefix` | `omr_prefix` | Keep | Clear, compact |
| `dataset_merge.py` | `build_merged_records` | `input_files` | `input_files` | Keep | Clear, snake_case |
| `dataset_merge.py` | `build_merged_records` | `extaddr_to_device_label` | `label_map` | Rename | `extaddr_to_device_label` is verbose; `label_map` is compact and clearly implies a lookup dict |
| `dataset_merge.py` | `parse_file_list_args` | `values` | `values` | Keep | Simple |
| `dataset_merge.py` | `resolve_input_files` | `default_files` | `default_files` | Keep | Clear |
| `dataset_merge.py` | `resolve_input_files` | `include_files` | `include_files` | Keep | Clear |
| `dataset_merge.py` | `resolve_input_files` | `exclude_files` | `exclude_files` | Keep | Clear |
| `dataset_merge.py` | `parse_args` | `argv` | `argv` | Keep | Standard |
| `dataset_merge.py` | `main` | `argv` | `argv` | Keep | Standard |
| `eve_parse.py` | `load_and_parse_eve_file` | `path` | `path` | Keep | Simple |
| `eve_parse.py` | `load_and_parse_eve_file` | `network_dataset_info` | `dataset_info` | Rename | `network_` prefix is redundant; `dataset_info` is compact; consistent with proposed rename in other files |
| `eve_parse.py` | `enhance_eve_routes` | `eve_network_enhanced_data` | `eve_data` | Rename | Overly verbose; `eve_data` is compact and clear — the function name already conveys it enhances routes |
| `eve_parse.py` | `main` | `argv` | `argv` | Keep | Standard |
| `mdns_thread_scopes.py` | `get_vendor_from_oui` | `oui_hex` | `oui` | Rename | `_hex` suffix is redundant — OUI values are always hex by definition; `oui` is compact |
| `mdns_thread_scopes.py` | `decode_state_bitmap_br` | `sb_hex` | `sb_val` | Rename | `_hex` format is not always the input type; `sb_val` is consistent with other `decode_*` functions using `*_value` convention |
| `mdns_thread_scopes.py` | `format_state_bitmap_br` | `bits` | `bits` | Keep | Simple, consistent with other `format_*` functions |
| `mdns_thread_scopes.py` | `decode_hap_status_flags` | `sf_value` | `sf_value` | Keep | Consistent with other `decode_*` functions |
| `mdns_thread_scopes.py` | `format_hap_status_flags` | `bits` | `bits` | Keep | Simple, consistent |
| `mdns_thread_scopes.py` | `decode_hap_feature_flags` | `ff_value` | `ff_value` | Keep | Consistent naming convention |
| `mdns_thread_scopes.py` | `format_hap_feature_flags` | `bits` | `bits` | Keep | Simple, consistent |
| `mdns_thread_scopes.py` | `get_hap_category_name` | `ci_value` | `ci_value` | Keep | Consistent naming convention |
| `mdns_thread_scopes.py` | `get_matter_device_type_name` | `dt_value` | `dt_value` | Keep | Consistent naming convention |
| `mdns_thread_scopes.py` | `parse_matter_vp` | `vp_value` | `vp_value` | Keep | Consistent naming convention |
| `mdns_thread_scopes.py` | `decode_matter_commissioning_data` | `cd_value` | `cd_value` | Keep | Consistent naming convention |
| `mdns_thread_scopes.py` | `format_matter_commissioning_data` | `bits` | `bits` | Keep | Simple, consistent |
| `mdns_thread_scopes.py` | `decode_matter_tcp_support` | `t_value` | `t_value` | Keep | Consistent naming convention |
| `mdns_thread_scopes.py` | `get_pairing_hint_description` | `ph_value` | `ph_value` | Keep | Consistent naming convention |
| `mdns_thread_scopes.py` | `decode_hap_setup_hash` | `sh_value` | `sh_value` | Keep | Consistent naming convention |
| `mdns_thread_scopes.py` | `decode_thread_partition_id` | `pt_value` | `pt_value` | Keep | Consistent naming convention |
| `mdns_thread_scopes.py` | `decode_thread_beacon_bitmap` | `bb_value` | `bb_value` | Keep | Consistent naming convention |
| `mdns_thread_scopes.py` | `format_thread_beacon_bitmap` | `bits` | `bits` | Keep | Simple, consistent |
| `mdns_thread_scopes.py` | `decode_matter_icd_capability` | `icd_value` | `icd_value` | Keep | Consistent naming convention |
| `mdns_thread_scopes.py` | `parse_fabric_and_node_ids_from_name` | `service_name` | `service_name` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `_base_field_dict` | `raw_value` | `raw_value` | Keep | Clear, consistent across all `_enrich_*` functions |
| `mdns_thread_scopes.py` | `_base_field_dict` | `full_name` | `full_name` | Keep | Clear, consistent |
| `mdns_thread_scopes.py` | `_enrich_field_sb` | `raw_value` | `raw_value` | Keep | Consistent pattern |
| `mdns_thread_scopes.py` | `_enrich_field_sb` | `full_name` | `full_name` | Keep | Consistent pattern |
| `mdns_thread_scopes.py` | `_enrich_field_bb` | `raw_value` | `raw_value` | Keep | Consistent pattern |
| `mdns_thread_scopes.py` | `_enrich_field_bb` | `full_name` | `full_name` | Keep | Consistent pattern |
| `mdns_thread_scopes.py` | `_enrich_field_at` | `raw_value` | `raw_value` | Keep | Consistent pattern |
| `mdns_thread_scopes.py` | `_enrich_field_at` | `full_name` | `full_name` | Keep | Consistent pattern |
| `mdns_thread_scopes.py` | `_enrich_field_xa` | `raw_value` | `raw_value` | Keep | Consistent pattern |
| `mdns_thread_scopes.py` | `_enrich_field_xa` | `full_name` | `full_name` | Keep | Consistent pattern |
| `otbr_cli_meshdiag_childtable.py` | `_parse_yes_no_to_bool` | `value` | `value` | Keep | Simple, generic |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `parent_rloc16` | `parent_rloc16` | Keep | Precise domain term |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `router` | `router` | Keep | Simple |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `extaddr_map` | `extaddr_map` | Keep | Consistent |
| `otbr_cli_meshdiag_childtable.py` | `fetch_all_meshdiag_child_tables` | `extaddr_map` | `extaddr_map` | Keep | Consistent |
| `otbr_cli_meshdiag_childtable.py` | `main` | `argv` | `argv` | Keep | Standard |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `output` | `output` | Keep | Simple |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `extaddr_map` | `extaddr_map` | Keep | Consistent |
| `otbr_cli_meshdiag_topology.py` | `enhance_topology_router_links` | `topology_data` | `topology_data` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `enhance_topology_router_links` | `network_dataset_info` | `dataset_info` | Rename | `network_` prefix redundant; `dataset_info` is compact; consistent with proposed renames elsewhere |
| `otbr_cli_meshdiag_topology.py` | `get_meshdiag_topology` | `extaddr_map` | `extaddr_map` | Keep | Consistent |
| `otbr_cli_meshdiag_topology.py` | `get_meshdiag_topology` | `network_dataset_info` | `dataset_info` | Rename | Same rationale as above |
| `otbr_cli_meshdiag_topology.py` | `main` | `argv` | `argv` | Keep | Standard |
| `otbr_restapi_download.py` | `build_base_url` | `host` | `host` | Keep | Standard |
| `otbr_restapi_download.py` | `build_base_url` | `port` | `port` | Keep | Standard |
| `otbr_restapi_download.py` | `build_base_url` | `base_url` | `base_url` | Keep | Clear |
| `otbr_restapi_download.py` | `build_headers` | `accept` | `accept` | Keep | Standard HTTP term |
| `otbr_restapi_download.py` | `build_headers` | `extra_headers` | `extra_headers` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `download_json` | `url` | `url` | Keep | Simple |
| `otbr_restapi_download.py` | `download_json` | `headers` | `headers` | Keep | Standard HTTP term |
| `otbr_restapi_download.py` | `download_json` | `output_file` | `out_file` | Rename | `output_file` is slightly verbose; `out_file` is compact and consistent with common Python idiom |
| `otbr_restapi_download.py` | `download_json` | `timeout` | `timeout` | Keep | Standard |
| `otbr_restapi_download.py` | `download_json` | `retries` | `retries` | Keep | Clear |
| `otbr_restapi_download.py` | `download_all_restapi_endpoints` | `base_url` | `base_url` | Keep | Clear |
| `otbr_restapi_download.py` | `download_all_restapi_endpoints` | `headers` | `headers` | Keep | Standard |
| `otbr_restapi_download.py` | `download_all_restapi_endpoints` | `timeout` | `timeout` | Keep | Standard |
| `otbr_restapi_download.py` | `main` | `argv` | `argv` | Keep | Standard |
| `otbr_restapi_raw_client_cli.py` | `build_client` | `args` | `args` | Keep | Standard `argparse` convention |
| `otbr_restapi_raw_client_cli.py` | `dispatch` | `args` | `args` | Keep | Standard `argparse` convention |
| `otbr_restapi_raw_client_cli.py` | `main` | `argv` | `argv` | Keep | Standard |
| `otbr_cli_router_table.py` | `parse_router_table` | `output` | `output` | Keep | Simple |
| `otbr_cli_router_table.py` | `parse_router_table` | `extaddr_map` | `extaddr_map` | Keep | Consistent |
| `otbr_cli_router_table.py` | `fetch_and_parse_router_table` | `extaddr_map` | `extaddr_map` | Keep | Consistent |
| `otbr_cli_router_table.py` | `main` | `argv` | `argv` | Keep | Standard |
| `extaddr_device_label_map.py` | `load_extaddr_device_label_map` | `path` | `path` | Keep | Simple |

---

## Summary of Proposed Renames

| # | File | Function | `current` → `new` | Reason |
|---|---|---|---|---|
| 1 | `util_network.py` | `fetch_dataset_active` | `hideSensitiveInfo` → `hide_sensitive` | **Not snake_case** — only violation of Python naming convention |
| 2 | `util_convert.py` | `extaddr_hex_to_base64` | `hex_number` → `hex_addr` | Misleading — value is a hex string, not a number |
| 3 | `util_ot_ctl.py` | `exec_ot_ctl_dispatch` | `ot_command` → `cmd` | Verbose — function name already establishes ot-ctl context |
| 4 | `util_data.py` | `_normalize_path` | `path_value` → `path` | `_value` suffix is noise; type annotation conveys type |
| 5 | `util_data.py` | `resolve_data_dir_with_source` | `datadir_arg` → `data_dir` | `_arg` suffix is noise |
| 6 | `util_data.py` | `resolve_data_dir` | `datadir_arg` → `data_dir` | Same as above |
| 7 | `util_data.py` | `resolve_data_file_path` | `path_or_name` → `file_path` | Ambiguous; `file_path` is direct |
| 8 | `td_cli.py` | `dispatch` | `sub_argv` → `extra_args` | Clearer — these are unrecognised/forwarded args |
| 9 | `util_convert.py` | `b64_to_extended_address` | `b64_str` → `b64` | `_str` suffix is redundant |
| 10 | `util_convert.py` | `extended_address_to_b64` | `hex_str` → `hex_addr` | Too generic; `hex_addr` indicates it is an address |
| 11 | `otbr_restapi_client.py` | `set_node_state` | `value` → `state` | `value` is too generic; `state` is domain-accurate |
| 12 | `util_network.py` | `_parse_prefix_token` | `command_output` → `output` | Verbose; `output` is compact and clear |
| 13 | `util_network.py` | `_fetch_prefix_via_ot_ctl` | `debug_label` → `label` | `debug_` prefix is noise |
| 14 | `util_network.py` | `build_rloc_ipv6_address_prefix` | `meshlocal_prefix` → `ml_prefix` | `ml` is a standard Thread abbreviation; shorter |
| 15 | `util_network.py` | `build_rloc16_ipv6_address` | `ipv6_rloc_prefix` → `rloc_prefix` | `ipv6_` qualifier is obvious from context |
| 16 | `util_network.py` | `is_ipv6_address_in_omr_prefix` | `ipv6_address` → `addr` | Redundant given function name; `addr` is compact |
| 17 | `util_network.py` | `is_ipv6_address_in_omr_prefix` | `omr_ipv6_prefix` → `omr_prefix` | `_ipv6_` redundant; shorter and consistent |
| 18 | `util_network.py` | `find_omr_address_in_list` | `omr_ipv6_prefix` → `omr_prefix` | Same as above |
| 19 | `otbr_cli_networkdiag_topology.py` | `fetch_network_diag_for_device` | `rloc` → `rloc16` | Inconsistent with rest of codebase |
| 20 | `otbr_cli_networkdiag_topology.py` | `fetch_network_diag_for_device` | `ipv6_rloc_prefix` → `rloc_prefix` | Consistent with `util_network` rename |
| 21 | `otbr_cli_networkdiag_topology.py` | `fetch_network_diag_topology` | `network_dataset_info` → `dataset_info` | `network_` prefix redundant |
| 22 | `dataset_merge.py` | `append_merge_conflict` | `current_value` → `cur_val` | Compact; pair with `new_val` |
| 23 | `dataset_merge.py` | `append_merge_conflict` | `incoming_value` → `new_val` | Compact; clearly indicates newly arriving value |
| 24 | `dataset_merge.py` | `merge_lists` | `a_list` → `left` | Non-descriptive; `left`/`right` is consistent with `values_equivalent` |
| 25 | `dataset_merge.py` | `merge_lists` | `b_list` → `right` | Same rationale |
| 26 | `dataset_merge.py` | `build_merged_records` | `extaddr_to_device_label` → `label_map` | Verbose; `label_map` is compact and clear |
| 27 | `eve_parse.py` | `load_and_parse_eve_file` | `network_dataset_info` → `dataset_info` | Consistent with other `network_dataset_info` renames |
| 28 | `eve_parse.py` | `enhance_eve_routes` | `eve_network_enhanced_data` → `eve_data` | Overly verbose; function name provides full context |
| 29 | `mdns_thread_scopes.py` | `get_vendor_from_oui` | `oui_hex` → `oui` | OUI is always hex by definition; `_hex` suffix is redundant |
| 30 | `mdns_thread_scopes.py` | `decode_state_bitmap_br` | `sb_hex` → `sb_val` | Inconsistent with other `decode_*` functions that use `*_value` |
| 31 | `otbr_cli_meshdiag_topology.py` | `enhance_topology_router_links` | `network_dataset_info` → `dataset_info` | Consistent with other `network_dataset_info` renames |
| 32 | `otbr_cli_meshdiag_topology.py` | `get_meshdiag_topology` | `network_dataset_info` → `dataset_info` | Consistent |
| 33 | `otbr_restapi_download.py` | `download_json` | `output_file` → `out_file` | Compact; commonly used shortening |

---

*Total: **33 proposed renames** across 14 files, **all other arguments: Keep***
