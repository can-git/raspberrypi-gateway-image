# Materialized content — do not commit

At build time this directory receives `provision/` (gitignored) — a copy of the
`nu-gateway-service` repo's `provision/` tree (nuprov + systemd unit + its own
`install.sh`). CI does this from the Bitbucket checkout; for a local build:

```bash
cp -r /path/to/nu-gateway-service/provision files/provision
rm -rf files/provision/tests files/provision/__pycache__ files/provision/.pytest_cache
```
