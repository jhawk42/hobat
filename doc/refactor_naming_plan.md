# Refactor Naming Plan

## Goals

- Renaming .py files to follow a consistent naming convention.
- Establish a clear, consistent naming convention across all source files so that
the *data source* (REST API vs. `ot-ctl` CLI vs MDNS vs eve). Optionally the *role* (collection,
parsing, merging, utility, test) are visible in the file name where necessary.
- Preserving OTBR CLI vs REST API Distinction: Every file and public function name must make it immediately clear whether it wraps the **`ot-ctl` command-line tool** ("otbr cli") or calls the **OTBR REST API** ("otbr restapi").

---

## Naming Convention

| Category | File prefix segment | Example file |
|---|---|---|
| ot-ctl wrappers | `otbr_cli_` | `otbr_cli_router_table.py` |
| REST API clients / downloaders | `otbr_restapi_` | `otbr_restapi_client.py` |
| eve utilities | `eve_` | `eve_parse.py` |
| mdns utilities | `mdns_` | `mdns_thread_scopes.py` |
| Shared utilities | `util_` | `util_ot_ctl.py` |

---

## Phase 1 — Rename CLI (ot-ctl) Data-Collection Files

These files all import `td_util_ot_ctl` and ultimately call `ot-ctl`.

| Current name | New name |
|---|---|
| `td_get_otbr_cli_networkdiag_topology.py` | `otbr_cli_networkdiag_topology.py` |
| `td_get_otbr_cli_router_table.py` | `otbr_cli_router_table.py` |
| `td_get_otbr_cli_meshdiag_topology.py` | `otbr_cli_meshdiag_topology.py` |
| `td_get_otbr_cli_meshdiag_childtable.py` | `otbr_cli_meshdiag_childtable.py` |
| `td_get_otbr_cli_meshdiag_routerneighbortable.py` | `otbr_cli_meshdiag_routerneighbortable.py` |
| `td_get_otbr_cli_network_dataset_info.py` | `otbr_cli_network_dataset_info.py` |

**Steps for each file:**
1. `git mv src/<old>.py src/<new>.py`
2. Update all `import` / `from` statements in every file that references the
   old module name.
3. Update any `__main__` guard output filenames or references if they embed the
   old module name.
4. Add a one-line backward-compatible shim at the old path if external callers
   still depend on it (optional — only if needed).
5. Update `codebase_overview.md` to use the new file names throughout.

---

## Phase 2 — Rename REST API Data-Collection Files

These files call the OTBR HTTP REST API (port 8081 by default).

| Current name | New name |
|---|---|
| `td_get_otbr_restapi_client.py` | `otbr_restapi_client.py` |
| `td_get_otbr_restapi_client_cli.py` | `otbr_restapi_client_cli.py` |
| `td_get_otbr_restapi_raw_client.py` | `otbr_restapi_raw_client.py` |
| `td_get_otbr_restapi_raw_client_cli.py` | `otbr_restapi_raw_client_cli.py` |
| `td_get_otbr_restapi.py` | `otbr_restapi_download.py` |

**Steps for each file:**
1. `git mv src/<old>.py src/<new>.py`
2. Update all `import` / `from` statements in every file that references the
   old module name (including `td_merge.py` and test files).
3. Update `doc/otbr_restapi_clients.md` to use the new file names throughout.
4. Update `codebase_overview.md` to use the new file names throughout.

---

## Phase 3 — Rename Remaining Files (mDNS, Eve Parser, Extaddr Map)

| Current name | New name |
|---|---|
| `td_get_mdns_thread_scopes.py` | `mdns_thread_scopes.py` |
| `td_parse_eve.py` | `eve_parse.py` |
| `td_parse_extaddr_data_map.py` | `extaddr_device_label_map.py` |

**Steps for each file:**
1. `git mv src/<old>.py src/<new>.py`
2. Update all `import` / `from` statements in every file that references the
   old module name (including `td_merge.py` and test files).
3. Update `doc/otbr_restapi_clients.md` to use the new file names throughout.
4. Update `codebase_overview.md` to use the new file names throughout.


---

## Phase 4 — Update util files

| Current name | New name |
|---|---|
| `td_util_convert.py` | `util_convert.py` |
| `td_util_mdns.py` | `util_mdns.py` |
| `td_util_network.py` | `util_network.py` |
| `td_util_ot_ctl.py` | `util_ot_ctl.py` |

**Steps for each file:**
1. `git mv src/<old>.py src/<new>.py`
2. Update all `import` / `from` statements in every file that references the
   old module name (including `td_merge.py` and test files).
3. Update `codebase_overview.md` to use the new file names throughout.

---

## Phase 5 — Update test files

| Current name | New name |
|---|---|
| `test_td_get_otbr_restapi.py` | `test_otbr_restapi_download.py` |
| `test_td_get_otbr_restapi_client.py` | `test_otbr_restapi_client.py` |
| `test_td_get_otbr_restapi_raw_client.py` | `test_otbr_restapi_raw_client.py` |

These test files now live under `tests/`.

Update all internal `import` statements in each test file to point at the new
module names.

---

## Phase 6 — Update documentation

- `doc/otbr_restapi_clients.md` — replace every occurrence of old file names
  with the new `otbr_restapi_*` names.
- `doc/codebase_overview.md` — update the file inventory table to reflect the
  new names and add a "CLI vs REST API" section explaining the naming
  convention.

---

## Phase 7 — Validate

```bash
# Run the renamed REST API tests
python -m unittest tests/test_otbr_restapi_download.py \
                 tests/test_otbr_restapi_client.py \
                 tests/test_otbr_restapi_raw_client.py

# Run the util tests impacted by util module renames
python -m unittest tests/test_util_convert_base64_extaddr_to_hexnumber.py \
                 tests/test_util_convert_base64_extaddr_list_to_hexnumber_list.py \
                 tests/test_util_convert_hexnumber_extaddr_to_base64.py

# Verify no old module names remain in imports or script references
rg "td_get_otbr_cli_|td_get_otbr_restapi_|td_get_mdns_thread_scopes|td_parse_eve|td_parse_extaddr_data_map|td_util_convert|td_util_mdns|td_util_network|td_util_ot_ctl|test_td_get_otbr_restapi" src tests doc
```

---

## Summary of all renames

| Old name | New name | Category |
|---|---|---|
| `td_get_otbr_cli_networkdiag_topology.py` | `otbr_cli_networkdiag_topology.py` | cli |
| `td_get_otbr_cli_router_table.py` | `otbr_cli_router_table.py` | cli |
| `td_get_otbr_cli_meshdiag_topology.py` | `otbr_cli_meshdiag_topology.py` | cli |
| `td_get_otbr_cli_meshdiag_childtable.py` | `otbr_cli_meshdiag_childtable.py` | cli |
| `td_get_otbr_cli_meshdiag_routerneighbortable.py` | `otbr_cli_meshdiag_routerneighbortable.py` | cli |
| `td_get_otbr_cli_network_dataset_info.py` | `otbr_cli_network_dataset_info.py` | cli |
| `td_get_otbr_restapi_client.py` | `otbr_restapi_client.py` | restapi |
| `td_get_otbr_restapi_client_cli.py` | `otbr_restapi_client_cli.py` | restapi |
| `td_get_otbr_restapi_raw_client.py` | `otbr_restapi_raw_client.py` | restapi |
| `td_get_otbr_restapi_raw_client_cli.py` | `otbr_restapi_raw_client_cli.py` | restapi |
| `td_get_otbr_restapi.py` | `otbr_restapi_download.py` | restapi |
| `td_get_mdns_thread_scopes.py` | `mdns_thread_scopes.py` | mdns |
| `td_parse_eve.py` | `eve_parse.py` | eve |
| `td_parse_extaddr_data_map.py` | `extaddr_device_label_map.py` | parser |
| `td_util_convert.py` | `util_convert.py` | util |
| `td_util_mdns.py` | `util_mdns.py` | util |
| `td_util_network.py` | `util_network.py` | util |
| `td_util_ot_ctl.py` | `util_ot_ctl.py` | util |
| `test_td_get_otbr_restapi.py` | `test_otbr_restapi_download.py` | test |
| `test_td_get_otbr_restapi_client.py` | `test_otbr_restapi_client.py` | test |
| `test_td_get_otbr_restapi_raw_client.py` | `test_otbr_restapi_raw_client.py` | test |
