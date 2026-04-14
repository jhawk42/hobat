# Initial Refactor Naming Plan

## Goal

Establish a clear, consistent naming convention across all source files so that
the *data source* (REST API vs. `ot-ctl` CLI) and the *role* (collection,
parsing, merging, utility, test) are always visible in the file name.

This plan was proposed and partially executed in phases 1–6. The target naming
scheme described here is also the state documented in `doc/codebase_overview.md`.

---

## Naming Convention

| Category | Prefix | Example |
|---|---|---|
| REST API data-collection scripts | `td_get_otbr_restapi_` | `td_get_otbr_restapi_client.py` |
| ot-ctl CLI data-collection scripts | `td_get_otbr_cli_` | `td_get_otbr_cli_router_table.py` |
| mDNS / service-discovery scripts | `td_get_mdns_` | `td_get_mdns_thread_scopes.py` |
| Data-parsing helpers | `td_parse_` | `td_parse_eve.py` |
| Shared utility modules | `td_util_` | `td_util_ot_ctl.py` |
| Unit tests | `test_td_` | `test_td_get_otbr_restapi_client.py` |

---

## Phase 1 — Remove Personal Information and Tidy Comments

**Scope:** All Python and HTML files.

Steps:
1. Remove any personal names, email addresses, machine-specific paths, or
   internal host names from comments, docstrings, and string literals.
2. Remove redundant or misleading comments.
3. Normalise line endings, trailing whitespace, and blank-line counts to match
   the rest of the file.

---

## Phase 2 — Standardise Vendor / OUI References and Minor Renames

**Scope:** `td_util_mdns.py` and any callers.

Steps:
1. Move the OUI vendor lookup table into `td_util_mdns.py` (already the
   canonical home for mDNS utilities).
2. Remove the inline `VENDOR_OUI` dict that had been duplicated in
   `td_mdns_thread.py`.
3. Update all callers to import from the shared utility.
4. Rename any file-level constants or identifiers that used personal or
   project-internal names to generic equivalents.

---

## Phase 3 — Rename ot-ctl CLI Data-Collection Files

These files all call `ot-ctl` (via `td_util_ot_ctl`) and write a local JSON
output file.  Their names should reflect both that they *get* data and that the
source is the `ot-ctl` CLI.

| Current name (after Phases 1–2) | Target name |
|---|---|
| `td_otbr_networkdiag.py` | `td_get_otbr_cli_networkdiag_topology.py` |
| `td_otbr_router_table.py` | `td_get_otbr_cli_router_table.py` |
| `td_otbr_meshdiag_topology.py` | `td_get_otbr_cli_meshdiag_topology.py` |
| `td_otbr_meshdiag_childtable.py` | `td_get_otbr_cli_meshdiag_childtable.py` |
| `td_otbr_meshdiag_neighbortable.py` | `td_get_otbr_cli_meshdiag_routerneighbortable.py` |
| `td_otbr_dataset.py` | `td_get_otbr_cli_network_dataset_info.py` |

Steps for each file:
1. `git mv src/<old>.py src/<new>.py`
2. Update every `import` / `from` statement in files that depend on the renamed
   module.
3. Update output JSON filenames embedded in the `__main__` block if they still
   reflect the old module name (e.g. rename the written file from
   `td-otbr-networkdiag.json` → `td-otbr-cli-networkdiag-topology.json`).

---

## Phase 4 — Rename REST API Data-Collection Files

These files call the OTBR HTTP REST API (default port 8081).

| Current name | Target name |
|---|---|
| `td_otbr_download.py` | `td_get_otbr_restapi.py` |
| `td_otbr_client.py` | `td_get_otbr_restapi_client.py` |
| `td_otbr_client_cli.py` | `td_get_otbr_restapi_client_cli.py` |
| `td_otbr_raw_client.py` | `td_get_otbr_restapi_raw_client.py` |
| `td_otbr_raw_client_cli.py` | `td_get_otbr_restapi_raw_client_cli.py` |

Steps:
1. `git mv src/<old>.py src/<new>.py`
2. Update all `import` / `from` statements in every dependent file, in
   particular `dataset_merge.py` and the test files.
3. Update the output JSON filenames embedded in `td_get_otbr_restapi.py` if
   they still reference the old module name.
4. Update `doc/otbr_restapi_clients.md` to reference the new file names in all
   examples.

---

## Phase 5 — Rename Remaining Files (mDNS, Parser, Extaddr Map)

| Current name | Target name | Reason |
|---|---|---|
| `td_mdns_thread.py` | `td_get_mdns_thread_scopes.py` | Data-collection script; source is mDNS |
| `td_extaddr_map.py` | `td_parse_extaddr_data_map.py` | Parses the static label map file; not a collector |

Steps:
1. `git mv src/<old>.py src/<new>.py`
2. Update all callers (e.g. `dataset_merge.py`, any `__main__` entry points that
   import these modules).

---

## Phase 6 — HTML Cleanup and Documentation Updates

**Scope:** `tdash.html`, `td_web_tables.html`, `td_web_topology.html`,
`doc/codebase_overview.md`, `doc/otbr_restapi_clients.md`.

Steps:
1. Remove any personal information, internal host references, or non-generic
   device labels from the HTML dashboards.
2. Update `DATASET_REGISTRY` entries in the HTML files to use the new JSON
   output filenames produced by the renamed collectors (e.g.
   `td-otbr-cli-router-table.json`, `td-otbr-restapi-devices.json`).
3. Update all file-name references in `doc/codebase_overview.md` to match the
   target names from Phases 3–5.
4. Update all file-name references and command-line examples in
   `doc/otbr_restapi_clients.md`.
5. Update `README.md` "Getting started" commands to use the final file names.

---

## Target File Inventory (after all 6 phases)

### Data Collection — OTBR REST API

| File | Role |
|---|---|
| `td_get_otbr_restapi.py` | Fixed-target downloader (devices, diagnostics, dataset) |
| `td_get_otbr_restapi_client.py` | Flattened JSON:API client library |
| `td_get_otbr_restapi_client_cli.py` | CLI front-end for the flattened client |
| `td_get_otbr_restapi_raw_client.py` | Raw JSON:API client library |
| `td_get_otbr_restapi_raw_client_cli.py` | CLI front-end for the raw client |

### Data Collection — ot-ctl CLI

| File | ot-ctl command | Output JSON |
|---|---|---|
| `td_get_otbr_cli_network_dataset_info.py` | `dataset active`, `prefix meshlocal`, `br omrprefix favored` | `td-otbr-cli-network-dataset-info.json` |
| `td_get_otbr_cli_router_table.py` | `router table` | `td-otbr-cli-router-table.json` |
| `td_get_otbr_cli_meshdiag_topology.py` | `meshdiag topology ip6-addrs children` | `td-otbr-cli-meshdiag-topology.json` |
| `td_get_otbr_cli_meshdiag_childtable.py` | `meshdiag childtable <rloc16>` | `td-otbr-cli-meshdiag-router-childtables.json` |
| `td_get_otbr_cli_meshdiag_routerneighbortable.py` | `meshdiag routerneighbortable <rloc16>` | `td-otbr-cli-meshdiag-router-neighbortables.json` |
| `td_get_otbr_cli_networkdiag_topology.py` | `networkdiag get <rloc-ipv6> <tlvs>` | `td-otbr-cli-networkdiag-topology.json` |

### Data Collection — Other

| File | Role |
|---|---|
| `td_get_mdns_thread_scopes.py` | mDNS Thread service discovery |

### Data Parsing

| File | Role |
|---|---|
| `td_parse_eve.py` | Parses Eve App topology JSON export |
| `td_parse_extaddr_data_map.py` | Loads static extended-address → device-label map |

### Data Merging and Utilities

| File | Role |
|---|---|
| `dataset_merge.py` | Merges all collector outputs into a single JSON file |
| `td_util_ot_ctl.py` | Runs `ot-ctl` inside a Docker container |
| `td_util_network.py` | Network helpers (prefixes, RLOC16, OMR) |
| `td_util_convert.py` | Base64 ↔ hex conversion for extended addresses |
| `td_util_mdns.py` | OUI vendor lookup table |

### Tests and Mock Server

| File | Role |
|---|---|
| `td_mock_otbr_restapi_server.py` | In-process mock OTBR REST API server |
| `test_td_get_otbr_restapi.py` | Tests for `td_get_otbr_restapi.py` |
| `test_td_get_otbr_restapi_client.py` | Tests for the flattened client pair |
| `test_td_get_otbr_restapi_raw_client.py` | Tests for the raw client pair |

---

## Validation After All Phases

```bash
# Run the full test suite
python -m unittest \
    src/test_td_get_otbr_restapi.py \
    src/test_td_get_otbr_restapi_client.py \
    src/test_td_get_otbr_restapi_raw_client.py

# Confirm no old module names remain in import statements
grep -r "import td_otbr_client\b\|from td_otbr_client " src/
grep -r "import td_otbr_networkdiag\b\|from td_otbr_networkdiag " src/
grep -r "import td_mdns_thread\b\|from td_mdns_thread " src/
grep -r "import td_extaddr_map\b\|from td_extaddr_map " src/

# Confirm all target files exist
for f in \
    td_get_otbr_restapi.py \
    td_get_otbr_restapi_client.py \
    td_get_otbr_restapi_client_cli.py \
    td_get_otbr_restapi_raw_client.py \
    td_get_otbr_restapi_raw_client_cli.py \
    td_get_otbr_cli_router_table.py \
    td_get_otbr_cli_meshdiag_topology.py \
    td_get_otbr_cli_meshdiag_childtable.py \
    td_get_otbr_cli_meshdiag_routerneighbortable.py \
    td_get_otbr_cli_networkdiag_topology.py \
    td_get_otbr_cli_network_dataset_info.py \
    td_get_mdns_thread_scopes.py \
    td_parse_extaddr_data_map.py; do
  test -f "src/$f" && echo "OK: $f" || echo "MISSING: $f"
done
```
