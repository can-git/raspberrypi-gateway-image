#!/bin/bash -e

# Install the nu-provision host service (recovery channel: beacon + setConfig +
# cert delivery + reboot). The source of truth is the nu-gateway-service repo's
# provision/ tree — CI materializes it into files/provision (gitignored) before
# the build; for a local build copy it there yourself. Its own install.sh is
# what runs inside the image, so image and bench installs cannot drift.

if [ ! -f files/provision/install.sh ]; then
	echo "ERROR: files/provision/ missing — materialize it from nu-gateway-service before running pi-gen" >&2
	exit 1
fi

echo "Copy nu-provision source into rootfs"
rm -rf "${ROOTFS_DIR}/tmp/nu-provision-src"
cp -r files/provision "${ROOTFS_DIR}/tmp/nu-provision-src"

echo "Run the repo installer inside the image (venv + deps + unit enable)"
on_chroot << EOF
bash /tmp/nu-provision-src/install.sh
rm -rf /tmp/nu-provision-src
EOF

echo "Record image version (announced by the provisioning beacon)"
install -v -d "${ROOTFS_DIR}/etc/nu"
IMG_VERSION="${IMG_NAME:-nu_gateway}-$(date -u +%Y%m%d)"
echo "NUPROV_IMAGE_TAG=${IMG_VERSION}" > "${ROOTFS_DIR}/etc/nu/image.env"
echo "${IMG_VERSION}" > "${ROOTFS_DIR}/etc/nu/image-version"

echo "Point the unit at the image env"
install -v -d "${ROOTFS_DIR}/etc/systemd/system/nu-provision.service.d"
cat > "${ROOTFS_DIR}/etc/systemd/system/nu-provision.service.d/10-image.conf" << 'CONF'
[Service]
EnvironmentFile=-/etc/nu/image.env
CONF
