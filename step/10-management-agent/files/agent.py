#!/usr/bin/env python3
"""
Nu management agent (runs on the host as a systemd service, as root).

Responsibilities
----------------
1. Connect to the broker with the certificate in /etc/nu/certs (client-id = device UUID).
2. While the device is not provisioned, periodically announce itself on
   nu/device/<uuid>/announce  with {uuid, local_ip, mac, version, provisioned}.
3. Subscribe to nu/device/<uuid>/config/set and apply incoming config:
      - set/replace ANY key in the boot env files (gateway.env / sink.env / tenant.env),
        preserving comments and unrelated lines
      - set the WiFi connection
   then snapshot the previous (known-good) config, mark the new config for
   verification, and reboot to apply.
4. After reboot, verify connectivity: if the broker connects, COMMIT; if it does not
   within NU_VERIFY_TIMEOUT seconds, ROLL BACK to the last-known-good config and reboot.
5. Publish results to nu/device/<uuid>/config/result and retained state to
   nu/device/<uuid>/status.
"""

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

import paho.mqtt.client as mqtt

# --- paths (overridable via env so the agent can be run/tested off-device) --
NU_DIR = os.environ.get("NU_DIR", "/etc/nu")
ENV_DIR = os.environ.get("NU_ENV_DIR", "/boot/firmware/nu")
WIFI_DIR = os.environ.get("NU_WIFI_DIR", "/etc/NetworkManager/system-connections")
PROVISIONED_FILE = f"{NU_DIR}/provisioned"
REV_FILE = f"{NU_DIR}/config-rev"
PENDING_FILE = f"{NU_DIR}/pending-verify"
LASTGOOD_DIR = f"{NU_DIR}/lastgood"
VERSION_FILE = f"{NU_DIR}/image-version"
AGENT_ENV = f"{NU_DIR}/agent.env"

ALLOWED_ENV_FILES = {"gateway.env", "sink.env", "tenant.env"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] nu-agent: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("nu-agent")


# --- tiny env-file loader (KEY=VALUE) --------------------------------------
def load_env_file(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


CFG = {
    "NU_BROKER_HOST": "tbmq.nuteknoloji.com",
    "NU_BROKER_PORT": "5859",
    "NU_CA_CERT": "/etc/nu/certs/ca.pem",
    "NU_CERTFILE": "/etc/nu/certs/device.pem",
    "NU_KEYFILE": "/etc/nu/certs/device-key.pem",
    "NU_ANNOUNCE_INTERVAL": "30",
    "NU_VERIFY_TIMEOUT": "180",
}
CFG.update(load_env_file(AGENT_ENV))


# --- helpers ---------------------------------------------------------------
def read_first_line(path, default="unknown"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip() or default
    except OSError:
        return default


def get_local_ip():
    """Best-effort primary IP (the source IP used to reach the broker)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((CFG["NU_BROKER_HOST"], int(CFG["NU_BROKER_PORT"])))
        return s.getsockname()[0]
    except OSError:
        return "unknown"
    finally:
        s.close()


def get_mac():
    """MAC of the interface holding the default route, else first non-loopback."""
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                fields = line.split()
                if fields[1] == "00000000":  # default route
                    return read_first_line(f"/sys/class/net/{fields[0]}/address")
    except OSError:
        pass
    try:
        for iface in sorted(os.listdir("/sys/class/net")):
            if iface != "lo":
                return read_first_line(f"/sys/class/net/{iface}/address")
    except OSError:
        pass
    return "unknown"


def read_rev():
    try:
        return int(read_first_line(REV_FILE, "0"))
    except ValueError:
        return 0


def write_rev(rev):
    with open(REV_FILE, "w", encoding="utf-8") as f:
        f.write(str(rev))


def is_provisioned():
    return os.path.exists(PROVISIONED_FILE)


# --- env editing (preserve comments / unrelated lines) ---------------------
def set_env_values(path, updates):
    """Set or replace each key=value in `updates` inside the env file at `path`."""
    lines = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    remaining = dict(updates)
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            lines[i] = f"{key}={remaining.pop(key)}\n"

    if remaining:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        for key, val in remaining.items():
            lines.append(f"{key}={val}\n")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    log.info("Updated %s (%d keys)", path, len(updates))


def apply_files(files):
    for name, updates in files.items():
        if name not in ALLOWED_ENV_FILES:
            raise ValueError(f"file '{name}' is not allowed")
        if not isinstance(updates, dict):
            raise ValueError(f"file '{name}' must map keys to values")
        set_env_values(os.path.join(ENV_DIR, name), {k: str(v) for k, v in updates.items()})


def apply_wifi(wifi):
    ssid = wifi.get("ssid")
    psk = wifi.get("psk", "")
    if not ssid:
        raise ValueError("wifi requires 'ssid'")
    os.makedirs(WIFI_DIR, exist_ok=True)
    conn = os.path.join(WIFI_DIR, f"{ssid}.nmconnection")
    with open(conn, "w", encoding="utf-8") as f:
        f.write(
            "[connection]\n"
            f"id={ssid}\n"
            "type=wifi\n"
            "autoconnect=true\n"
            "autoconnect-priority=20\n\n"
            "[wifi]\n"
            "mode=infrastructure\n"
            f"ssid={ssid}\n\n"
            "[wifi-security]\n"
            "key-mgmt=wpa-psk\n"
            f"psk={psk}\n\n"
            "[ipv4]\nmethod=auto\n\n"
            "[ipv6]\nmethod=auto\n"
        )
    os.chmod(conn, 0o600)
    log.info("Wrote WiFi connection for SSID '%s'", ssid)


# --- snapshot / rollback ---------------------------------------------------
def _copy_tree(src, dst):
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(dst, exist_ok=True)
    if os.path.isdir(src):
        for name in os.listdir(src):
            sp = os.path.join(src, name)
            if os.path.isfile(sp):
                shutil.copy2(sp, os.path.join(dst, name))


def snapshot_lastgood():
    """Save the currently-working config so we can roll back to it."""
    os.makedirs(LASTGOOD_DIR, exist_ok=True)
    _copy_tree(ENV_DIR, f"{LASTGOOD_DIR}/env")
    _copy_tree(WIFI_DIR, f"{LASTGOOD_DIR}/wifi")
    log.info("Snapshotted last-known-good config")


def restore_lastgood():
    env_snap = f"{LASTGOOD_DIR}/env"
    wifi_snap = f"{LASTGOOD_DIR}/wifi"
    if os.path.isdir(env_snap):
        os.makedirs(ENV_DIR, exist_ok=True)
        for name in os.listdir(env_snap):
            shutil.copy2(os.path.join(env_snap, name), os.path.join(ENV_DIR, name))
    if os.path.isdir(wifi_snap):
        if os.path.isdir(WIFI_DIR):
            shutil.rmtree(WIFI_DIR)
        os.makedirs(WIFI_DIR, exist_ok=True)
        for name in os.listdir(wifi_snap):
            dst = os.path.join(WIFI_DIR, name)
            shutil.copy2(os.path.join(wifi_snap, name), dst)
            os.chmod(dst, 0o600)
    log.info("Restored last-known-good config")


def reboot():
    if os.environ.get("NU_NO_REBOOT") == "1":
        log.warning("NU_NO_REBOOT=1 -> skipping reboot (dev mode)")
        return
    log.info("Rebooting to apply config...")
    subprocess.call(["/sbin/reboot"])


# --- agent -----------------------------------------------------------------
class Agent:
    def __init__(self):
        self.gw_id = self.read_gw_id()
        self.version = read_first_line(VERSION_FILE)
        self.base = f"nu/device/{self.gw_id}"
        self.t_announce = f"{self.base}/announce"
        self.t_set = f"{self.base}/config/set"
        self.t_result = f"{self.base}/config/result"
        self.t_status = f"{self.base}/status"
        self.running = True
        self.client = self._make_client()

    @staticmethod
    def read_gw_id():
        # Identity = WM_GW_ID from the boot gateway.env. Default "0" = unconfigured.
        vals = load_env_file(os.path.join(ENV_DIR, "gateway.env"))
        return vals.get("WM_GW_ID") or "0"

    def _make_client(self):
        try:
            from paho.mqtt.enums import CallbackAPIVersion
            c = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION1,
                            client_id=self.gw_id, clean_session=True)
        except (ImportError, AttributeError, TypeError):
            c = mqtt.Client(client_id=self.gw_id, clean_session=True)
        if os.environ.get("NU_NO_TLS") != "1":  # NU_NO_TLS=1 for local plain-broker testing
            c.tls_set(ca_certs=CFG["NU_CA_CERT"],
                      certfile=CFG["NU_CERTFILE"],
                      keyfile=CFG["NU_KEYFILE"])
        c.on_connect = self.on_connect
        c.on_message = self.on_message
        return c

    # ---- payloads ----
    def status_payload(self):
        return json.dumps({
            "gw_id": self.gw_id,
            "local_ip": get_local_ip(),
            "mac": get_mac(),
            "version": self.version,
            "provisioned": is_provisioned(),
            "rev": read_rev(),
        })

    def publish_result(self, rev, status, detail=""):
        self.client.publish(self.t_result,
                            json.dumps({"rev": rev, "status": status, "detail": detail}),
                            qos=1)

    # ---- mqtt callbacks ----
    def on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            log.error("Broker connection failed, rc=%s", rc)
            return
        log.info("Connected to broker as %s", self.gw_id)
        client.subscribe(self.t_set, qos=1)
        client.publish(self.t_status, self.status_payload(), qos=1, retain=True)
        # We are connected -> if a config trial is pending, this proves it works.
        self._commit_if_pending()

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            log.error("Bad setConfig payload: %s", e)
            return
        self.handle_set_config(payload)

    # ---- config apply with verify/rollback ----
    def handle_set_config(self, payload):
        rev = int(payload.get("rev", 0))
        if rev <= read_rev():
            log.info("Ignoring rev %s (already at %s)", rev, read_rev())
            self.publish_result(rev, "skipped", "rev already applied")
            return
        try:
            # Current config works (we are connected), so snapshot it as known-good.
            snapshot_lastgood()
            if "files" in payload:
                apply_files(payload["files"])
            if "wifi" in payload:
                apply_wifi(payload["wifi"])
        except Exception as e:  # noqa: BLE001 - report any apply failure back
            log.exception("Failed to apply config")
            self.publish_result(rev, "error", str(e))
            return

        # Mark the new config for verification on next boot, then reboot.
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump({"rev": rev}, f)
        self.publish_result(rev, "applying", "rebooting to apply and verify")
        log.info("Config rev %s staged; rebooting for verification", rev)
        time.sleep(2)
        reboot()

    def _commit_if_pending(self):
        if not os.path.exists(PENDING_FILE):
            return
        try:
            with open(PENDING_FILE, "r", encoding="utf-8") as f:
                pending = json.load(f)
            rev = int(pending.get("rev", 0))
        except (ValueError, OSError):
            rev = read_rev()
        write_rev(rev)
        if not is_provisioned():
            open(PROVISIONED_FILE, "w").close()
        os.remove(PENDING_FILE)
        self.publish_result(rev, "applied", "verified after reboot")
        self.client.publish(self.t_status, self.status_payload(), qos=1, retain=True)
        log.info("Committed config rev %s", rev)

    # ---- background loops ----
    def announce_loop(self):
        interval = int(CFG["NU_ANNOUNCE_INTERVAL"])
        while self.running:
            if not is_provisioned():
                self.client.publish(self.t_announce, self.status_payload(), qos=1)
            time.sleep(interval)

    def verify_watchdog(self):
        """If a config trial never connects within the timeout, roll back."""
        if not os.path.exists(PENDING_FILE):
            return
        timeout = int(CFG["NU_VERIFY_TIMEOUT"])
        log.info("Config trial pending; verifying connectivity within %ss", timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not os.path.exists(PENDING_FILE):
                return  # committed by on_connect
            time.sleep(3)
        if os.path.exists(PENDING_FILE):
            log.error("Verification timed out -> rolling back")
            restore_lastgood()
            os.remove(PENDING_FILE)
            reboot()

    def run(self):
        threading.Thread(target=self.verify_watchdog, daemon=True).start()
        threading.Thread(target=self.announce_loop, daemon=True).start()
        while self.running:
            try:
                self.client.connect(CFG["NU_BROKER_HOST"], int(CFG["NU_BROKER_PORT"]), 60)
                self.client.loop_forever()
            except Exception as e:  # noqa: BLE001 - keep retrying forever
                log.error("MQTT loop error: %s; retry in 10s", e)
                time.sleep(10)


if __name__ == "__main__":
    os.makedirs(NU_DIR, exist_ok=True)
    Agent().run()
