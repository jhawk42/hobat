# Hobat: Home Assistant App

## Installation

Hobat uses the Docker API to run `ot-ctl` in the Home Assistant OpenThread
Border Router app container. After installing Hobat, disable **Protection mode**
on the app's page before starting it. Home Assistant controls this setting per
installation; it cannot be disabled from `config.yaml`.

Disabling Protection mode grants Hobat access to the host Docker socket. Only
enable this for a trusted image.

For OTBR datasets, the OpenThread Border Router app must be installed and running. 
Hobat can target both its standard HAOS container name, `addon_core_openthread_border_router` 
and the OTBR REST API.

For Home Assistant Matter datasets, install and start Matter Server. Hobat uses
host networking and connects read-only to `ws://localhost:5580/ws` by default.
The `TD_HA_MATTER_WS_HOST` and `TD_HA_MATTER_WS_PORT` environment variables can
override that endpoint.
Only nodes commissioned to that Matter controller are visible. Unavailable or
sleeping nodes may omit diagnostics, Wi-Fi Matter nodes do not expose Thread
diagnostics, and Matter collection does not replace OTBR network-wide data.

Thread Watch is optional. Set `thread_watch_host` to the hostname or IP
address of a trusted review server (without `http://`) and `thread_watch_port`
to its HTTP port, then restart the add-on. The defaults are `127.0.0.1` and
`9180`. The launcher exports `TD_THREAD_WATCH_HOST` and `TD_THREAD_WATCH_PORT`.
If you previously set `thread_watch_uri`, replace it with these two settings.
Host and port use HTTP; standalone CLI use of `--uri` still supports HTTPS.
These settings do not install or start Thread Watch. Keep the unauthenticated
review API and retained names and addresses on a trusted network.

## Optional nightly scheduler

To enable the nightly scheduler set `scheduler_enabled: true` in the
add-on Configuration tab. Set `ext_pan_id` to the intended Thread network.
Optionally set `scheduler_start_time` (strict `HH:MM`, default `04:20`) and
`scheduler_keep_days` (positive integer, default `10`). Restart the add-on
after changes. The scheduler uses the add-on process timezone; check the
offset and next local/UTC start in `td_cli system scheduler status --server-url URL`
before relying on it. Both container builds install timezone data. There is
no catch-up or automatic retry.

Automatic collection is full, followed by health processing and gated purge;
second-Sunday repack runs only after a successful nightly purge. Stop the
add-on before restoring its data directory. Retain/export complete INFO logs
for at least five selected run dates. See the [migration checklist](../README.md#replace-nightly-cron-with-the-optional-scheduler)
before enabling the timer.

## Web Interface

Start Hobat, then select **Open Web UI**. Dashboard data is persisted in the
app's `/data` directory and included in Home Assistant backups.

The dashboard and API must remain on the same browser origin. Home Assistant or
another reverse proxy must forward the dashboard's path-relative `/api/*`
requests to Hobat; Hobat does not emit CORS authorization headers. This is not
authentication and does not block direct HTTP clients that can reach port 9165.

Device Diagnostics are enabled by default. Set `device_actions_enabled: false`
to disable Ping and all other diagnostic actions. Set
`device_reset_enabled: false` to disable destructive OTBR Reset Counters while
leaving Ping available; disabling actions also disables reset. Existing saved
`false` values remain explicit opt-outs. Because same-origin access is not
authentication, default-on diagnostics require the Web UI to be limited to
trusted users by Home Assistant ingress or equivalent access control.

Set the optional `TD_DEBUG_LEVEL` app setting to `DEBUG`, `INFO`, `WARNING`, or
`ERROR` to control Hobat's default troubleshooting log level. Leave it unset to
use Hobat's `INFO` default. Explicit `--debug` or `--verbose` server arguments
continue to take precedence over this setting.

The app's `/data` directory can also be backed up with `td_cli system backups
create`. Collector-generated network credentials, including `networkKey` and
`pskc`, are redacted before persistence, and backups may contain
device identities. Stop Hobat before restoring one with `td_cli system backups
restore`; validation and staging complete before the active data directory is
replaced.

Select **Home Assistant Matter** to view Devices, Diagnostics, Mesh
Diagnostics, or Topology. Enable **Cache Only** before Sync when the dashboard
must not contact Matter Server. Refreshes are serialized under one Matter
source lock and expensive collections run as cancellable background jobs.

Select **thread-watch > Devices** for its cached passive inventory. Cache Only
does not collect. A normal Sync or Force Refresh can issue one bounded
`/api/devices` request. Duplicate and identity-less rows remain independent,
but the inventory is not a current-membership, merge, roster, or health claim
and carries an explicit unknown network scope.

