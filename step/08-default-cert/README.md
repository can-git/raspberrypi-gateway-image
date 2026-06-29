# Default bootstrap certificate (raspi-provision)

`files/ca.pem`, `files/device.pem`, `files/device-key.pem` are the **shared bootstrap
identity** (`CN=raspi-provision`) baked into every image. They are installed to
`/etc/nu/certs` so a freshly flashed device can connect to the broker and publish its
`nu/device/<uuid>/announce` beacon before it has a real per-customer certificate.

## Security
- This identity is shared across all un-provisioned devices, so on the broker (TBMQ)
  its ACL **must** be restricted to the provisioning topics only
  (`nu/device/+/announce`, `nu/device/+/config/set`, `nu/device/+/config/result`,
  `nu/device/+/status`). It must **not** be allowed on the telemetry topics.
- `files/device-key.pem` is the bootstrap private key. It is **gitignored** by default
  (see repo root `.gitignore`). Place it here before building, or provide it from a CI
  secret. Keep it revocable.

## Replacing with the real certificate (per customer, manual)
The per-customer certificate is delivered over SSH during commissioning:

```bash
scp ca.pem device.pem device-key.pem nu@<device-ip>:/tmp/
ssh nu@<device-ip> "sudo mv /tmp/*.pem /etc/nu/certs/ && docker restart nu-converter"
```
