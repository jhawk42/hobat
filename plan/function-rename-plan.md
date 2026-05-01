# Function Rename Plan — `src/*.py`

## Overview

This plan proposes standardised, snake_case, compact and easy-to-understand
names for every public and private function defined across all `src/*.py`
files.  The analysis was performed by reading each file in full.

---

## Phases

### Phase 1 — Analysis (complete)

- Read all 23 `src/*.py` files.
- Catalogue every function/method name.
- Evaluate each name against the criteria: snake_case, compact, simple, easy
  to understand.
- Produce the table below.

### Phase 2 — Review (pending human approval)

- Share this document for review.
- Collect feedback on proposed names.
- Adjust any proposal that reviewers disagree with.

### Phase 3 — Implementation (not started)

- Apply renames to source files.
- Update all call sites across `src/` and `tests/`.
- Run existing tests to confirm nothing is broken.
- Open a follow-up PR with the code changes.

---

## Criteria Applied

| Criterion | Meaning |
|-----------|---------|
| **snake_case** | All lowercase letters and underscores only |
| **Compact** | No redundant words; as short as unambiguous allows |
| **Simple** | One clear concept per name |
| **Easy to understand** | Readable without consulting the surrounding code |

---

## Function Name Table

| `.py` file | Current function name | New function name | Action | Comment |
|---|---|---|---|---|
| `const.py` | _(no functions)_ | — | — | Only constants; nothing to rename |
| `extaddr_device_label_map.py` | `load_extaddr_device_label_map` | — | **Keep** | Clear verb + noun, snake_case, self-describing |
| `util_ot_ctl.py` | `exec_ot_ctl_dispatch` | `_run_ot_ctl_cmd` | **Rename** | `exec` + `dispatch` is redundant; `_run` is the conventional verb for subprocess execution; `_cmd` suffix clarifies it runs a raw command |
| `util_ot_ctl.py` | `exec_ot_ctl` | `run_ot_ctl` | **Rename** | `exec` is a Python builtin shadow; `run` is the idiomatic subprocess verb (mirrors `subprocess.run`) |
| `util_convert.py` | `b64_to_extended_address` | `b64_to_extaddr` | **Rename** | `extended_address` is long; `extaddr` is the well-established abbreviation used everywhere else in the codebase |
| `util_convert.py` | `extended_address_to_b64` | `extaddr_to_b64` | **Rename** | Same reason as above: aligns with `extaddr` abbreviation used project-wide |
| `util_convert.py` | `extaddr_hex_to_base64` | `extaddr_to_b64_compat` | **Rename** | This is a backward-compatible alias; the suffix `_compat` signals it exists for compatibility only, steering new callers toward `extaddr_to_b64` |
| `util_data.py` | `_normalize_path` | — | **Keep** | Clear, concise private helper |
| `util_data.py` | `_normalize_optional_path` | `_to_optional_path` | **Rename** | Shorter; the verb `_to_` is sufficient to express a conversion; callers already know the function normalises |
| `util_data.py` | `parse_datadir_from_argv` | — | **Keep** | Explicit verb+noun+source; reads naturally |
| `util_data.py` | `resolve_data_dir_with_source` | — | **Keep** | The `_with_source` suffix meaningfully distinguishes it from `resolve_data_dir` |
| `util_data.py` | `resolve_data_dir` | — | **Keep** | Short and clear |
| `util_data.py` | `ensure_data_dir_exists` | — | **Keep** | Idiomatic "ensure" pattern; self-documenting |
| `util_data.py` | `format_data_dir_log_message` | `fmt_data_dir_log` | **Rename** | `format_` prefix is verbose; `fmt_` is the common abbreviation; `_message` is implied by `_log` |
| `util_data.py` | `data_file_path` | — | **Keep** | Compact and unambiguous |
| `util_data.py` | `resolve_data_file_path` | — | **Keep** | Clear distinction from `data_file_path` |
| `util_network.py` | `_parse_prefix_token` | `_extract_prefix` | **Rename** | `_parse_token` is generic; `_extract_prefix` is specific and shorter |
| `util_network.py` | `_strip_prefix_mask` | — | **Keep** | Short and precise |
| `util_network.py` | `_fetch_prefix_via_ot_ctl` | `_get_prefix` | **Rename** | `_via_ot_ctl` is noise inside a module already dedicated to ot-ctl calls |
| `util_network.py` | `_build_ipv6_prefix_by_type` | `_fmt_ipv6_prefix` | **Rename** | `_build_*_by_type` is lengthy; `_fmt_` conveys "formats a prefix for a given type" more compactly |
| `util_network.py` | `fetch_meshlocal_prefix` | — | **Keep** | Descriptive and already concise |
| `util_network.py` | `build_rloc_ipv6_address_prefix` | `meshlocal_to_rloc_prefix` | **Rename** | Current name starts with `build_` but the input is the meshlocal prefix; the new name makes the input→output transformation explicit |
| `util_network.py` | `strip_rloc16_hex_prefix` | `strip_0x` | **Rename** | The function only strips the `0x` prefix; the specific name is both shorter and more accurate |
| `util_network.py` | `build_rloc16_ipv6_address` | `make_rloc16_addr` | **Rename** | `build_` is interchangeable with `make_`; `rloc16_ipv6_address` → `rloc16_addr` is shorter without loss of meaning |
| `util_network.py` | `fetch_omr_prefix` | — | **Keep** | Mirrors `fetch_meshlocal_prefix` for consistency |
| `util_network.py` | `build_omr_ipv6_address_prefix` | `omr_to_ipv6_prefix` | **Rename** | Input is OMR prefix, output is IPv6 prefix; `_to_` pattern makes the transformation obvious |
| `util_network.py` | `is_ipv6_address_in_omr_prefix` | `addr_in_omr_prefix` | **Rename** | Drops the verbose `is_ipv6_address_` prefix; `addr_in_omr_prefix` reads naturally as a boolean predicate |
| `util_network.py` | `find_omr_address_in_list` | `find_omr_addr` | **Rename** | `_in_list` is redundant—the function signature already shows a list parameter |
| `util_network.py` | `fetch_dataset_active` | `get_active_dataset` | **Rename** | `fetch_` vs `get_` is inconsistent in the module; `get_` is the REST-convention used in sibling files; also parameter `hideSensitiveInfo` (camelCase) should be renamed `hide_sensitive` |
| `util_network.py` | `fetch_network_dataset_info` | — | **Keep** | Self-explanatory |
| `otbr_cli_router_table.py` | `fetch_router_table` | — | **Keep** | Clear fetch verb + resource |
| `otbr_cli_router_table.py` | `parse_router_table` | — | **Keep** | Pairs naturally with `fetch_router_table` |
| `otbr_cli_router_table.py` | `fetch_and_parse_router_table` | `get_router_table` | **Rename** | `fetch_and_parse_` is verbose; `get_` implies the full pipeline (fetch + parse) and is half as long |
| `otbr_cli_router_table.py` | `main` | — | **Keep** | Standard entry-point convention |
| `otbr_cli_meshdiag_childip6.py` | `fetch_meshdiag_child_ip6_for_device` | `get_child_ip6_for_router` | **Rename** | `fetch_meshdiag_` prefix is repetitive inside a module already named `meshdiag_childip6`; `for_device` → `for_router` matches Thread terminology |
| `otbr_cli_meshdiag_childip6.py` | `fetch_all_meshdiag_child_ip6_tables` | `get_all_child_ip6_tables` | **Rename** | Same `fetch_meshdiag_` redundancy; `all_` prefix preserved for clarity |
| `otbr_cli_meshdiag_childip6.py` | `main` | — | **Keep** | Standard entry-point |
| `otbr_cli_meshdiag_childtable.py` | `_parse_yes_no_to_bool` | `_yn_bool` | **Rename** | The intent (`yes/no` → `bool`) is expressed in 7 characters; `_to_bool` suffix follows conversion-helper convention |
| `otbr_cli_meshdiag_childtable.py` | `fetch_meshdiag_child_table_for_device` | `get_child_table_for_router` | **Rename** | Same `fetch_meshdiag_` redundancy; aligns with `get_child_ip6_for_router` above |
| `otbr_cli_meshdiag_childtable.py` | `fetch_all_meshdiag_child_tables` | `get_all_child_tables` | **Rename** | Same rationale |
| `otbr_cli_meshdiag_childtable.py` | `main` | — | **Keep** | Standard entry-point |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_meshdiag_router_neighbor_table_for_device` | `get_router_neighbor_table` | **Rename** | Longest function name in the codebase (50 chars); drops `fetch_meshdiag_` prefix and `_for_device` suffix—the parameters already convey target |
| `otbr_cli_meshdiag_routerneighbortable.py` | `fetch_all_meshdiag_router_neighbor_tables` | `get_all_router_neighbor_tables` | **Rename** | Same `fetch_meshdiag_` redundancy |
| `otbr_cli_meshdiag_routerneighbortable.py` | `main` | — | **Keep** | Standard entry-point |
| `otbr_cli_meshdiag_topology.py` | `fetch_meshdiag_topology` | `get_meshdiag_topology_raw` | **Rename** | `fetch_` → `get_` for consistency; `_raw` clarifies this returns the unparsed ot-ctl string (avoiding collision with `get_meshdiag_topology` which returns processed data) |
| `otbr_cli_meshdiag_topology.py` | `parse_meshdiag_topology_output` | `parse_meshdiag_topology` | **Rename** | `_output` suffix is redundant—parse functions always receive output |
| `otbr_cli_meshdiag_topology.py` | `enhance_topology_router_links` | `enrich_topology_links` | **Rename** | `enhance_` and `enrich_` are synonyms; `enrich_` is used in sibling files—use one verb project-wide; `_router_` is implied by context |
| `otbr_cli_meshdiag_topology.py` | `get_meshdiag_topology` | — | **Keep** | Already concise and consistent |
| `otbr_cli_meshdiag_topology.py` | `main` | — | **Keep** | Standard entry-point |
| `otbr_cli_network_dataset_info.py` | `main` | — | **Keep** | Standard entry-point |
| `otbr_cli_networkdiag_topology.py` | `fetch_ipv6_addresses` | — | **Keep** | Clear verb + resource |
| `otbr_cli_networkdiag_topology.py` | `parse_ipv6_address_list` | `parse_ipv6_addrs` | **Rename** | `address_list` → `addrs` is the abbreviation used everywhere else in the codebase |
| `otbr_cli_networkdiag_topology.py` | `device_type_from_mode` | — | **Keep** | Concise transformation name |
| `otbr_cli_networkdiag_topology.py` | `parse_mode_flags` | — | **Keep** | Short and precise |
| `otbr_cli_networkdiag_topology.py` | `parse_child_table` | — | **Keep** | Mirrors router table convention |
| `otbr_cli_networkdiag_topology.py` | `parse_mac_counters` | — | **Keep** | Clear |
| `otbr_cli_networkdiag_topology.py` | `parse_mle_counters` | — | **Keep** | Clear |
| `otbr_cli_networkdiag_topology.py` | `parse_time_statistics` | `parse_time_stats` | **Rename** | `statistics` → `stats` is the conventional abbreviation; saves 7 characters |
| `otbr_cli_networkdiag_topology.py` | `fetch_network_diag_for_device` | `get_device_diag` | **Rename** | `fetch_` → `get_`; `network_diag` is implied by file context; shorter and still unambiguous |
| `otbr_cli_networkdiag_topology.py` | `fetch_network_diag_topology` | `get_diag_topology` | **Rename** | Same `fetch_` → `get_`; `network_` prefix is implied by module context |
| `otbr_cli_networkdiag_topology.py` | `print_network_diag_topology` | `print_diag_topology` | **Rename** | Drops `network_` for symmetry with `get_diag_topology` |
| `otbr_cli_networkdiag_topology.py` | `save_topology_to_json_dict` | `topology_to_json_dict` | **Rename** | `save_` is misleading—function returns a dict, it does not write to disk; `topology_to_json_dict` describes the transformation accurately |
| `otbr_cli_networkdiag_topology.py` | `save_topology_to_json_list` | `topology_to_json_list` | **Rename** | Same reason as above |
| `otbr_cli_networkdiag_topology.py` | `main` | — | **Keep** | Standard entry-point |
| `mdns_thread_scopes.py` | `get_vendor_from_oui` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `decode_state_bitmap_br` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `format_state_bitmap_br` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `decode_hap_status_flags` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `format_hap_status_flags` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `decode_hap_feature_flags` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `format_hap_feature_flags` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `get_hap_category_name` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `get_matter_device_type_name` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `parse_matter_vp` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `decode_matter_commissioning_data` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `format_matter_commissioning_data` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `decode_matter_tcp_support` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `get_pairing_hint_description` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `decode_hap_setup_hash` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `decode_thread_partition_id` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `decode_thread_beacon_bitmap` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `format_thread_beacon_bitmap` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `decode_matter_icd_capability` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `parse_fabric_and_node_ids_from_name` | `parse_fabric_node_ids` | **Rename** | `_from_name` is redundant (parameter already named `service_name`); resulting name is half the length |
| `mdns_thread_scopes.py` | `_base_field_dict` | `_field_base` | **Rename** | Noun-first matches Python convention for helper builders; `field_base` reads as "the base for a field dict" |
| `mdns_thread_scopes.py` | `_enrich_field_sb` | — | **Keep** | Part of a systematic `_enrich_field_<key>` family; consistent pattern |
| `mdns_thread_scopes.py` | `_enrich_field_bb` | — | **Keep** | Same family |
| `mdns_thread_scopes.py` | `_enrich_field_at` | — | **Keep** | Same family |
| `mdns_thread_scopes.py` | `_enrich_field_xa` | — | **Keep** | Same family |
| `mdns_thread_scopes.py` | `_enrich_field_pt` | — | **Keep** | Same family |
| `mdns_thread_scopes.py` | `_enrich_field_sf` | — | **Keep** | Same family |
| `mdns_thread_scopes.py` | `_enrich_field_ff` | — | **Keep** | Same family |
| `mdns_thread_scopes.py` | `_enrich_field_sh` | — | **Keep** | Same family |
| `mdns_thread_scopes.py` | `_enrich_field_ci` | — | **Keep** | Same family |
| `mdns_thread_scopes.py` | `_enrich_field_VP` | `_enrich_field_vp` | **Rename** | Uppercase letters in function names violate PEP 8 snake_case; lowercase `vp` is consistent with all sibling functions |
| `mdns_thread_scopes.py` | `_enrich_field_DT` | `_enrich_field_dt` | **Rename** | Same PEP 8 violation |
| `mdns_thread_scopes.py` | `_enrich_field_CD` | `_enrich_field_cd` | **Rename** | Same PEP 8 violation |
| `mdns_thread_scopes.py` | `_enrich_field_D` | `_enrich_field_d` | **Rename** | Single uppercase letter; lowercase for consistency |
| `mdns_thread_scopes.py` | `_enrich_field_PH` | `_enrich_field_ph` | **Rename** | Same PEP 8 violation |
| `mdns_thread_scopes.py` | `_enrich_field_interval_ms` | — | **Keep** | Already snake_case and descriptive |
| `mdns_thread_scopes.py` | `_enrich_field_T` | `_enrich_field_t` | **Rename** | Same PEP 8 violation |
| `mdns_thread_scopes.py` | `_enrich_field_ICD` | `_enrich_field_icd` | **Rename** | Same PEP 8 violation |
| `mdns_thread_scopes.py` | `_enrich_properties` | — | **Keep** | Clear private helper |
| `mdns_thread_scopes.py` | `_update_last_event_time` | — | **Keep** | Clear method |
| `mdns_thread_scopes.py` | `_to_json_safe_value` | — | **Keep** | Clear conversion helper |
| `mdns_thread_scopes.py` | `_build_record_from_service_info` | `_build_record` | **Rename** | `_from_service_info` is redundant—the class only processes service info; shorter name preserves full intent |
| `mdns_thread_scopes.py` | `_is_matter_tcp_excluded` | — | **Keep** | Clear boolean predicate |
| `mdns_thread_scopes.py` | `_upsert_record` | — | **Keep** | Standard upsert convention |
| `mdns_thread_scopes.py` | `get_records` | — | **Keep** | Simple accessor |
| `mdns_thread_scopes.py` | `wait_for_idle` | — | **Keep** | Clear |
| `mdns_thread_scopes.py` | `update_service` | — | **Keep** | Zeroconf listener interface—must not change |
| `mdns_thread_scopes.py` | `remove_service` | — | **Keep** | Zeroconf listener interface—must not change |
| `mdns_thread_scopes.py` | `add_service` | — | **Keep** | Zeroconf listener interface—must not change |
| `mdns_thread_scopes.py` | `main` | — | **Keep** | Standard entry-point |
| `otbr_restapi_client.py` | `get_node` | — | **Keep** | REST verb + resource |
| `otbr_restapi_client.py` | `get_node_state` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `set_node_state` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `get_active_dataset` | — | **Keep** | Clear REST pattern |
| `otbr_restapi_client.py` | `set_active_dataset` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `list_devices` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `get_device` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `list_diagnostics` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `get_diagnostic` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `list_actions` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `get_action` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `enqueue_actions` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `enqueue_add_thread_device_task` | — | **Keep** | Mirrors API task name |
| `otbr_restapi_client.py` | `enqueue_get_network_diagnostic_task` | — | **Keep** | Mirrors API task name |
| `otbr_restapi_client.py` | `enqueue_reset_network_diag_counter_task` | — | **Keep** | Mirrors API task name |
| `otbr_restapi_client.py` | `enqueue_get_energy_scan_task` | — | **Keep** | Mirrors API task name |
| `otbr_restapi_client.py` | `enqueue_update_device_collection_task` | — | **Keep** | Mirrors API task name |
| `otbr_restapi_client.py` | `_request` | — | **Keep** | Standard private HTTP method |
| `otbr_restapi_client.py` | `_build_url` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `_build_headers` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `_encode_body` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `_decode_response_body` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `_parse_payload_from_text` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `_normalize_response_payload` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `_flatten_jsonapi_document` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `_flatten_jsonapi_item` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `_parse_error_details` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `_build_fields_query` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `_build_destination_attributes` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `_validate_non_empty_sequence` | — | **Keep** | Clear guard |
| `otbr_restapi_client.py` | `_validate_non_empty_string` | — | **Keep** | Clear guard |
| `otbr_restapi_client.py` | `_parse_media_type` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `_coerce_int` | — | **Keep** | Clear |
| `otbr_restapi_client.py` | `build_fields_mapping` | — | **Keep** | Clear public helper |
| `otbr_restapi_client.py` | `error_to_dict` | — | **Keep** | Clear |
| `otbr_restapi_client_cli.py` | `build_parser` | — | **Keep** | Standard CLI builder name |
| `otbr_restapi_client_cli.py` | `_add_node_commands` | — | **Keep** | Clear sub-parser builder |
| `otbr_restapi_client_cli.py` | `_add_devices_commands` | — | **Keep** | Clear |
| `otbr_restapi_client_cli.py` | `_add_diagnostics_commands` | — | **Keep** | Clear |
| `otbr_restapi_client_cli.py` | `_add_actions_commands` | — | **Keep** | Clear |
| `otbr_restapi_client_cli.py` | `_add_fields_argument` | — | **Keep** | Clear |
| `otbr_restapi_client_cli.py` | `build_client` | — | **Keep** | Clear factory |
| `otbr_restapi_client_cli.py` | `dispatch` | — | **Keep** | Standard dispatch pattern |
| `otbr_restapi_client_cli.py` | `_parse_dataset_input` | — | **Keep** | Clear |
| `otbr_restapi_client_cli.py` | `_parse_typed_values` | — | **Keep** | Clear |
| `otbr_restapi_client_cli.py` | `emit_output` | — | **Keep** | Clear |
| `otbr_restapi_client_cli.py` | `emit_error` | — | **Keep** | Clear |
| `otbr_restapi_client_cli.py` | `exit_code_for_exception` | — | **Keep** | Clear |
| `otbr_restapi_client_cli.py` | `main` | — | **Keep** | Standard entry-point |
| `otbr_restapi_raw_client.py` | _(all methods override parent)_ | — | **Keep** | Overrides must match parent interface |
| `otbr_restapi_raw_client_cli.py` | `build_parser` | — | **Keep** | Standard |
| `otbr_restapi_raw_client_cli.py` | `build_client` | — | **Keep** | Standard |
| `otbr_restapi_raw_client_cli.py` | `dispatch` | — | **Keep** | Standard |
| `otbr_restapi_raw_client_cli.py` | `main` | — | **Keep** | Standard entry-point |
| `otbr_restapi_download.py` | `build_parser` | — | **Keep** | Standard |
| `otbr_restapi_download.py` | `build_base_url` | — | **Keep** | Clear factory |
| `otbr_restapi_download.py` | `build_headers` | — | **Keep** | Clear factory |
| `otbr_restapi_download.py` | `download_json` | — | **Keep** | Clear |
| `otbr_restapi_download.py` | `download_all_restapi_endpoints` | `download_all_endpoints` | **Rename** | `restapi_` is redundant inside a module named `otbr_restapi_download` |
| `otbr_restapi_download.py` | `main` | — | **Keep** | Standard entry-point |
| `eve_parse.py` | `load_and_parse_eve_file` | `parse_eve_file` | **Rename** | `load_and_parse_` is verbose; `parse_` already implies loading; callers pass a path, not raw data |
| `eve_parse.py` | `enhance_eve_routes` | `enrich_eve_routes` | **Rename** | `enhance` and `enrich` are synonyms; `enrich_` is the verb used in `otbr_cli_meshdiag_topology.py`—use one verb project-wide |
| `eve_parse.py` | `main` | — | **Keep** | Standard entry-point |
| `dataset_merge.py` | `load_json` | — | **Keep** | Minimal and clear |
| `dataset_merge.py` | `normalize_identifier_text` | `norm_id_text` | **Rename** | `normalize_identifier_text` is four syllables; `norm_id_text` conveys the same in three short tokens |
| `dataset_merge.py` | `first_normalized_identifier` | `first_norm_id` | **Rename** | Same rationale; also pairs symmetrically with `norm_id_text` |
| `dataset_merge.py` | `get_canonical_extaddr` | — | **Keep** | Clear |
| `dataset_merge.py` | `get_canonical_omr` | — | **Keep** | Clear |
| `dataset_merge.py` | `normalize_record_aliases` | `norm_record_aliases` | **Rename** | `normalize_` → `norm_` for consistency with proposed `norm_id_text` and `norm_identifiers` |
| `dataset_merge.py` | `derive_mode_device` | — | **Keep** | Clear derivation function |
| `dataset_merge.py` | `normalize_identifiers` | `norm_identifiers` | **Rename** | Consistent `norm_` prefix |
| `dataset_merge.py` | `load_extaddr_device_label_map` | — | **Keep** | Matches the same function in `extaddr_device_label_map.py` |
| `dataset_merge.py` | `extract_records` | — | **Keep** | Clear |
| `dataset_merge.py` | `value_is_empty` | — | **Keep** | Clear predicate |
| `dataset_merge.py` | `merge_unique_strings` | — | **Keep** | Clear |
| `dataset_merge.py` | `values_equivalent` | — | **Keep** | Clear predicate |
| `dataset_merge.py` | `append_merge_conflict` | — | **Keep** | Clear |
| `dataset_merge.py` | `merge_lists` | — | **Keep** | Clear |
| `dataset_merge.py` | `deep_merge` | — | **Keep** | Clear |
| `dataset_merge.py` | `nested_get` | — | **Keep** | Clear |
| `dataset_merge.py` | `collect_merge_identity_values` | `get_identity_vals` | **Rename** | `collect_merge_identity_values` is five tokens; `get_identity_vals` says the same in three |
| `dataset_merge.py` | `find_candidate_node_ids` | — | **Keep** | Clear |
| `dataset_merge.py` | `index_node_identity_values` | `index_node_ids` | **Rename** | `identity_values` → `ids` without loss of meaning; consistent with `get_identity_vals` |
| `dataset_merge.py` | `add_identifier` | — | **Keep** | Clear |
| `dataset_merge.py` | `merge_nodes` | — | **Keep** | Clear |
| `dataset_merge.py` | `build_merged_records` | — | **Keep** | Clear |
| `dataset_merge.py` | `parse_file_list_args` | — | **Keep** | Clear |
| `dataset_merge.py` | `resolve_input_files` | — | **Keep** | Clear |
| `dataset_merge.py` | `parse_args` | — | **Keep** | Standard argparse helper |
| `dataset_merge.py` | `main` | — | **Keep** | Standard entry-point |
| `web_server.py` | `build_parser` | — | **Keep** | Standard |
| `web_server.py` | `main` | — | **Keep** | Standard entry-point |
| `web_server.py` | `do_GET` | — | **Keep** | HTTP handler interface—must not change |
| `web_server.py` | `_is_json_request` | — | **Keep** | Clear boolean predicate |
| `web_server.py` | `_resolve_json_file_path` | `_json_file_path` | **Rename** | `_resolve_` prefix is implied; the return type (a `Path`) makes the intent clear |
| `web_server.py` | `_serve_json_from_data_dir` | `_serve_json` | **Rename** | `_from_data_dir` is an implementation detail; callers only care that a JSON response is served |
| `td_cli.py` | `_add_otbr_cli_commands` | — | **Keep** | Clear builder helper |
| `td_cli.py` | `_add_otbr_restapi_commands` | — | **Keep** | Clear |
| `td_cli.py` | `_add_process_commands` | — | **Keep** | Clear |
| `td_cli.py` | `_add_merge_commands` | — | **Keep** | Clear |
| `td_cli.py` | `build_parser` | — | **Keep** | Standard |
| `td_cli.py` | `_load_extaddr_device_label_map` | `_load_extaddr_map` | **Rename** | `device_label_map` is already encoded in `extaddr`; shorter name is unambiguous |
| `td_cli.py` | `dispatch` | — | **Keep** | Standard dispatch |
| `td_cli.py` | `_forward_with_datadir` | — | **Keep** | Clear inner helper |
| `td_cli.py` | `main` | — | **Keep** | Standard entry-point |

---

## Summary

| Action | Count |
|--------|-------|
| **Keep** | ~125 |
| **Rename** | ~35 |

### Top rename themes

1. **Redundant module-context prefix** (`fetch_meshdiag_` inside a meshdiag
   module, `network_diag` inside a networkdiag module, `restapi_` inside a
   restapi module).
2. **Verbose synonyms** (`fetch_` → `get_`, `enhance_` → `enrich_`,
   `normalize_` → `norm_`, `statistics` → `stats`, `address_list` → `addrs`).
3. **PEP 8 uppercase** (`_enrich_field_VP`, `_enrich_field_DT`, etc.).
4. **Misleading verbs** (`save_topology_to_json_dict/list` returns data, it
   does not write to disk).
5. **camelCase parameter** (`hideSensitiveInfo` in `fetch_dataset_active`
   should be `hide_sensitive`).

---

*Draft — awaiting review before any code changes are made.*
