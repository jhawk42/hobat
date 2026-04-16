# Robustness, Reliability, Correctness & Typos — Fix Plan

**Scope**: All `src/*.py` and `src/tdash.html` files.  
**Out of scope**: Refactoring large files, adding new features, `tests/` files.  
**Approach**: Five sequential phases; each phase is independently deployable. Run the verification steps after every phase.

---

## Phase 1 — Cross-Cutting Infrastructure Issues

*These affect almost every file; fix them first to unblock later phases.*

### 1.1 Add subprocess timeouts — `util_ot_ctl.py`
`run_ot_ctl_command_stdio()` passes no `timeout=` to `subprocess.run()`.  
Every `ot-ctl` consumer can hang indefinitely.  
**Fix**: Add `timeout=30` as a default (configurable via env var `TD_OT_CTL_TIMEOUT`).

### 1.2 Fix type-annotation syntax errors
The following lines use `param:None` (an annotation of type `None`) instead of `param=None` (a default value):
- `util_ot_ctl.py` lines 22 & 42: `container_name:None`
- `otbr_cli_meshdiag_routerneighbortable.py` line 116: `extaddr_map:None`

**Fix**: Change each to the correct default-value syntax `param=None`.

### 1.3 Add network timeouts to `urlopen` calls
- `otbr_restapi_download.py` line 73: `urlopen()` called without timeout.
- `otbr_restapi_client.py`: `timeout` parameter can be `None`, passed directly to `urlopen()`.

**Fix**: Provide a default `timeout=30` in both call sites and expose the parameter to callers.

### 1.4 Narrow broad exception handling
- `otbr_restapi_client_cli.py` line 379: bare `except Exception`.
- `otbr_restapi_download.py` lines 71-82: catches all exceptions, hiding programming errors.

**Fix**: Replace with targeted exception types (`URLError`, `HTTPError`, `JSONDecodeError`, `OSError`). Log the exception class and message before re-raising or continuing.

**Files**: `src/util_ot_ctl.py`, `src/otbr_restapi_client.py`, `src/otbr_restapi_download.py`, `src/otbr_restapi_client_cli.py`, `src/otbr_cli_meshdiag_routerneighbortable.py`

---

## Phase 2 — File I/O & JSON Parsing Robustness

*Prevent crashes from missing or malformed files.*

### 2.1 Wrap all `open()` + `json.load()` calls
The following files open and parse JSON with no error handling:
- `extaddr_device_label_map.py` lines 13-14
- `eve_parse.py` line 35
- `tdash.py` lines 31-34

**Fix**: Wrap each with `try … except (OSError, json.JSONDecodeError)` and log a descriptive message. Return a sensible empty fallback (e.g. `{}` or `[]`) rather than crashing.

### 2.2 Validate JSON structure after load
After loading, verify shape at the boundary:
- `extaddr_device_label_map.py`: assert loaded value is a `list`; skip entries missing `"extaddr"` or `"device_label"` and log a warning instead of silently including bad data.
- Other callers: check for required top-level keys before accessing them.

### 2.3 Use atomic writes — `otbr_restapi_download.py`
Direct writes to target filenames leave corrupt files if the process crashes mid-write.  
**Fix**: Write to `<filename>.tmp`, then call `os.replace(tmp, target)` which is atomic on POSIX.

### 2.4 Guard base64/hex conversions — `util_convert.py`
`b64_to_extended_address()` and `extended_address_to_b64()` have no error handling around `base64.b64decode()` and `bytes.fromhex()`.  
**Fix**: Wrap with `try … except (binascii.Error, ValueError)` and raise a `ValueError` with a descriptive message. Also validate that inputs are non-empty strings before attempting conversion.

**Files**: `src/extaddr_device_label_map.py`, `src/eve_parse.py`, `src/tdash.py`, `src/otbr_restapi_download.py`, `src/util_convert.py`

---

## Phase 3 — Parsing Correctness & Silent Failures

*Fragile regex/string parsing that silently leaves data incomplete.*

### 3.1 Guard `int()` conversions on regex group strings
The following call `int()` on regex captures without catching `ValueError`:
- `otbr_cli_router_table.py` lines 70-72
- `otbr_cli_meshdiag_topology.py` line 56
- `mdns_thread_scopes.py` line 538
- `otbr_cli_networkdiag_topology.py` line 565

**Fix**: Wrap each with `try … except ValueError` and log which line/field failed to parse.

### 3.2 Fix division-by-zero — `otbr_cli_networkdiag_topology.py` line 461
Percentage calculation has no guard for `total_pkts == 0`.  
**Fix**: Add `if total_pkts > 0:` before the division; default the percentage to `0.0` otherwise.

### 3.3 Log regex non-matches instead of silently skipping
`otbr_cli_meshdiag_childtable.py`, `otbr_cli_meshdiag_routerneighbortable.py`, and `otbr_cli_router_table.py` all proceed silently when a regex pattern does not match, leaving fields unset.  
**Fix**: Add `logger.warning("unexpected format, pattern did not match: %r", line)` at each non-match branch.

### 3.4 Guard `None` before unpack — `mdns_thread_scopes.py` lines 555-558
`decode_thread_beacon_bitmap()` can return `None`; the return value is immediately unpacked as a tuple.  
**Fix**: Add `if result is not None:` before unpacking.

### 3.5 Fix bytes-to-int coercion — `mdns_thread_scopes.py` line 612
`int(ff_value) if isinstance(ff_value, bytes)` — `bytes` cannot be directly cast to `int`.  
**Fix**: Use `int.from_bytes(ff_value, 'big')` or `int(ff_value.decode())` depending on the intended encoding.

### 3.6 Guard empty-line `IndexError` — `otbr_cli_networkdiag_topology.py` line 399
`not line.startswith(' ') and ':' not in line.split()[0]` throws `IndexError` on an empty `line`.  
**Fix**: Prepend `line.strip() and` to the condition so empty lines are skipped first.

### 3.7 Guard `base64.b64decode()` — `mdns_thread_scopes.py` line 654
Called without error handling.  
**Fix**: Wrap with `try … except binascii.Error` and log a warning with the offending value.

**Files**: `src/otbr_cli_router_table.py`, `src/otbr_cli_meshdiag_topology.py`, `src/otbr_cli_meshdiag_childtable.py`, `src/otbr_cli_meshdiag_routerneighbortable.py`, `src/otbr_cli_networkdiag_topology.py`, `src/mdns_thread_scopes.py`

---

## Phase 4 — Reliability: Retries, Timeouts & Configurability

### 4.1 Add retry with exponential back-off — `otbr_restapi_client.py`
Single attempt; any transient `URLError` or HTTP 5xx causes immediate failure.  
**Fix**: Perform up to 3 attempts with `time.sleep(2 ** attempt)` for `URLError` and HTTP 5xx. Expose a `retries` parameter (default `3`).

### 4.2 Add retry to `otbr_restapi_download.py` `download_json()`
Same single-attempt issue as 4.1.  
**Fix**: Reuse the retry helper from `otbr_restapi_client.py` or implement an equivalent inline.

### 4.3 Fix DoS risk in `td_web4.py`
`Content-Length` is read from request headers without:
- Checking the header is present (raises `KeyError`).
- Capping the value (unbounded read; potential DoS).

**Fix**:  
```python
MAX_BODY_SIZE = 1 * 1024 * 1024  # 1 MB
content_length = int(self.headers.get('Content-Length', 0))
if content_length > MAX_BODY_SIZE:
    self.send_response(413)
    self.end_headers()
    return
```

### 4.4 Make port numbers configurable
`tdash_web.py`, `td_web1.py`, `td_web2.py`, `td_web3.py`, `td_web4.py` all hardcode port 8000/8087. Multiple scripts cannot run simultaneously.  
**Fix**: Read port from `PORT` environment variable, falling back to the current hardcoded value:
```python
PORT = int(os.environ.get("PORT", 8000))
```

### 4.5 Add `zeroconf` browse timeout — `mdns_thread_scopes.py` line 1025
The `ServiceBrowser` loop can block indefinitely.  
**Fix**: Add a configurable `browse_timeout` (default `30` seconds) and call `zeroconf.close()` after it expires.

**Files**: `src/otbr_restapi_client.py`, `src/otbr_restapi_download.py`, `src/td_web4.py`, `src/tdash_web.py`, `src/td_web1.py`–`src/td_web4.py`, `src/mdns_thread_scopes.py`

---

## Phase 5 — Typos, Naming Inconsistencies & HTML Correctness

*Low-risk, high-clarity fixes. Can be worked in parallel with Phase 4.*

| # | Location | Current text | Correct text |
|---|---|---|---|
| 5.1 | `src/otbr_cli_networkdiag_topology.py` lines ~435, ~460 | `"perentages"` | `"percentages"` |
| 5.2 | `src/tdash.html` line 180 | `"Max - Total Errors Packets %"` | `"Mac - Total Error Packets %"` |
| 5.3 | `src/tdash.html` line 183 | `"Mac - Total Discard Packets %"` | Verify against OpenThread field; standardise `Mac` vs `MAC` |
| 5.4 | `src/otbr_cli_meshdiag_childtable.py` | field name `"supvn"` | Expand to match OpenThread CLI output (e.g. `"supervision"`) |
| 5.5 | `src/otbr_cli_meshdiag_childtable.py` | field name `"q_msg"` | Rename to match OpenThread CLI output exactly |
| 5.6 | `src/eve_parse.py` | mixed `rloc` / `RLOC` casing | Standardise to lowercase `rloc16` throughout |
| 5.7 | `src/td_web3.py`, `src/td_web4.py` | `import logging` appears twice | Remove the duplicate import |
| 5.8 | `src/otbr_cli_networkdiag_topology.py` lines 645-646, 671-673; `src/eve_parse.py` line 80 | Stale `# TODO` comments | Convert to GitHub Issues or remove if no longer relevant |

---

## File-to-Phase Index

| File | Phases |
|---|---|
| `src/util_ot_ctl.py` | 1 |
| `src/otbr_restapi_client.py` | 1, 4 |
| `src/otbr_restapi_download.py` | 1, 2, 4 |
| `src/otbr_restapi_client_cli.py` | 1 |
| `src/otbr_cli_meshdiag_routerneighbortable.py` | 1, 3 |
| `src/util_convert.py` | 2 |
| `src/extaddr_device_label_map.py` | 2 |
| `src/eve_parse.py` | 2, 5 |
| `src/tdash.py` | 2 |
| `src/otbr_cli_router_table.py` | 3 |
| `src/otbr_cli_meshdiag_topology.py` | 3 |
| `src/otbr_cli_meshdiag_childtable.py` | 3, 5 |
| `src/otbr_cli_networkdiag_topology.py` | 3, 5 |
| `src/mdns_thread_scopes.py` | 3, 4 |
| `src/td_web4.py` | 4, 5 |
| `src/tdash_web.py` | 4 |
| `src/td_web1.py` – `src/td_web3.py` | 4 |
| `src/td_web3.py` | 5 |
| `src/tdash.html` | 5 |

---

## Verification Checklist

After each phase, run:

1. **Syntax check** — `python3 -m py_compile src/*.py` — must report zero errors.
2. **Test suite** — `python3 -m pytest tests/` — all existing tests must pass.
3. **Manual server smoke test** — start `src/tdash_web.py` and confirm `tdash.html` loads without console errors.
4. **Download smoke test** — run `src/otbr_restapi_download.py` against a live or mocked OTBR to confirm atomic-write and timeout behaviour.
5. **Typo grep** (after Phase 5) — `grep -r "perentages\|Errors Packets" src/` must return zero hits.
