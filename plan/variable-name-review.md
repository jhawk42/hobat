# Variable Name Review Plan

## Objective

Review all function-local variable names across `src/*.py` files and propose names that are:
- Snake case
- Compact
- Simple and easy to understand

For each variable, the proposed action is **Keep** or **Rename**, with a comment explaining any rename.

---

## Phase 1 — Inventory

Walk every function in every `src/*.py` file.  
Collect all function-local variable names (excluding parameters and class-level attributes).

## Phase 2 — Evaluate

For each variable assess:
- Is it already snake_case?
- Is it compact (not excessively long)?
- Is it clear to a reader unfamiliar with the code?
- Does it violate PEP 8 (e.g., camelCase, UPPER_CASE used for a mutable local)?

## Phase 3 — Propose

Assign an action:
- **Keep** — name is already good
- **Rename** — name can be improved; provide the new name and a reason

## Phase 4 — Review

Present the table below to the team for review and approval before any code changes are made.

## Phase 5 — Execute (after approval only)

Apply approved renames in a dedicated PR, one file per commit for easy review.

---

## Variable Name Review Table

| .py file name | function name | current local variable name | new local variable name | action | comment |
|---|---|---|---|---|---|
| `const.py` | — | — | — | — | No functions with local variables |
| `extaddr_device_label_map.py` | `load_extaddr_device_label_map` | `mapping` | `mapping` | Keep | Clear, snake_case |
| `extaddr_device_label_map.py` | `load_extaddr_device_label_map` | `data` | `data` | Keep | Clear, snake_case |
| `extaddr_device_label_map.py` | `load_extaddr_device_label_map` | `item` | `item` | Keep | Clear, snake_case |
| `extaddr_device_label_map.py` | `load_extaddr_device_label_map` | `extaddr` | `extaddr` | Keep | Clear, snake_case, domain term |
| `extaddr_device_label_map.py` | `load_extaddr_device_label_map` | `device_label` | `device_label` | Keep | Clear, snake_case |
| `util_convert.py` | `b64_to_extended_address` | `clean_b64` | `clean_b64` | Keep | Clear, snake_case |
| `util_convert.py` | `b64_to_extended_address` | `raw_bytes` | `raw_bytes` | Keep | Clear, snake_case |
| `util_convert.py` | `extended_address_to_b64` | `raw_bytes` | `raw_bytes` | Keep | Clear, snake_case |
| `util_convert.py` | `extended_address_to_b64` | `b64_str` | `b64_str` | Keep | Clear (local reassignment is a shadow of param but name is accurate) |
| `util_convert.py` | `extended_address_to_b64` | `escaped_b64_str` | `escaped` | Rename | Suffix `_b64_str` is redundant; type is obvious from context |
| `util_data.py` | `_normalize_path` | `path` | `path` | Keep | Clear, snake_case |
| `util_data.py` | `_normalize_optional_path` | `as_text` | `as_text` | Keep | Clear, snake_case |
| `util_data.py` | `parse_datadir_from_argv` | `args` | `args` | Keep | Clear, conventional |
| `util_data.py` | `parse_datadir_from_argv` | `index` | `index` | Keep | Clearer than `i` in this context |
| `util_data.py` | `parse_datadir_from_argv` | `token` | `token` | Keep | Clear, snake_case |
| `util_data.py` | `parse_datadir_from_argv` | `value` | `value` | Keep | Clear, snake_case |
| `util_data.py` | `resolve_data_dir_with_source` | `env_map` | `env_map` | Keep | Clear, snake_case |
| `util_data.py` | `resolve_data_dir_with_source` | `base_cwd` | `base_cwd` | Keep | Clear, snake_case |
| `util_data.py` | `resolve_data_dir_with_source` | `env_value` | `env_value` | Keep | Clear, snake_case |
| `util_data.py` | `resolve_data_dir_with_source` | `datadir_value` | `datadir_value` | Keep | Clear, snake_case |
| `util_data.py` | `resolve_data_dir_with_source` | `docker_default` | `docker_default` | Keep | Clear, snake_case |
| `util_data.py` | `resolve_data_dir_with_source` | `local_default` | `local_default` | Keep | Clear, snake_case |
| `util_data.py` | `resolve_data_dir_with_source` | `created` | `created` | Keep | Clear, snake_case |
| `util_data.py` | `ensure_data_dir_exists` | `resolved` | `resolved` | Keep | Clear, snake_case |
| `util_data.py` | `format_data_dir_log_message` | `suffix` | `suffix` | Keep | Clear, snake_case |
| `util_data.py` | `data_file_path` | `file_path` | `file_path` | Keep | Clear, snake_case |
| `util_data.py` | `resolve_data_file_path` | `normalized` | `normalized` | Keep | Clear, snake_case |
| `util_data.py` | `resolve_data_file_path` | `value` | `value` | Keep | Clear, snake_case |
| `util_network.py` | `_parse_prefix_token` | `command_output` | `command_output` | Keep | Clear (shadows param after strip, acceptable) |
| `util_network.py` | `_fetch_prefix_via_ot_ctl` | `command_output` | `command_output` | Keep | Clear, snake_case |
| `util_network.py` | `_fetch_prefix_via_ot_ctl` | `prefix` | `prefix` | Keep | Clear, snake_case |
| `util_network.py` | `_build_ipv6_prefix_by_type` | `base_prefix` | `base_prefix` | Keep | Clear, snake_case |
| `util_network.py` | `fetch_dataset_active` | `command` | `command` | Keep | Clear, snake_case |
| `util_network.py` | `fetch_dataset_active` | `dataset_output` | `raw_output` | Rename | `dataset_output` is redundant with the function name; `raw_output` conveys it is the unprocessed string |
| `util_network.py` | `fetch_dataset_active` | `dataset_info` | `dataset_info` | Keep | Clear, snake_case |
| `util_network.py` | `fetch_dataset_active` | `key` | `key` | Keep | Clear, standard loop name |
| `util_network.py` | `fetch_dataset_active` | `value` | `value` | Keep | Clear, standard loop name |
| `util_network.py` | `fetch_network_dataset_info` | `network_dataset_info` | `network_dataset_info` | Keep | Clear, snake_case |
| `util_network.py` | `fetch_network_dataset_info` | `prefix_meshlocal` | `prefix_meshlocal` | Keep | Clear, snake_case |
| `util_network.py` | `fetch_network_dataset_info` | `prefix_meshlocal_ipv6addr_prefix` | `prefix_meshlocal_ipv6addr_prefix` | Keep | Long but precise; domain-specific |
| `util_network.py` | `fetch_network_dataset_info` | `prefix_omr` | `prefix_omr` | Keep | Clear, snake_case |
| `util_network.py` | `fetch_network_dataset_info` | `dataset_active` | `dataset_active` | Keep | Clear, snake_case |
| `util_network.py` | `find_omr_address_in_list` | `addr` | `addr` | Keep | Clear, compact loop name |
| `util_ot_ctl.py` | `exec_ot_ctl_dispatch` | `full_command_docker_container` | `docker_cmd` | Rename | Original name is very long; `docker_cmd` is compact and equally clear |
| `util_ot_ctl.py` | `exec_ot_ctl_dispatch` | `full_command_no_docker` | `local_cmd` | Rename | `local_cmd` is compact and expresses "run without docker" clearly |
| `util_ot_ctl.py` | `exec_ot_ctl_dispatch` | `full_command` | `cmd` | Rename | `full_command` is verbose; `cmd` is the standard compact name for a subprocess command list |
| `util_ot_ctl.py` | `exec_ot_ctl_dispatch` | `_timeout` | `timeout_sec` | Rename | Leading underscore is unconventional for a plain local; `timeout_sec` states the unit |
| `util_ot_ctl.py` | `exec_ot_ctl_dispatch` | `result` | `result` | Keep | Clear, standard subprocess result name |
| `util_ot_ctl.py` | `exec_ot_ctl_dispatch` | `err_str` | `err_str` | Keep | Clear, snake_case |
| `util_ot_ctl.py` | `exec_ot_ctl` | `container_name_env` | `env_container_name` | Rename | Reordering to `env_*` prefix makes it obvious the value comes from an environment variable |
| `util_ot_ctl.py` | `exec_ot_ctl` | `container_use_env` | `env_container_use` | Rename | Same reason as `env_container_name` |
| `util_ot_ctl.py` | `exec_ot_ctl` | `container_use` | `container_use` | Keep | Clear, snake_case |
| `util_ot_ctl.py` | `exec_ot_ctl` | `output` | `output` | Keep | Clear, standard name |
| `web_server.py` | `_is_json_request` | `parsed` | `url_parts` | Rename | `parsed` is too generic; `url_parts` clarifies it is the result of `urlparse` |
| `web_server.py` | `_resolve_json_file_path` | `parsed` | `url_parts` | Rename | Same as above |
| `web_server.py` | `_resolve_json_file_path` | `request_rel` | `rel_path` | Rename | `request_rel` is a mix of a noun and an adjective; `rel_path` is concise and clear |
| `web_server.py` | `_resolve_json_file_path` | `target` | `target` | Keep | Clear, snake_case |
| `web_server.py` | `_serve_json_from_data_dir` | `target` | `target` | Keep | Clear, snake_case |
| `web_server.py` | `_serve_json_from_data_dir` | `payload` | `payload` | Keep | Clear, snake_case |
| `web_server.py` | `build_parser` | `parser` | `parser` | Keep | Clear, conventional |
| `web_server.py` | `main` | `parser` | `parser` | Keep | Clear, conventional |
| `web_server.py` | `main` | `args` | `args` | Keep | Clear, conventional |
| `web_server.py` | `main` | `static_root` | `static_root` | Keep | Clear, snake_case |
| `web_server.py` | `main` | `td_data_dir_resolution` | `dir_res` | Rename | Very long; `dir_res` is compact and still clear given `resolve_data_dir_with_source` is the call |
| `web_server.py` | `main` | `td_data_dir` | `td_data_dir` | Keep | Clear, consistent with rest of codebase |
| `web_server.py` | `main` | `Handler` | `handler` | Rename | Local variables must be snake_case per PEP 8; `Handler` looks like a class |
| `web_server.py` | `main` | `httpd` | `httpd` | Keep | Conventional name for an HTTP server instance |
| `otbr_cli_network_dataset_info.py` | `main` | `td_data_dir` | `td_data_dir` | Keep | Clear, snake_case |
| `otbr_cli_network_dataset_info.py` | `main` | `network_dataset_info` | `network_dataset_info` | Keep | Clear, snake_case |
| `otbr_cli_network_dataset_info.py` | `main` | `save_json_path` | `save_json_path` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `fetch_meshdiag_child_ip6_for_device` | `output` | `output` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `fetch_meshdiag_child_ip6_for_device` | `timeout_match` | `timeout_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `fetch_meshdiag_child_ip6_for_device` | `router_child_ip6` | `router_child_ip6` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `fetch_meshdiag_child_ip6_for_device` | `router_child_ip6_data` | `router_child_ip6_data` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `fetch_meshdiag_child_ip6_for_device` | `current_child` | `current_child` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `fetch_meshdiag_child_ip6_for_device` | `stripped` | `stripped` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `fetch_meshdiag_child_ip6_for_device` | `child_rloc16_match` | `rloc16_match` | Rename | `child_` prefix is redundant in the context of parsing child lines; `rloc16_match` is compact |
| `otbr_cli_meshdiag_childip6.py` | `fetch_all_meshdiag_child_ip6_tables` | `router_table_data` | `router_table_data` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `fetch_all_meshdiag_child_ip6_tables` | `router_rlocs` | `router_rlocs` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `fetch_all_meshdiag_child_ip6_tables` | `router_child_ip6_tables` | `router_child_ip6_tables` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `fetch_all_meshdiag_child_ip6_tables` | `router` | `router` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `fetch_all_meshdiag_child_ip6_tables` | `extaddr` | `extaddr` | Keep | Clear, domain term |
| `otbr_cli_meshdiag_childip6.py` | `fetch_all_meshdiag_child_ip6_tables` | `device_label` | `device_label` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `fetch_all_meshdiag_child_ip6_tables` | `router_child_ip6` | `router_child_ip6` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `main` | `td_data_dir` | `td_data_dir` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `main` | `extaddr_json_filename` | `extaddr_json_filename` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `main` | `extaddr_map` | `extaddr_map` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `main` | `router_child_ip6_tables` | `router_child_ip6_tables` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childip6.py` | `main` | `output_filename` | `output_filename` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `output` | `output` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `timeout_match` | `timeout_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `router_child_table` | `router_child_table` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `router_child_table_data` | `router_child_table_data` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `current_child` | `current_child` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `stripped` | `stripped` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `match` | `match` | Keep | Clear, conventional regex match name |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `child_extaddr` | `child_extaddr` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `timeout_age_match` | `timeout_age_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `rx_type_match` | `rx_type_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `rss_match` | `rss_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `err_rate_match` | `err_rate_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `conn_time_match` | `conn_time_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `csl_match` | `csl_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_all_meshdiag_child_tables` | `router_table_data` | `router_table_data` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_all_meshdiag_child_tables` | `router_rlocs` | `router_rlocs` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_all_meshdiag_child_tables` | `router_child_tables` | `router_child_tables` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_all_meshdiag_child_tables` | `router` | `router` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_all_meshdiag_child_tables` | `extaddr` | `extaddr` | Keep | Clear, domain term |
| `otbr_cli_meshdiag_childtable.py` | `fetch_all_meshdiag_child_tables` | `device_label` | `device_label` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `fetch_all_meshdiag_child_tables` | `router_child_table` | `router_child_table` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `main` | `td_data_dir` | `td_data_dir` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `main` | `extaddr_json_filename` | `extaddr_json_filename` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `main` | `extaddr_map` | `extaddr_map` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `main` | `router_child_tables` | `router_child_tables` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_childtable.py` | `main` | `output_filename` | `output_filename` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_meshdiag_router_neighbor_table_for_device` | `output` | `output` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_meshdiag_router_neighbor_table_for_device` | `timeout_match` | `timeout_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_meshdiag_router_neighbor_table_for_device` | `router_neighbor_table` | `router_neighbor_table` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_meshdiag_router_neighbor_table_for_device` | `router_neighbor_table_data` | `router_neighbor_table_data` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_meshdiag_router_neighbor_table_for_device` | `current_neighbor` | `current_neighbor` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_meshdiag_router_neighbor_table_for_device` | `stripped` | `stripped` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_meshdiag_router_neighbor_table_for_device` | `match` | `match` | Keep | Clear, conventional regex match name |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_meshdiag_router_neighbor_table_for_device` | `rss_match` | `rss_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_meshdiag_router_neighbor_table_for_device` | `err_rate_match` | `err_rate_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_meshdiag_router_neighbor_table_for_device` | `conn_time_match` | `conn_time_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_all_meshdiag_router_neighbor_tables` | `router_table_data` | `router_table_data` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_all_meshdiag_router_neighbor_tables` | `router_rlocs` | `router_rlocs` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_all_meshdiag_router_neighbor_tables` | `router_neighbor_tables` | `router_neighbor_tables` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_all_meshdiag_router_neighbor_tables` | `router` | `router` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_all_meshdiag_router_neighbor_tables` | `extaddr` | `extaddr` | Keep | Clear, domain term |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_all_meshdiag_router_neighbor_tables` | `device_label` | `device_label` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_all_meshdiag_router_neighbor_tables` | `router_neighbor_table` | `router_neighbor_table` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `main` | `td_data_dir` | `td_data_dir` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `main` | `extaddr_json_filename` | `extaddr_json_filename` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `main` | `extaddr_map` | `extaddr_map` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `main` | `router_neighbor_tables` | `router_neighbor_tables` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_routerneighbortable.py` | `main` | `output_path` | `output_path` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `fetch_meshdiag_topology` | `output` | `output` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `routers` | `routers` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `router_blocks` | `router_blocks` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `block` | `block` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `lines` | `lines` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `first_line` | `first_line` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `match` | `match` | Keep | Clear, conventional regex match name |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `router` | `router` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `extaddr_lower` | `extaddr_lower` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `current_section` | `current_section` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `current_lq` | _(remove)_ | Rename | Variable is assigned but never read; dead code — should be removed |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `stripped` | `stripped` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `link_match` | `link_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `links` | `links` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `child` | `child` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `rloc_match` | `rloc_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `lq_match` | `lq_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `mode_match` | `mode_match` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `enhance_topology_router_links` | `omr_ipv6addr_prefix` | `omr_ipv6addr_prefix` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `enhance_topology_router_links` | `topology_data_enhanced` | `topology_data_enhanced` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `enhance_topology_router_links` | `router` | `router` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `enhance_topology_router_links` | `enhanced_router` | `enhanced_router` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `enhance_topology_router_links` | `link_type` | `link_type` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `enhance_topology_router_links` | `link_ids` | `link_ids` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `decode_links_to_objects` (nested) | `link_objects` | `link_objects` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `decode_links_to_objects` (nested) | `link_id` | `link_id` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `decode_links_to_objects` (nested) | `linked_router` | `linked_router` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `decode_links_to_objects` (nested) | `device_label` | `device_label` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `decode_links_to_objects` (nested) | `link_rloc16` | `link_rloc16` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `get_meshdiag_topology` | `topology_data_enhanced` | `topology_data_enhanced` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `get_meshdiag_topology` | `output` | `output` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `get_meshdiag_topology` | `topology_data_enhanced_links` | `enhanced_links` | Rename | Double `enhanced` in the name is redundant; `enhanced_links` is compact and sufficient |
| `otbr_cli_meshdiag_topology.py` | `main` | `td_data_dir` | `td_data_dir` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `main` | `extaddr_json_filename` | `extaddr_json_filename` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `main` | `extaddr_map` | `extaddr_map` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `main` | `network_dataset_info` | `network_dataset_info` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `main` | `meshdiag_topology_data` | `meshdiag_topology_data` | Keep | Clear, snake_case |
| `otbr_cli_meshdiag_topology.py` | `main` | `save_path` | `save_path` | Keep | Clear, snake_case |
| `otbr_cli_network_dataset_info.py` | `main` | `f` | `f` | Keep | Conventional file-handle name |
| `otbr_cli_networkdiag_topology.py` | `fetch_ipv6_addresses` | `output` | `output` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `fetch_ipv6_addresses` | `ipv6_map` | `ipv6_map` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `fetch_ipv6_addresses` | `lines` | `lines` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `fetch_ipv6_addresses` | `rloc_match` | `rloc_match` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `fetch_ipv6_addresses` | `ipv6_match` | `ipv6_match` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `fetch_ipv6_addresses` | `rloc` | `rloc` | Keep | Clear, compact domain term |
| `otbr_cli_networkdiag_topology.py` | `fetch_ipv6_addresses` | `ipv6` | `ipv6` | Keep | Clear, compact domain term |
| `otbr_cli_networkdiag_topology.py` | `parse_ipv6_address_list` | `ipv6_list` | `ipv6_list` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_ipv6_address_list` | `lines` | `lines` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_ipv6_address_list` | `in_ipv6_section` | `in_ipv6_section` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_ipv6_address_list` | `ipv6_addr` | `ipv6_addr` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mode_flags` | `mode` | `mode` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mode_flags` | `lines` | `lines` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mode_flags` | `in_mode_section` | `in_mode_section` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mode_flags` | `stripped` | `stripped` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mode_flags` | `val_match` | `val_match` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `children` | `children` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `lines` | `lines` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `in_child_section` | `in_child_section` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `current_child` | `current_child` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `parent_rloc16_int` | `parent_rloc16_int` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `child_id_match` | `cid_match` | Rename | `child_id_match` is verbose; `cid_match` is compact and clear in context |
| `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `child_id` | `cid` | Rename | `child_id` is fine but `cid` is consistently compact; both the intermediate variable and sibling `cid_int` use the same prefix |
| `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `child_id_int` | `cid_int` | Rename | Same reasoning as `cid`; aligns with `cid_match` and `cid` |
| `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `child_rloc16_int` | `rloc16_int` | Rename | `child_` prefix is redundant within this function's child-parsing context |
| `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `child_rloc16` | `rloc16` | Rename | Same as above |
| `otbr_cli_networkdiag_topology.py` | `parse_mac_counters` | `counters` | `counters` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mac_counters` | `lines` | `lines` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mac_counters` | `in_mac_section` | `in_mac_section` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mac_counters` | `parts` | `parts` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mac_counters` | `key` | `key` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mac_counters` | `value` | `value` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mac_counters` | `ifinerrors` | `ifinerrors` | Keep | Domain counter name; matches JSON field |
| `otbr_cli_networkdiag_topology.py` | `parse_mac_counters` | `ifouterrors` | `ifouterrors` | Keep | Domain counter name; matches JSON field |
| `otbr_cli_networkdiag_topology.py` | `parse_mac_counters` | `totalerrors` | `totalerrors` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mac_counters` | `ifindiscards` | `ifindiscards` | Keep | Domain counter name; matches JSON field |
| `otbr_cli_networkdiag_topology.py` | `parse_mac_counters` | `ifoutdiscards` | `ifoutdiscards` | Keep | Domain counter name; matches JSON field |
| `otbr_cli_networkdiag_topology.py` | `parse_mac_counters` | `totaldiscards` | `totaldiscards` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mle_counters` | `counters` | `counters` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mle_counters` | `lines` | `lines` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mle_counters` | `in_mle_section` | `in_mle_section` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mle_counters` | `parts` | `parts` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mle_counters` | `key` | `key` | Keep | Clear, snake_case |
| `otbr_cli_networkdiag_topology.py` | `parse_mle_counters` | `value` | `value` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `parse_router_table` | `routers` | `routers` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `parse_router_table` | `lines` | `lines` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `parse_router_table` | `header_line` | `header_line` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `parse_router_table` | `header_idx` | `header_idx` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `parse_router_table` | `field_names` | `field_names` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `parse_router_table` | `values` | `values` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `parse_router_table` | `router` | `router` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `parse_router_table` | `field_name` | `field_name` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `parse_router_table` | `value` | `value` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `parse_router_table` | `ext_mac` | `ext_mac` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `fetch_and_parse_router_table` | `raw_output` | `raw_output` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `main` | `td_data_dir` | `td_data_dir` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `main` | `extaddr_json_filename` | `extaddr_json_filename` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `main` | `extaddr_map` | `extaddr_map` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `main` | `router_table_data` | `router_table_data` | Keep | Clear, snake_case |
| `otbr_cli_router_table.py` | `main` | `save_path` | `save_path` | Keep | Clear, snake_case |
| `eve_parse.py` | `load_and_parse_eve_file` | `rloc16_missing_start` | `missing_rloc16_start` | Rename | Leading adjective `missing_` reads more naturally and follows adjective-noun order |
| `eve_parse.py` | `load_and_parse_eve_file` | `out` | `result` | Rename | `out` is too terse; `result` is the conventional name for the dict being built |
| `eve_parse.py` | `load_and_parse_eve_file` | `omr_ipv6addr_prefix` | `omr_ipv6addr_prefix` | Keep | Clear, snake_case |
| `eve_parse.py` | `load_and_parse_eve_file` | `j` | `data` | Rename | `j` gives no information; `data` is the conventional name for parsed JSON |
| `eve_parse.py` | `load_and_parse_eve_file` | `node` | `node` | Keep | Clear, snake_case |
| `eve_parse.py` | `load_and_parse_eve_file` | `rloc16_decimal` | `rloc16_decimal` | Keep | Clear, snake_case |
| `eve_parse.py` | `load_and_parse_eve_file` | `ipv6_addrs` | `ipv6_addrs` | Keep | Clear, snake_case |
| `eve_parse.py` | `load_and_parse_eve_file` | `rloc16_hex` | `rloc16_hex` | Keep | Clear, snake_case |
| `eve_parse.py` | `load_and_parse_eve_file` | `threadNetworks` | `thread_networks` | Rename | camelCase violates PEP 8 for local variables; `thread_networks` is the correct snake_case form |
| `eve_parse.py` | `load_and_parse_eve_file` | `extAddress_b64` | `ext_addr_b64` | Rename | Mixed camelCase/underscore violates PEP 8; `ext_addr_b64` is snake_case and compact |
| `eve_parse.py` | `load_and_parse_eve_file` | `extAddress_hex` | `ext_addr_hex` | Rename | Same as `ext_addr_b64` — normalize to snake_case |
| `eve_parse.py` | `enhance_eve_routes` | `id_to_name` | `id_to_name` | Keep | Clear, snake_case |
| `eve_parse.py` | `enhance_eve_routes` | `id_to_rloc16_hex` | `id_to_rloc16_hex` | Keep | Clear, snake_case |
| `eve_parse.py` | `enhance_eve_routes` | `key_to_name` | `key_to_name` | Keep | Clear, snake_case |
| `eve_parse.py` | `enhance_eve_routes` | `original_key` | `original_key` | Keep | Clear, snake_case |
| `eve_parse.py` | `enhance_eve_routes` | `original_node` | `original_node` | Keep | Clear, snake_case |
| `eve_parse.py` | `enhance_eve_routes` | `node_name` | `node_name` | Keep | Clear, snake_case |
| `eve_parse.py` | `enhance_eve_routes` | `node_id` | `node_id` | Keep | Clear, snake_case |
| `eve_parse.py` | `enhance_eve_routes` | `output` | `result` | Rename | `output` suggests a string/bytes result; `result` is clearer for a dict |
| `eve_parse.py` | `enhance_eve_routes` | `node_copy` | `node_copy` | Keep | Clear, snake_case |
| `eve_parse.py` | `enhance_eve_routes` | `rloc16_hex` | `rloc16_hex` | Keep | Clear, snake_case |
| `eve_parse.py` | `enhance_eve_routes` | `routes` | `routes` | Keep | Clear, snake_case |
| `eve_parse.py` | `enhance_eve_routes` | `route` | `route` | Keep | Clear, snake_case |
| `eve_parse.py` | `enhance_eve_routes` | `destination` | `destination` | Keep | Clear, snake_case |
| `eve_parse.py` | `main` | `td_data_dir` | `td_data_dir` | Keep | Clear, snake_case |
| `eve_parse.py` | `main` | `network_dataset_info` | `network_dataset_info` | Keep | Clear, snake_case |
| `eve_parse.py` | `main` | `eve_json_file_path` | `eve_json_file_path` | Keep | Clear, snake_case |
| `eve_parse.py` | `main` | `eve_data_parse_1` | `eve_data_raw` | Rename | `_1` suffix is cryptic; `raw` clearly signals this is the first-pass / unenhanced data |
| `eve_parse.py` | `main` | `eve_data_enhanced` | `eve_data_enhanced` | Keep | Clear, snake_case |
| `eve_parse.py` | `main` | `save_json_filename` | `out_path` | Rename | `save_json_filename` is verbose; `out_path` is compact and consistent with other files |
| `mdns_thread_scopes.py` | `decode_state_bitmap_br` | `sb_int` | `sb_int` | Keep | Clear, snake_case, domain abbreviation |
| `mdns_thread_scopes.py` | `decode_state_bitmap_br` | `bits` | `bits` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `format_state_bitmap_br` | `status` | `status` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `decode_hap_status_flags` | `sf_int` | `sf_int` | Keep | Clear, snake_case, domain abbreviation |
| `mdns_thread_scopes.py` | `decode_hap_status_flags` | `bits` | `bits` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `format_hap_status_flags` | `status` | `status` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `decode_hap_feature_flags` | `ff_int` | `ff_int` | Keep | Clear, snake_case, domain abbreviation |
| `mdns_thread_scopes.py` | `decode_hap_feature_flags` | `bits` | `bits` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `format_hap_feature_flags` | `features` | `features` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `get_pairing_hint_description` | `ph_int` | `ph_int` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `get_pairing_hint_description` | `hints` | `hints` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `get_pairing_hint_description` | `descriptions` | `descriptions` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `decode_hap_setup_hash` | `sh_b64` | `sh_b64` | Keep | Clear, snake_case, domain abbreviation |
| `mdns_thread_scopes.py` | `decode_hap_setup_hash` | `hash_bytes` | `hash_bytes` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `decode_hap_setup_hash` | `hash_hex` | `hash_hex` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `decode_thread_partition_id` | `pt_hex` | `pt_hex` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `decode_thread_partition_id` | `pt_int` | `pt_int` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `decode_thread_beacon_bitmap` | `bb_hex` | `bb_hex` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `decode_thread_beacon_bitmap` | `bb_int` | `bb_int` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `decode_thread_beacon_bitmap` | `bits` | `bits` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `format_thread_beacon_bitmap` | `status` | `status` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `decode_matter_icd_capability` | `icd_str` | `icd_str` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `decode_matter_icd_capability` | `icd_int` | `icd_int` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `parse_fabric_and_node_ids_from_name` | `instance_name` | `instance_name` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `parse_fabric_and_node_ids_from_name` | `parts` | `parts` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `parse_fabric_and_node_ids_from_name` | `fabric_id_hex` | `fabric_id_hex` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `parse_fabric_and_node_ids_from_name` | `node_id_hex` | `node_id_hex` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `parse_fabric_and_node_ids_from_name` | `fabric_id_decimal` | `fabric_id_decimal` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `parse_fabric_and_node_ids_from_name` | `node_id_decimal` | `node_id_decimal` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `parse_matter_vp` | `vp_str` | `vp_str` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `parse_matter_vp` | `parts` | `parts` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `parse_matter_vp` | `vendor_id` | `vendor_id` | Keep | Clear, snake_case |
| `mdns_thread_scopes.py` | `parse_matter_vp` | `product_id` | `product_id` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `build_headers` | `headers` | `headers` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `build_headers` | `raw_header` | `raw_header` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `build_headers` | `name` | `name` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `build_headers` | `separator` | `separator` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `build_headers` | `value` | `value` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `build_headers` | `normalized_name` | `normalized_name` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `build_headers` | `normalized_value` | `normalized_value` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `download_json` | `request` | `request` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `download_json` | `last_exc` | `last_exc` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `download_json` | `charset` | `charset` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `download_json` | `payload` | `payload` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `download_json` | `data` | `data` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `download_json` | `tmp_file` | `tmp_file` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `download_all_restapi_endpoints` | `failures` | `failures` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `download_all_restapi_endpoints` | `request_headers` | `request_headers` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `download_all_restapi_endpoints` | `endpoint` | `endpoint` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `download_all_restapi_endpoints` | `output_file` | `output_file` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `download_all_restapi_endpoints` | `url` | `url` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `download_all_restapi_endpoints` | `resolved_output_file` | `resolved_output_file` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `download_all_restapi_endpoints` | `ok` | `ok` | Keep | Clear, compact boolean name |
| `otbr_restapi_download.py` | `main` | `parser` | `parser` | Keep | Clear, conventional |
| `otbr_restapi_download.py` | `main` | `args` | `args` | Keep | Clear, conventional |
| `otbr_restapi_download.py` | `main` | `previous_td_data_dir` | `previous_td_data_dir` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `main` | `base_url` | `base_url` | Keep | Clear, snake_case |
| `otbr_restapi_download.py` | `main` | `headers` | `headers` | Keep | Clear, snake_case |
| `otbr_restapi_client_cli.py` | `dispatch` | `client` | `client` | Keep | Clear, snake_case |
| `otbr_restapi_client_cli.py` | `dispatch` | `fields` | `fields` | Keep | Clear, snake_case |
| `otbr_restapi_client_cli.py` | `dispatch` | `dataset` | `dataset` | Keep | Clear, snake_case |
| `otbr_restapi_client_cli.py` | `_parse_dataset_input` | `td_data_dir` | `td_data_dir` | Keep | Clear, snake_case |
| `otbr_restapi_client_cli.py` | `_resolve` (nested) | `path_value` | `path_value` | Keep | Clear, snake_case |
| `otbr_restapi_client_cli.py` | `_parse_typed_values` | `parsed` | `parsed` | Keep | Clear, snake_case |
| `otbr_restapi_client_cli.py` | `_parse_typed_values` | `value` | `value` | Keep | Clear, snake_case |
| `otbr_restapi_client_cli.py` | `emit_output` | `rendered` | `rendered` | Keep | Clear, snake_case |
| `otbr_restapi_client_cli.py` | `emit_output` | `suffix` | `suffix` | Keep | Clear, snake_case |
| `otbr_restapi_client_cli.py` | `emit_error` | `payload` | `payload` | Keep | Clear, snake_case |
| `otbr_restapi_client_cli.py` | `main` | `parser` | `parser` | Keep | Clear, conventional |
| `otbr_restapi_client_cli.py` | `main` | `args` | `args` | Keep | Clear, conventional |
| `otbr_restapi_client_cli.py` | `main` | `output_path` | `output_path` | Keep | Clear, snake_case |
| `otbr_restapi_client_cli.py` | `main` | `result` | `result` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client_cli.py` | `dispatch` | `client` | `client` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client_cli.py` | `dispatch` | `fields` | `fields` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client_cli.py` | `main` | `parser` | `parser` | Keep | Clear, conventional |
| `otbr_restapi_raw_client_cli.py` | `main` | `args` | `args` | Keep | Clear, conventional |
| `otbr_restapi_raw_client_cli.py` | `main` | `output_path` | `output_path` | Keep | Clear, snake_case |
| `otbr_restapi_raw_client_cli.py` | `main` | `result` | `result` | Keep | Clear, snake_case |
| `td_cli.py` | `_load_extaddr_device_label_map` | `EXTADDR_JSON_FILENAME_DEFAULT` | `default_filename` | Rename | UPPER_CASE is reserved for module-level constants in PEP 8; this is a function-local variable |
| `td_cli.py` | `dispatch` | `_sub` | `sub_parsers` | Rename | Leading underscore implies "private/internal"; `sub_parsers` is clear and properly snake_case |
| `td_cli.py` | `dispatch` | `cli_cmd` | `cli_cmd` | Keep | Clear, compact |
| `td_cli.py` | `dispatch` | `meshdiag_cmd` | `meshdiag_cmd` | Keep | Clear, compact |
| `td_cli.py` | `dispatch` | `forwarded` | `forwarded` | Keep | Clear, snake_case |
| `td_cli.py` | `dispatch` | `expand_children_argv` | `children_argv` | Rename | `expand_` prefix is redundant; the boolean purpose is already encoded in the parent arg name |
| `td_cli.py` | `dispatch` | `mdns_argv` | `mdns_argv` | Keep | Clear, snake_case |
| `td_cli.py` | `dispatch` | `restapi_cmd` | `restapi_cmd` | Keep | Clear, compact |
| `td_cli.py` | `dispatch` | `web_argv` | `web_argv` | Keep | Clear, snake_case |
| `td_cli.py` | `main` | `argv_list` | `argv_list` | Keep | Clear, snake_case |
| `td_cli.py` | `main` | `parser` | `parser` | Keep | Clear, conventional |
| `td_cli.py` | `main` | `args` | `args` | Keep | Clear, conventional |
| `td_cli.py` | `main` | `extras` | `extras` | Keep | Clear, snake_case |
| `dataset_merge.py` | `normalize_identifier_text` | `value` | `value` | Keep | Clear, snake_case |
| `dataset_merge.py` | `first_normalized_identifier` | `key` | `key` | Keep | Clear, snake_case |
| `dataset_merge.py` | `first_normalized_identifier` | `value` | `value` | Keep | Clear, snake_case |
| `dataset_merge.py` | `normalize_record_aliases` | `extaddr` | `extaddr` | Keep | Clear, domain term |
| `dataset_merge.py` | `normalize_record_aliases` | `omr_addr` | `omr_addr` | Keep | Clear, snake_case |
| `dataset_merge.py` | `derive_mode_device` | `mode_device_raw` | `mode_device_raw` | Keep | Clear, snake_case |
| `dataset_merge.py` | `derive_mode_device` | `value` | `value` | Keep | Clear, snake_case |
| `dataset_merge.py` | `derive_mode_device` | `mode` | `mode` | Keep | Clear, snake_case |
| `dataset_merge.py` | `derive_mode_device` | `mode_device` | `mode_device` | Keep | Clear, snake_case |
| `dataset_merge.py` | `derive_mode_device` | `device_type_ftd` | `device_type_ftd` | Keep | Clear, snake_case |
| `dataset_merge.py` | `derive_mode_device` | `device_type` | `device_type` | Keep | Clear, snake_case |
| `dataset_merge.py` | `derive_mode_device` | `role` | `role` | Keep | Clear, snake_case |
| `dataset_merge.py` | `derive_mode_device` | `role_text` | `role_text` | Keep | Clear, snake_case |
| `dataset_merge.py` | `derive_mode_device` | `node_type` | `node_type` | Keep | Clear, snake_case |
| `dataset_merge.py` | `derive_mode_device` | `type_text` | `type_text` | Keep | Clear, snake_case |
| `dataset_merge.py` | `normalize_identifiers` | `rloc16` | `rloc16` | Keep | Clear, domain term |
| `dataset_merge.py` | `normalize_identifiers` | `omr_addr` | `omr_addr` | Keep | Clear, snake_case |
| `dataset_merge.py` | `normalize_identifiers` | `ipv6_values` | `ipv6_values` | Keep | Clear, snake_case |
| `dataset_merge.py` | `normalize_identifiers` | `prefix` | `prefix` | Keep | Clear, snake_case |
| `dataset_merge.py` | `normalize_identifiers` | `ip_value` | `ip_value` | Keep | Clear, snake_case |
| `dataset_merge.py` | `normalize_identifiers` | `mode_device` | `mode_device` | Keep | Clear, snake_case |
| `dataset_merge.py` | `normalize_identifiers` | `mode` | `mode` | Keep | Clear, snake_case |
| `dataset_merge.py` | `load_extaddr_device_label_map` | `data` | `data` | Keep | Clear, snake_case |
| `dataset_merge.py` | `load_extaddr_device_label_map` | `mapping` | `mapping` | Keep | Clear, snake_case |
| `dataset_merge.py` | `load_extaddr_device_label_map` | `item` | `item` | Keep | Clear, snake_case |
| `dataset_merge.py` | `load_extaddr_device_label_map` | `normalized_item` | `normalized_item` | Keep | Clear, snake_case |
| `dataset_merge.py` | `load_extaddr_device_label_map` | `extaddr` | `extaddr` | Keep | Clear, domain term |
| `dataset_merge.py` | `load_extaddr_device_label_map` | `label` | `label` | Keep | Clear, snake_case |
| `dataset_merge.py` | `extract_records` | `records` | `records` | Keep | Clear, snake_case |
| `dataset_merge.py` | `extract_records` | `item` | `item` | Keep | Clear, snake_case |
| `dataset_merge.py` | `extract_records` | `merged_item` | `merged_item` | Keep | Clear, snake_case |
| `dataset_merge.py` | `extract_records` | `attrs` | `attrs` | Keep | Clear, compact |
| `dataset_merge.py` | `extract_records` | `map_key` | `map_key` | Keep | Clear, snake_case |
| `dataset_merge.py` | `extract_records` | `copied` | `copied` | Keep | Clear, snake_case |
| `dataset_merge.py` | `merge_unique_strings` | `merged` | `merged` | Keep | Clear, snake_case |
| `dataset_merge.py` | `merge_unique_strings` | `value` | `value` | Keep | Clear, snake_case |
| `dataset_merge.py` | `merge_unique_strings` | `text` | `text` | Keep | Clear, snake_case |
| `dataset_merge.py` | `append_merge_conflict` | `conflicts` | `conflicts` | Keep | Clear, snake_case |
| `dataset_merge.py` | `append_merge_conflict` | `current_text` | `current_text` | Keep | Clear, snake_case |
| `dataset_merge.py` | `append_merge_conflict` | `incoming_text` | `incoming_text` | Keep | Clear, snake_case |
| `dataset_merge.py` | `append_merge_conflict` | `entry` | `entry` | Keep | Clear, snake_case |
| `dataset_merge.py` | `merge_lists` | `seen` | `seen` | Keep | Clear, snake_case |
| `dataset_merge.py` | `merge_lists` | `merged` | `merged` | Keep | Clear, snake_case |
| `dataset_merge.py` | `merge_lists` | `item` | `item` | Keep | Clear, snake_case |
| `dataset_merge.py` | `merge_lists` | `key` | `key` | Keep | Clear, snake_case |
| `dataset_merge.py` | `deep_merge` | `existing_conflicts` | `existing_conflicts` | Keep | Clear, snake_case |
| `dataset_merge.py` | `deep_merge` | `conflict` | `conflict` | Keep | Clear, snake_case |
| `dataset_merge.py` | `deep_merge` | `existing_sources` | `existing_sources` | Keep | Clear, snake_case |
| `dataset_merge.py` | `deep_merge` | `incoming_sources` | `incoming_sources` | Keep | Clear, snake_case |
| `dataset_merge.py` | `deep_merge` | `current_path` | `current_path` | Keep | Clear, snake_case |
| `dataset_merge.py` | `deep_merge` | `cur` | `cur` | Keep | Compact conventional name for current value |
| `dataset_merge.py` | `nested_get` | `parts` | `parts` | Keep | Clear, snake_case |
| `dataset_merge.py` | `nested_get` | `cur` | `cur` | Keep | Compact conventional name |
| `dataset_merge.py` | `nested_get` | `part` | `part` | Keep | Clear, snake_case |
| `dataset_merge.py` | `collect_merge_identity_values` | `identities` | `identities` | Keep | Clear, snake_case |
| `dataset_merge.py` | `collect_merge_identity_values` | `rloc16` | `rloc16` | Keep | Clear, domain term |
| `dataset_merge.py` | `collect_merge_identity_values` | `extaddr` | `extaddr` | Keep | Clear, domain term |
| `dataset_merge.py` | `collect_merge_identity_values` | `omr` | `omr` | Keep | Clear, compact domain term |
| `dataset_merge.py` | `find_candidate_node_ids` | `candidate_ids` | `candidate_ids` | Keep | Clear, snake_case |
| `dataset_merge.py` | `find_candidate_node_ids` | `rloc16` | `rloc16` | Keep | Clear, domain term |
| `dataset_merge.py` | `find_candidate_node_ids` | `extaddr` | `extaddr` | Keep | Clear, domain term |
| `dataset_merge.py` | `find_candidate_node_ids` | `omr` | `omr` | Keep | Clear, compact domain term |
| `dataset_merge.py` | `index_node_identity_values` | `identity_values` | `identity_values` | Keep | Clear, snake_case |
| `dataset_merge.py` | `index_node_identity_values` | `rloc16` | `rloc16` | Keep | Clear, domain term |
| `dataset_merge.py` | `index_node_identity_values` | `extaddr` | `extaddr` | Keep | Clear, domain term |
| `dataset_merge.py` | `index_node_identity_values` | `omr` | `omr` | Keep | Clear, domain term |
| `dataset_merge.py` | `merge_nodes` | `target` | `target` | Keep | Clear, snake_case |
| `dataset_merge.py` | `merge_nodes` | `source` | `source` | Keep | Clear, snake_case |
| `dataset_merge.py` | `merge_nodes` | `lookup` | `lookup` | Keep | Clear, snake_case |

---

## Summary of Proposed Renames

| # | File | Function | Current | Proposed | Reason |
|---|---|---|---|---|---|
| 1 | `util_convert.py` | `extended_address_to_b64` | `escaped_b64_str` | `escaped` | Suffix is redundant |
| 2 | `util_network.py` | `fetch_dataset_active` | `dataset_output` | `raw_output` | `dataset_output` echoes the function name; `raw` is clearer |
| 3 | `util_ot_ctl.py` | `exec_ot_ctl_dispatch` | `full_command_docker_container` | `docker_cmd` | Very long; `docker_cmd` is compact and clear |
| 4 | `util_ot_ctl.py` | `exec_ot_ctl_dispatch` | `full_command_no_docker` | `local_cmd` | Same reasoning |
| 5 | `util_ot_ctl.py` | `exec_ot_ctl_dispatch` | `full_command` | `cmd` | Standard compact subprocess name |
| 6 | `util_ot_ctl.py` | `exec_ot_ctl_dispatch` | `_timeout` | `timeout_sec` | Underscore prefix is unconventional; unit suffix is helpful |
| 7 | `util_ot_ctl.py` | `exec_ot_ctl` | `container_name_env` | `env_container_name` | `env_` prefix makes source clear |
| 8 | `util_ot_ctl.py` | `exec_ot_ctl` | `container_use_env` | `env_container_use` | Same reasoning |
| 9 | `web_server.py` | `_is_json_request` | `parsed` | `url_parts` | Clarifies result of `urlparse` |
| 10 | `web_server.py` | `_resolve_json_file_path` | `parsed` | `url_parts` | Same |
| 11 | `web_server.py` | `_resolve_json_file_path` | `request_rel` | `rel_path` | More concise |
| 12 | `web_server.py` | `main` | `td_data_dir_resolution` | `dir_res` | Very long; compact alias is sufficient |
| 13 | `web_server.py` | `main` | `Handler` | `handler` | PEP 8: local variables must be snake_case |
| 14 | `otbr_cli_meshdiag_childip6.py` | `fetch_meshdiag_child_ip6_for_device` | `child_rloc16_match` | `rloc16_match` | `child_` prefix is redundant in context |
| 15 | `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `current_lq` | _(remove)_ | Dead code — never read after assignment |
| 16 | `otbr_cli_meshdiag_topology.py` | `get_meshdiag_topology` | `topology_data_enhanced_links` | `enhanced_links` | Double `_enhanced` is redundant |
| 17 | `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `child_id_match` | `cid_match` | Compact; consistent with siblings |
| 18 | `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `child_id` | `cid` | Compact; aligns with `cid_match` |
| 19 | `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `child_id_int` | `cid_int` | Compact; aligns with `cid` |
| 20 | `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `child_rloc16_int` | `rloc16_int` | `child_` prefix redundant in child-parsing context |
| 21 | `otbr_cli_networkdiag_topology.py` | `parse_child_table` | `child_rloc16` | `rloc16` | Same reasoning |
| 22 | `eve_parse.py` | `load_and_parse_eve_file` | `rloc16_missing_start` | `missing_rloc16_start` | Adjective-noun order is more natural |
| 23 | `eve_parse.py` | `load_and_parse_eve_file` | `out` | `result` | `out` is too terse |
| 24 | `eve_parse.py` | `load_and_parse_eve_file` | `j` | `data` | `j` is meaningless; `data` is conventional for parsed JSON |
| 25 | `eve_parse.py` | `load_and_parse_eve_file` | `threadNetworks` | `thread_networks` | PEP 8: camelCase is not allowed for local variables |
| 26 | `eve_parse.py` | `load_and_parse_eve_file` | `extAddress_b64` | `ext_addr_b64` | Mixed camelCase/underscore violates PEP 8 |
| 27 | `eve_parse.py` | `load_and_parse_eve_file` | `extAddress_hex` | `ext_addr_hex` | Same |
| 28 | `eve_parse.py` | `enhance_eve_routes` | `output` | `result` | `output` implies string/bytes; `result` is correct for a dict |
| 29 | `eve_parse.py` | `main` | `eve_data_parse_1` | `eve_data_raw` | `_1` suffix is cryptic; `raw` is clear |
| 30 | `eve_parse.py` | `main` | `save_json_filename` | `out_path` | Verbose; `out_path` is compact and consistent with similar files |
| 31 | `td_cli.py` | `_load_extaddr_device_label_map` | `EXTADDR_JSON_FILENAME_DEFAULT` | `default_filename` | UPPER_CASE is for module-level constants, not function locals |
| 32 | `td_cli.py` | `dispatch` | `_sub` | `sub_parsers` | Underscore prefix is misleading; `sub_parsers` is clear |
| 33 | `td_cli.py` | `dispatch` | `expand_children_argv` | `children_argv` | `expand_` prefix is redundant |
