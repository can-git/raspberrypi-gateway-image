# Nu gateway image

Builds a ready-to-use Raspberry Pi image for a Nu / Wirepas gateway. After flashing, the
device comes up **online over WiFi**, runs the gateway + converter, **announces itself to the
broker**, and can be **configured remotely** without touching the SD card again.

The base OS is built with [RPi-Distro/pi-gen](https://github.com/RPi-Distro/pi-gen) (Raspberry
Pi OS Lite, trixie/arm64) and customised through the `step/` folders.

## Access defaults

| Setting   | Value           |
| --------- | --------------- |
| Username  | `nu`            |
| Password  | `yc2024+90TR`   |
| Hostname  | `nugw`          |
| SSH       | enabled         |
| WiFi      | baked at build time (see [step/07-network](step/07-network)) |

## Build-time secrets (never committed)

These are read at build time and are gitignored:

- **WiFi credentials** — copy [step/07-network/wifi.env.example](step/07-network/wifi.env.example)
  to `step/07-network/wifi.env` and fill in `WIFI_SSID` / `WIFI_PSK`. `WPA_COUNTRY` (in
  [config](config)) must be set or the WiFi radio stays disabled.
- **Bootstrap certificate** — `step/08-default-cert/files/{ca,device,device-key}.pem`. The
  private key is gitignored; see [step/08-default-cert/README.md](step/08-default-cert/README.md).

## How a device comes up

1. **Flash + boot** → joins the default WiFi, gets a DHCP IP.
2. The **management agent** reads its identity from `WM_GW_ID` in
   `/boot/firmware/nu/gateway.env` (default `0` = unconfigured), connects to the broker with
   the default bootstrap certificate (`/etc/nu/certs`) and, while not provisioned, announces
   itself:
   - `nu/device/<WM_GW_ID>/announce` → `{ gw_id, local_ip, mac, version, provisioned }`
   You can watch this in MQTT Explorer.
3. **Commissioning** (one by one): set a unique `WM_GW_ID`, install the per-customer
   certificate over SSH, and (optionally) push config from MQTT Explorer.

## Remote configuration (setConfig)

The agent subscribes to `nu/device/<WM_GW_ID>/config/set` and applies the payload, then **reboots
to apply and verifies connectivity** — if the broker does not come back within
`NU_VERIFY_TIMEOUT`, it **rolls back to the last-known-good config** automatically.

| Topic | Direction |
| ----- | --------- |
| `nu/device/<WM_GW_ID>/announce`       | device → broker |
| `nu/device/<WM_GW_ID>/config/set`     | broker → device |
| `nu/device/<WM_GW_ID>/config/result`  | device → broker |
| `nu/device/<WM_GW_ID>/status` (retained) | device → broker |

Example `config/set` payload:

```json
{
  "rev": 1,
  "files": {
    "gateway.env": { "WM_GW_ID": "101034168" },
    "tenant.env":  { "PRODUCT": "t", "TENANT": "musteriX", "SITE": "atasehir", "VER": "v1" },
    "sink.env":    { "WM_CN_NETWORK_ADDRESS": "0xD8D42B", "WM_CN_NETWORK_CHANNEL": "9" }
  },
  "wifi": { "ssid": "Site-WiFi", "psk": "site-password" }
}
```

- `rev` must increase each time (older/equal revs are ignored → idempotent).
- `files` only accepts `gateway.env`, `sink.env`, `tenant.env`; any key inside is set/added,
  comments are preserved.
- `wifi` is optional. ⚠️ A wrong WiFi/broker change triggers the automatic rollback after reboot.

## Commissioning a device (operator runbook)

The per-customer certificate is generated once per customer on your server and **copied over
SSH** (it is shared across all of that customer's devices):

```bash
# IP comes from the announce beacon in MQTT Explorer
scp ca.pem device.pem device-key.pem nu@<device-ip>:/tmp/
ssh nu@<device-ip> "sudo mv /tmp/*.pem /etc/nu/certs/ && sudo systemctl restart nuManagementAgent && docker restart nu-converter"
```

Then publish a `config/set` message (with a unique `WM_GW_ID`) from MQTT Explorer.

## Boot config files

The gateway reads its config from the FAT boot partition at `/boot/firmware/nu/`
(`gateway.env`, `sink.env`, `tenant.env`). Templates are in [templates/](templates). These can
be edited offline on the SD card, or remotely via setConfig.

## Local commands (over SSH)

```bash
docker compose -f /home/nu/docker-compose.yml logs        # gateway logs
docker logs nu-converter -f                                # converter logs
journalctl -u nuManagementAgent -f                         # management agent logs
docker run --rm -v nu_dbus-volume:/var/run/dbus wirepas/gateway_transport_service wm-node-conf list
```

> Note: the gateway container images themselves come from `wirepas/...` on Docker Hub (the
> actual gateway software). Everything user-facing — user, hostname, services, volumes, paths —
> is `nu`.

## Releases

Images are built by GitHub Actions on tag/release; see
[.github/workflows/build_full_image.yml](.github/workflows/build_full_image.yml).
