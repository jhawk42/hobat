# OTBR REST API Clients

This repository now provides two client pairs for the OTBR REST API:

- `td_get_otbr_restapi_client.py`
- `td_get_otbr_restapi_client_cli.py`
- `td_get_otbr_restapi_raw_client.py`
- `td_get_otbr_restapi_raw_client_cli.py`

The existing `td_get_otbr_restapi.py` script is intentionally left unchanged.

Default OTBR host:

- `127.0.0.1`
- default port remains `8081`

## Response Shapes

### Flattened client pair

The flattened client is intended for scripts that want simple Python objects.

- JSON:API item documents are flattened to a single dict with `id`, `type`, and `attributes` merged at top level.
- JSON:API collections are flattened to a list of item dicts.
- `--with-meta` on the flattened CLI keeps collection metadata alongside flattened items.

Files:

- `td_get_otbr_restapi_client.py`
- `td_get_otbr_restapi_client_cli.py`

### Raw client pair

The raw client is intended for callers that want the OTBR server payloads without flattening.

- JSON:API item documents remain `{ "data": { ... } }`
- JSON:API collections remain `{ "meta": { ... }, "data": [ ... ] }`
- Error documents remain in server envelope form when returned by the server and are still surfaced through typed exceptions on failure

Files:

- `td_get_otbr_restapi_raw_client.py`
- `td_get_otbr_restapi_raw_client_cli.py`

Implementation note:

- `OTBRRawRestApiClient` reuses the same HTTP, parsing, and error-handling layer as the flattened client but defaults `raw=True` on JSON:API-capable methods.
- `td_get_otbr_restapi_raw_client_cli.py` uses the same command surface as the flattened CLI and routes requests through the raw client library.

## Error Handling Contract

Both client pairs share the same exception types.

- `OTBRUsageError`
  Raised before sending a request when client-side input is invalid.

- `OTBRConnectionError`
  Raised when the OTBR server cannot be reached.

- `OTBRInvalidResponseError`
  Raised when the server returns malformed JSON where JSON was expected.

- `OTBRHTTPError`
  Raised when the server responds with an HTTP error status.
  Includes:
  - `status_code`
  - `reason`
  - `url`
  - parsed `errors` details when the OTBR API returns either `application/json` or `application/vnd.api+json`

## CLI Behavior

### Flattened CLI

- prints flattened JSON output by default
- supports `--raw` when you want the unmodified OTBR envelope

### Raw CLI

- prints raw server envelopes by default
- keeps the same subcommands and flags as the flattened CLI

CLI exit codes for both CLIs:

- `0`: success
- `2`: usage or local input error
- `3`: connection failure
- `4`: OTBR HTTP error response
- `5`: invalid response payload from server
- `1`: unexpected failure

## Automated Tests

Run both focused test files:

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python -m unittest test_td_get_otbr_restapi_client.py test_td_get_otbr_restapi_raw_client.py
```

Coverage includes:

- flattened JSON:API collection handling
- raw JSON:API collection handling
- structured HTTP error parsing
- client-side usage validation
- CLI output and exit-code behavior

## Command-Line Examples

These examples use the default live OTBR host `127.0.0.1:8081`.

1. Flattened CLI: get the OTBR node as a flattened object

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_client_cli.py node get
```

2. Flattened CLI: get the current Thread node state

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_client_cli.py node state get
```

3. Flattened CLI: list devices with collection metadata

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_client_cli.py devices list --with-meta
```

4. Raw CLI: get the OTBR node as a raw JSON:API envelope

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_raw_client_cli.py node get
```

5. Raw CLI: list devices as a raw JSON:API collection

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_raw_client_cli.py devices list
```

6. Raw CLI: enqueue an update-device-collection task and keep the raw server response

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_raw_client_cli.py actions enqueue update-device-collection --max-age 30 --max-retries 5 --device-count 10 --timeout 93
```

For the local mock server, do not use the live-default examples directly. Override both host and port explicitly, for example:

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_client_cli.py --host 127.0.0.1 --port 18081 node get
```

## Live OTBR Smoke Tests

These examples assume the current default live OTBR host `127.0.0.1`.

Do not reuse these live-default commands for the local mock server. The mock server requires explicit `--host 127.0.0.1 --port 18081` overrides.

Flattened CLI examples:

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_client_cli.py node get
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_client_cli.py devices list --with-meta
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_client_cli.py actions list --with-meta
```

Raw CLI examples:

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_raw_client_cli.py node get
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_raw_client_cli.py devices list
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_raw_client_cli.py actions list
```

Error-path examples:

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_client_cli.py devices get --device-id 0000000000000000
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_raw_client_cli.py devices get --device-id 0000000000000000
```

Expected results:

- success commands exit with `0`
- invalid resource IDs return structured stderr JSON and exit with `4`
- if OTBR is down, commands exit with `3`

### Validated live host example

The following commands were validated against the live OTBR REST API at `127.0.0.1:8081`.

Flattened client and CLI:

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_client_cli.py node get
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_client_cli.py node state get
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_client_cli.py devices list --with-meta
```

Raw client and CLI:

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_raw_client_cli.py node get
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_raw_client_cli.py devices list
```

Observed live results:

- `node get` returned a `threadBorderRouter` with id `1a7fbf0434e4f043`
- `node state get` returned `router`
- `devices list --with-meta` returned `meta.collection.total = 25`
- raw CLI returned JSON:API envelopes under `data` and `meta`

You can still override the default target explicitly when needed:

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_client_cli.py --host 127.0.0.1 devices list --with-meta
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_raw_client_cli.py --host 127.0.0.1 devices list
```

## Local Mock Server

Use the mock server when a live OTBR endpoint is not available.

Important:

- the client default target is the live OTBR host `127.0.0.1:8081`
- the mock server runs locally on `127.0.0.1:18081`
- when talking to the mock server, override both `--host` and `--port`
- do not rely on client defaults when testing the mock server

Start the mock server in one terminal:

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_mock_otbr_restapi_server.py --host 127.0.0.1 --port 18081
```

Run flattened smoke tests against it:

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_client_cli.py --host 127.0.0.1 --port 18081 node get
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_client_cli.py --host 127.0.0.1 --port 18081 devices list --with-meta
```

Run raw smoke tests against it:

```bash
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_raw_client_cli.py --host 127.0.0.1 --port 18081 node get
/workspaces/td/td_otbr_restapi_swagger/.venv/bin/python td_get_otbr_restapi_raw_client_cli.py --host 127.0.0.1 --port 18081 devices list
```

The mock server supports the high-value endpoints used by both client pairs:

- `/api/node`
- `/node/state`
- `/node/dataset/active`
- `/api/devices`
- `/api/diagnostics`
- `/api/actions`