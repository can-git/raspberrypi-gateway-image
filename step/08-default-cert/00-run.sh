#!/bin/bash -e

# Bake the default "raspi-provision" bootstrap certificate into every device.
# This is a SHARED, low-privilege identity (broker ACL must restrict it to the
# nu/device/+/... provisioning topics only). It lets a freshly flashed device
# connect to the broker and announce itself until the per-customer certificate
# is installed manually over SSH into the same folder.

echo "Create /etc/nu/certs"
install -v -d -m 755 "${ROOTFS_DIR}/etc/nu/certs"

echo "Install default bootstrap certificate (raspi-provision)"
install -m 644 files/ca.pem          "${ROOTFS_DIR}/etc/nu/certs/ca.pem"
install -m 644 files/device.pem      "${ROOTFS_DIR}/etc/nu/certs/device.pem"
install -m 600 files/device-key.pem  "${ROOTFS_DIR}/etc/nu/certs/device-key.pem"

echo "Default certificate installed into /etc/nu/certs"
