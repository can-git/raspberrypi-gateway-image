#!/bin/bash -e

# Bake the shared "raspi-provision" bootstrap identity into every device.
# It lives in /etc/nu/provision-certs (nuprov's NUPROV_PROV_CERTS default) and
# the broker ACL must only ever allow it on the provisioning topics.
#
# /etc/nu/certs stays EMPTY in the image: that is the per-customer mTLS
# certificate directory, delivered by the provisioner during commissioning
# (nu-gateway-service RUNBOOK §5). nu-gateway mounts it read-only.

echo "Create cert dirs"
install -v -d -m 755 "${ROOTFS_DIR}/etc/nu/provision-certs"
install -v -d -m 755 "${ROOTFS_DIR}/etc/nu/certs"

echo "Install default bootstrap certificate (raspi-provision)"
install -m 644 files/ca.pem          "${ROOTFS_DIR}/etc/nu/provision-certs/ca.pem"
install -m 644 files/device.pem      "${ROOTFS_DIR}/etc/nu/provision-certs/device.pem"
install -m 600 files/device-key.pem  "${ROOTFS_DIR}/etc/nu/provision-certs/device-key.pem"

echo "Bootstrap certificate installed into /etc/nu/provision-certs"
