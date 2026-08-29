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

## Web Interface

Start Hobat, then select **Open Web UI**. Dashboard data is persisted in the
app's `/data` directory and included in Home Assistant backups.

## Local Image Testing

The published app uses the image configured in `config.yaml`. To force
Supervisor to build the app locally, temporarily comment out the `image` key.

For a standalone build from the TDash repository root, run:

```bash
docker build -f addon_hobat/Dockerfile -t local/hobat .
```