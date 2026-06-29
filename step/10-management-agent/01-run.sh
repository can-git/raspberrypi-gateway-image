#!/bin/bash -e

echo "Install nu management agent"
install -v -d "${ROOTFS_DIR}/opt/nu-agent"
install -m 755 files/agent.py  "${ROOTFS_DIR}/opt/nu-agent/agent.py"

echo "Install agent config (broker + cert paths)"
install -v -d "${ROOTFS_DIR}/etc/nu"
install -m 644 files/agent.env "${ROOTFS_DIR}/etc/nu/agent.env"

echo "Record image version"
echo "${IMG_NAME:-nu_gateway}-$(date -u +%Y%m%d)" > "${ROOTFS_DIR}/etc/nu/image-version"

echo "Install systemd service"
install -m 644 files/nuManagementAgent.service "${ROOTFS_DIR}/etc/systemd/system/"

on_chroot << EOF
systemctl enable nuManagementAgent.service
EOF
