#!/bin/bash -e

# Bake a default WiFi connection so the gateway comes up ONLINE right after flash.
# Without this (and WPA_COUNTRY in ../config) the WiFi radio stays rf-killed and the
# device is unreachable unless an ethernet cable is plugged in.
#
# Credentials are NOT committed to git. They are read from, in order:
#   1) ./wifi.env  (gitignored, created locally or by CI from secrets)
#   2) WIFI_SSID / WIFI_PSK environment variables
# If neither is present the step is skipped (build still succeeds, just no WiFi baked).

if [ -f ./wifi.env ]; then
	# shellcheck disable=SC1091
	source ./wifi.env
fi

if [ -z "${WIFI_SSID}" ]; then
	echo "WARN: WIFI_SSID not set (no ./wifi.env, no env var) -> skipping default WiFi"
	exit 0
fi

echo "Baking default WiFi connection for SSID '${WIFI_SSID}'"

install -v -d -m 755 "${ROOTFS_DIR}/etc/NetworkManager/system-connections"

CONN_FILE="${ROOTFS_DIR}/etc/NetworkManager/system-connections/${WIFI_SSID}.nmconnection"

cat > "${CONN_FILE}" <<EOF
[connection]
id=${WIFI_SSID}
type=wifi
autoconnect=true
autoconnect-priority=10

[wifi]
mode=infrastructure
ssid=${WIFI_SSID}

[wifi-security]
key-mgmt=wpa-psk
psk=${WIFI_PSK}

[ipv4]
method=auto

[ipv6]
method=auto
EOF

# NetworkManager refuses to load connection files that are not mode 0600 / root-owned.
chmod 600 "${CONN_FILE}"
echo "Default WiFi connection written to ${CONN_FILE}"
