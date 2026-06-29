#!/usr/bin/env python3
"""
Fleet config/cert pusher — the operator-side driver for the management agent.

Publishes a setConfig command to one device, a list of devices, or a whole fleet,
and (optionally) collects each device's verify result. The agent on each device then
snapshots its current config, applies the change, reboots, and self-verifies — rolling
back to the last-known-good if it can't reconnect. So this is "fire once, fleet rotates
itself, bad devices heal themselves" — no SSH, no per-device manual step.

Examples
--------
# Rotate the broker cert on every device (bundle dir has ca.pem/device.pem/device-key.pem):
#   the agent verifies the NEW cert by reconnecting; if it can't, it restores the OLD cert.
python fleet-set-config.py --devices-file fleet.txt \
    --cert-dir ./customer-1-bundle --wait

# Change a single env key on two devices:
python fleet-set-config.py --device 6005411963 --device 6005411964 \
    --set gateway.env WM_GW_ID=6005411963

# Local plain-broker smoke test (no TLS):
python fleet-set-config.py --device 0 --broker 127.0.0.1 --port 1883 --no-tls \
    --cert-dir ./bundle

Targets:  --device ID (repeatable)  and/or  --devices-file FILE (one id per line, # = comment)
Payload:  any combination of --cert-dir, --set FILE KEY=VALUE (repeatable), --wifi SSID:PSK
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time

import paho.mqtt.client as mqtt

CERT_FILES = {"ca": "ca.pem", "device": "device.pem", "device_key": "device-key.pem"}


def build_certs(cert_dir: str) -> dict:
    """Read ca/device/device-key PEMs from a bundle dir, return base64 for the payload."""
    out = {}
    for key, fname in CERT_FILES.items():
        path = os.path.join(cert_dir, fname)
        if os.path.exists(path):
            with open(path, "rb") as f:
                out[key] = base64.b64encode(f.read()).decode()
    if not out:
        sys.exit(f"no cert files ({'/'.join(CERT_FILES.values())}) found in {cert_dir}")
    return out


def build_files(sets: list[list[str]]) -> dict:
    """--set gateway.env WM_GW_ID=6005 -> {'gateway.env': {'WM_GW_ID': '6005'}}"""
    files: dict = {}
    for fname, kv in sets:
        if "=" not in kv:
            sys.exit(f"--set value must be KEY=VALUE, got {kv!r}")
        k, v = kv.split("=", 1)
        files.setdefault(fname, {})[k] = v
    return files


def load_targets(args) -> list[str]:
    ids = list(args.device)
    if args.devices_file:
        with open(args.devices_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    ids.append(line)
    # de-dupe, preserve order
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i); out.append(i)
    if not out:
        sys.exit("no targets: pass --device and/or --devices-file")
    return out


def make_client(args):
    try:
        from paho.mqtt.enums import CallbackAPIVersion
        c = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION1)
    except (ImportError, AttributeError, TypeError):
        c = mqtt.Client()
    if not args.no_tls:
        kw = {"ca_certs": args.ca}
        if args.certfile and args.keyfile:
            kw.update(certfile=args.certfile, keyfile=args.keyfile)
        c.tls_set(**kw)
    return c


def main():
    p = argparse.ArgumentParser(description="Push setConfig (certs/env/wifi) to the fleet.")
    p.add_argument("--device", action="append", default=[], help="target device id (repeatable)")
    p.add_argument("--devices-file", help="file with one device id per line")
    p.add_argument("--cert-dir", help="dir with ca.pem/device.pem/device-key.pem to rotate")
    p.add_argument("--set", nargs=2, action="append", default=[], metavar=("FILE", "KEY=VALUE"),
                   help="set an env key, e.g. --set gateway.env WM_GW_ID=6005 (repeatable)")
    p.add_argument("--wifi", help="SSID:PSK to push a WiFi connection")
    p.add_argument("--rev", type=int, default=int(time.time()),
                   help="monotonic config revision (default: epoch seconds)")
    p.add_argument("--broker", default="tbmq.nuteknoloji.com")
    p.add_argument("--port", type=int, default=5859)
    p.add_argument("--ca", default="/etc/nu/certs/ca.pem")
    p.add_argument("--certfile", help="operator client cert (mTLS publish)")
    p.add_argument("--keyfile", help="operator client key (mTLS publish)")
    p.add_argument("--no-tls", action="store_true", help="plain broker (local testing only)")
    p.add_argument("--wait", action="store_true", help="collect verify results before exiting")
    p.add_argument("--timeout", type=int, default=300, help="seconds to wait for results")
    p.add_argument("--dry-run", action="store_true", help="print payload + targets, publish nothing")
    args = p.parse_args()

    payload: dict = {"rev": args.rev}
    if args.cert_dir:
        payload["certs"] = build_certs(args.cert_dir)
    if args.set:
        payload["files"] = build_files(args.set)
    if args.wifi:
        ssid, _, psk = args.wifi.partition(":")
        payload["wifi"] = {"ssid": ssid, "psk": psk}
    if len(payload) == 1:
        sys.exit("nothing to do: pass --cert-dir, --set, and/or --wifi")

    targets = load_targets(args)
    # redact cert bodies for display
    shown = dict(payload)
    if "certs" in shown:
        shown["certs"] = {k: f"<{len(v)} b64 chars>" for k, v in shown["certs"].items()}
    print(f"rev={args.rev}  targets={len(targets)}  payload={json.dumps(shown)}")
    if args.dry_run:
        for t in targets:
            print(f"  would publish -> nu/device/{t}/config/set")
        return

    results: dict = {}
    expected = {t: f"nu/device/{t}/config/result" for t in targets}

    def on_message(_c, _u, msg):
        try:
            data = json.loads(msg.payload.decode())
        except (ValueError, UnicodeDecodeError):
            return
        for tid, topic in expected.items():
            if msg.topic == topic and tid not in results:
                results[tid] = data
                print(f"  [{tid}] {data.get('status')}: {data.get('detail','')}")

    client = make_client(args)
    if args.wait:
        client.on_message = on_message
    client.connect(args.broker, args.port, 60)
    client.loop_start()
    if args.wait:
        for topic in expected.values():
            client.subscribe(topic, qos=1)

    body = json.dumps(payload)
    for t in targets:
        client.publish(f"nu/device/{t}/config/set", body, qos=1)
        print(f"  published -> nu/device/{t}/config/set")

    if args.wait:
        print(f"waiting up to {args.timeout}s for verify results...")
        deadline = time.time() + args.timeout
        # 'applied' = committed after reboot; 'error' = apply failed before reboot
        while time.time() < deadline and len(
            [r for r in results.values() if r.get("status") in ("applied", "error", "skipped")]
        ) < len(targets):
            time.sleep(2)
        ok = [t for t, r in results.items() if r.get("status") == "applied"]
        print(f"\nconfirmed applied: {len(ok)}/{len(targets)}")
        missing = [t for t in targets if t not in results]
        if missing:
            print(f"no result yet (still rebooting/verifying or rolled back): {missing}")

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
