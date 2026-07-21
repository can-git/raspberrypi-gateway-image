#!/bin/bash -e

echo "Create nu folder on boot"
install -v -d "${ROOTFS_DIR}/boot/firmware/nu"

echo "Bake the default gateway.env (WM_GW_ID=0) — nuGatewayUpdate's start condition;
without it the docker stack never comes up on a fresh device (bench find 2026-07-21)"
install -m 755 files/gateway.env "${ROOTFS_DIR}/boot/firmware/nu/gateway.env"

echo "Add docker compose to home folder"
install -m 755 files/docker-compose.yml	"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/"

echo "Add systemd service to start Gateway at boot time"
install -m 644 files/nuGatewayUpdate.service	"${ROOTFS_DIR}/etc/systemd/system/"

echo "Add systemd service to configure sink at boot time"
install -m 644 files/nuSinkConfigurator.service	"${ROOTFS_DIR}/etc/systemd/system/"

echo "Add script to preload images without docker installed"
install -m 755 files/download-frozen-image-v2.sh  "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/"

echo "Preload the nugw image tar (materialized by CI from nu-gateway-service)"
if [ -f files/nugw.tar ]; then
	install -m 644 files/nugw.tar "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/"
else
	echo "ERROR: files/nugw.tar missing — build it from nu-gateway-service before running pi-gen" >&2
	exit 1
fi

echo "Add mosquitto config to accept ws connection"
install -m 644 files/config_ws_tcp.conf	"${ROOTFS_DIR}/etc/mosquitto/conf.d/"

echo "Execute install script"
on_chroot << EOF
systemctl enable nuGatewayUpdate.service

systemctl enable nuSinkConfigurator.service

EOF
