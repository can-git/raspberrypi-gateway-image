# Nu gateway image

Builds the **"nu" golden image** for a Nu / Wirepas gateway (KARAR 2026-07-13:
production first touch is this image — no first-boot download scripts). After flashing,
the device comes up **online over WiFi**, starts the full gateway stack, and announces
itself on the provisioning topic so it can be **commissioned remotely** without touching
the SD card again.

The base OS is built with [RPi-Distro/pi-gen](https://github.com/RPi-Distro/pi-gen)
(Raspberry Pi OS Lite, trixie/arm64) and customised through the `step/` folders.

## What runs on a flashed device

| Component | Form | Job |
| --------- | ---- | --- |
| `dbus` / `sink-service` / `transport-service-local` | docker (compose project `nu`) | Wirepas mesh access; local transport feeds host mosquitto |
| `transport-service` | docker | diagnostics to the **Wirepas backend** (kept on purpose — KARAR 2026-07-21) |
| `nu-gateway` (nugw) | docker, **preloaded from `nugw.tar`** — never a registry | local `gw-event` → parse/convert → **TBMQ over mutual TLS** |
| `nu-provision` | host systemd + venv (`/opt/nu-provision`) | recovery channel: beacon, setConfig, cert delivery, reboot |
| `nuSinkConfigurator` | host systemd oneshot | applies `/boot/firmware/nu/sink.env` → renames to `sink.success` (= consumed, **not** radio-verified) |
| `nuGatewayUpdate` | host systemd oneshot | first boot: `docker load` the preloaded tars, `docker compose up -d` |
| mosquitto | host service | local broker between Wirepas transport and nugw |

The provisioning protocol, setConfig envelope, and operator flow live in
**`nu-gateway-service`** (`docs/gateway-provisioning.md` + `provision/RUNBOOK.md`) —
this repo only bakes those components into an image and adds nothing of its own.

## Access defaults

| Setting   | Value           |
| --------- | --------------- |
| Username  | `nu`            |
| Password  | from the `FIRST_USER_PASS` build secret (not committed) |
| Hostname  | `nugw`          |
| SSH       | enabled         |
| WiFi      | baked at build time (see [step/07-network](step/07-network)) |

## Build inputs (never committed)

- **WiFi credentials** — `step/07-network/wifi.env` (or `WIFI_SSID`/`WIFI_PSK` env);
  CI materializes it from secrets. `WPA_COUNTRY` (in [config](config)) must be set or
  the WiFi radio stays rf-killed.
- **User password** — CI appends `FIRST_USER_PASS` to `config` from the secret.
- **Bootstrap certificate** — `step/08-default-cert/files/{ca,device,device-key}.pem`;
  the private key comes from the `BOOTSTRAP_DEVICE_KEY` secret. Baked into
  `/etc/nu/provision-certs` (see [step/08-default-cert](step/08-default-cert/README.md)).
- **nu-gateway-service source** (Bitbucket) — CI clones it via `NUGW_CLONE_URL`, builds
  `nugw.tar` (arm64) into `step/06-gateway-service/files/` and copies `provision/` into
  `step/10-nu-provision/files/provision/`.

## How a device comes up (STOCK)

1. **Flash + boot** → joins the baked WiFi, gets a DHCP IP.
2. `nuGatewayUpdate` loads the preloaded images and starts the compose stack.
   `nu-gateway` finds no `gateway.json` yet and waits in restart backoff — expected.
3. `nu-provision` connects to TBMQ with the shared bootstrap cert and beacons on
   `nu/provision`. From here on, commissioning is the standard flow in
   `nu-gateway-service/provision/RUNBOOK.md`: setConfig (identity + `WM_GW_ID` patch +
   staged `sink.env`), per-customer cert delivery to `/etc/nu/certs`,
   `provision:false` → reboot → normal mode.

Boot config lives on the FAT partition at `/boot/firmware/nu/` (`gateway.env`,
`sink.env` → `sink.success`, `gateway.json` after commissioning). `gateway.env` is
baked by [step/06](step/06-gateway-service) with `WM_GW_ID=0` — it is
`nuGatewayUpdate`'s start condition, so a fresh device brings the stack up
immediately. `sink.env` is NOT baked: it arrives later as a one-shot work order
from the provisioner ([templates/sink.env](templates/sink.env) is the reference).
`tenant.env` is retired (KARAR 2026-07-21): product/site identity lives in
`gateway.json` via setConfig.

## Local commands (over SSH)

```bash
docker compose -f /home/nu/docker-compose.yml logs   # stack logs
docker logs nu-gateway -f                            # nugw logs
journalctl -u nu-provision -f                        # provisioner logs
docker run --rm -v nu_dbus-volume:/var/run/dbus wirepas/gateway_transport_service wm-node-conf list
```

## Building

**CI (normal path):** GitHub Actions on `workflow_dispatch` or release — arm64 native
runner, secrets materialized automatically; see
[.github/workflows/build_full_image.yml](.github/workflows/build_full_image.yml).
Required repo secrets: `WIFI_SSID`, `WIFI_PSK`, `FIRST_USER_PASS`,
`BOOTSTRAP_DEVICE_KEY`, `BITBUCKET_TOKEN` (Atlassian API token, Bitbucket
`read:repository` scope — used to clone nu-gateway-service),
`WIREPAS_MQTT_PASSWORD` (Wirepas backend broker credential, baked into
`gateway.env` — without it the remote transport is "not authorised").

**Local:** materialize the same inputs by hand (wifi.env, device-key.pem,
`FIRST_USER_PASS` in `config`, `nugw.tar`, `files/provision/`), copy `step/*` into
pi-gen's `stage2/`, copy `config`, then run pi-gen's `build-docker.sh`.
