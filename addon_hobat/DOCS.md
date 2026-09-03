# Home Assistant App: Hobat

## Installation

Hobat uses the Docker API to run `ot-ctl` in the Home Assistant OpenThread
Border Router app container. After installing Hobat, disable **Protection mode**
on the app's page before starting it. Home Assistant controls this setting per
installation; it cannot be disabled from `config.yaml`.

Disabling Protection mode grants Hobat access to the host Docker socket. Only
enable this for a trusted image.

The OpenThread Border Router app must be installed and running. Hobat targets
its standard HAOS container name, `addon_core_openthread_border_router`.

For Home Assistant Matter datasets, install and start Matter Server. Hobat uses
host networking and connects read-only to `ws://localhost:5580/ws` by default.
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

Select **Home Assistant Matter** to view Devices, Diagnostics, Mesh
Diagnostics, or Topology. Enable **Cache Only** before Sync when the dashboard
must not contact Matter Server. Refreshes are serialized under one Matter
source lock and expensive collections run as cancellable background jobs.

## Local Image Testing

The published app uses `ghcr.io/jhawk42/hobat-ha-app`, configured in
`config.yaml`. This package is separate from the regular
`ghcr.io/jhawk42/hobat` image. To force Supervisor to build the app locally,
temporarily comment out the `image` key.

Published app versions must use the version from `config.yaml` as their image
tag, for example `ghcr.io/jhawk42/hobat-ha-app:0.1.0`.

For a standalone build from the Hobat repository root, run:

```bash
docker build -f addon_hobat/Dockerfile -t local/hobat-ha-app .
```