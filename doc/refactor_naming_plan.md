# Refactor Naming Plan: Preserving CLI vs REST API Distinction

## Goal

Every file and public function name must make it immediately clear whether it
wraps the **`ot-ctl` command-line tool** ("otbr cli") or calls the **OTBR REST
API** ("otbr restapi").  The previous rename pass dropped those qualifiers, so
the two groups are no longer distinguishable from the file name alone.

---

## Naming Convention

| Category | File prefix segment | Example file |
|---|---|---|
| ot-ctl wrappers | `td_otbr_cli_` | `td_otbr_cli_router_table.py` |
| REST API clients / downloaders | `td_otbr_restapi_` | `td_otbr_restapi_client.py` |
| Shared utilities | `td_util_` | `td_util_ot_ctl.py` |

---

## Phase 1 — Rename CLI (ot-ctl) files

These files all import `td_util_ot_ctl` and ultimately call `ot-ctl`.

| Current name | New name |
|---|---|
| `td_otbr_networkdiag.py` | `td_otbr_cli_networkdiag.py` |
| `td_otbr_router_table.py` | `td_otbr_cli_router_table.py` |
| `td_otbr_meshdiag_topology.py` | `td_otbr_cli_meshdiag_topology.py` |
| `td_otbr_meshdiag_childtable.py` | `td_otbr_cli_meshdiag_childtable.py` |
| `td_otbr_meshdiag_neighbortable.py` | `td_otbr_cli_meshdiag_neighbortable.py` |
| `td_otbr_dataset.py` | `td_otbr_cli_dataset.py` |

**Steps for each file:**
1. `git mv src/<old>.py src/<new>.py`
2. Update all `import` / `from` statements in every file that references the
   old module name.
3. Update any `__main__` guard output filenames or references if they embed the
   old module name.
4. Add a one-line backward-compatible shim at the old path if external callers
   still depend on it (optional — only if needed).

---

## Phase 2 — Rename REST API files

These files call the OTBR HTTP REST API (port 8081 by default).

| Current name | New name |
|---|---|
| `td_otbr_client.py` | `td_otbr_restapi_client.py` |
| `td_otbr_client_cli.py` | `td_otbr_restapi_client_cli.py` |
| `td_otbr_raw_client.py` | `td_otbr_restapi_raw_client.py` |
| `td_otbr_raw_client_cli.py` | `td_otbr_restapi_raw_client_cli.py` |
| `td_otbr_download.py` | `td_otbr_restapi_download.py` |

**Steps for each file:**
1. `git mv src/<old>.py src/<new>.py`
2. Update all `import` / `from` statements in every file that references the
   old module name (including `td_merge.py` and test files).
3. Update `doc/otbr_restapi_clients.md` to use the new file names throughout.

---

## Phase 3 — Update test files

| Current name | New name |
|---|---|
| `test_td_get_otbr_restapi.py` | `test_td_otbr_restapi_download.py` |
| `test_td_get_otbr_restapi_client.py` | `test_td_otbr_restapi_client.py` |
| `test_td_get_otbr_restapi_raw_client.py` | `test_td_otbr_restapi_raw_client.py` |

Update all internal `import` statements in each test file to point at the new
module names.

---

## Phase 4 — Update documentation

- `doc/otbr_restapi_clients.md` — replace every occurrence of old file names
  with the new `td_otbr_restapi_*` names.
- `doc/codebase_overview.md` — update the file inventory table to reflect the
  new names and add a "CLI vs REST API" section explaining the naming
  convention.

---

## Phase 5 — Validate

```bash
# Run the existing test suite
python -m pytest src/test_td_otbr_restapi_download.py \
                 src/test_td_otbr_restapi_client.py \
                 src/test_td_otbr_restapi_raw_client.py -v

# Verify no old names remain in import statements
grep -r "from td_otbr_client import\|import td_otbr_client$" src/
grep -r "from td_otbr_networkdiag import\|import td_otbr_networkdiag$" src/
```

---

## Summary of all renames

| Old name | New name | Category |
|---|---|---|
| `td_otbr_networkdiag.py` | `td_otbr_cli_networkdiag.py` | cli |
| `td_otbr_router_table.py` | `td_otbr_cli_router_table.py` | cli |
| `td_otbr_meshdiag_topology.py` | `td_otbr_cli_meshdiag_topology.py` | cli |
| `td_otbr_meshdiag_childtable.py` | `td_otbr_cli_meshdiag_childtable.py` | cli |
| `td_otbr_meshdiag_neighbortable.py` | `td_otbr_cli_meshdiag_neighbortable.py` | cli |
| `td_otbr_dataset.py` | `td_otbr_cli_dataset.py` | cli |
| `td_otbr_client.py` | `td_otbr_restapi_client.py` | restapi |
| `td_otbr_client_cli.py` | `td_otbr_restapi_client_cli.py` | restapi |
| `td_otbr_raw_client.py` | `td_otbr_restapi_raw_client.py` | restapi |
| `td_otbr_raw_client_cli.py` | `td_otbr_restapi_raw_client_cli.py` | restapi |
| `td_otbr_download.py` | `td_otbr_restapi_download.py` | restapi |
| `test_td_get_otbr_restapi.py` | `test_td_otbr_restapi_download.py` | test |
| `test_td_get_otbr_restapi_client.py` | `test_td_otbr_restapi_client.py` | test |
| `test_td_get_otbr_restapi_raw_client.py` | `test_td_otbr_restapi_raw_client.py` | test |
