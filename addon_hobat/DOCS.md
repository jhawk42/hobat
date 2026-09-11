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

## Web Interface

Start Hobat, then select **Open Web UI**. Dashboard data is persisted in the
app's `/data` directory and included in Home Assistant backups.

The dashboard and API must remain on the same browser origin. Home Assistant or
another reverse proxy must forward the dashboard's path-relative `/api/*`
requests to Hobat; Hobat does not emit CORS authorization headers. This is not
authentication and does not block direct HTTP clients that can reach port 9165.

Device Diagnostics are disabled by default. Set `device_actions_enabled` to
enable Ping. Set `device_reset_enabled` as well to enable destructive OTBR
Reset Counters. Enabling reset alone has no effect. Because same-origin access
is not authentication, enable these options only when the Web UI is limited to
trusted users by Home Assistant ingress or equivalent access control.

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

