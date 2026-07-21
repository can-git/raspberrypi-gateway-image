# Default bootstrap certificate (raspi-provision)

`files/ca.pem`, `files/device.pem`, `files/device-key.pem` are the **shared bootstrap
identity** (`CN=raspi-provision`) baked into every image. They are installed to
`/etc/nu/provision-certs` — the provisioner (`nu-provision`) uses them to reach TBMQ
over mutual TLS and publish its beacon on the provisioning topic until the device is
commissioned.

Two separate cert directories exist on a device:

| Directory | Identity | Who uses it |
| --------- | -------- | ----------- |
| `/etc/nu/provision-certs` | shared `raspi-provision` (baked here) | `nu-provision` (beacon + setConfig) |
| `/etc/nu/certs` | per-customer (delivered at commissioning) | `nu-gateway` telemetry mTLS |

`/etc/nu/certs` is created **empty** by this step; the per-customer certificate is
delivered into it by the provisioning flow (see `nu-gateway-service` RUNBOOK §5) —
not over ad-hoc SSH.

## Security
- The bootstrap identity is shared across all un-provisioned devices, so on the
  broker (TBMQ) its ACL **must** be restricted to the provisioning topics only
  (`nu/provision`). It must **not** be allowed on the telemetry topics.
- `files/device-key.pem` is the bootstrap private key. It is **gitignored**
  (see repo root `.gitignore`). Place it here before a local build, or let CI
  materialize it from the `BOOTSTRAP_DEVICE_KEY` secret. Keep it revocable.
