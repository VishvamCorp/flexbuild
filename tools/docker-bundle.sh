#!/bin/bash
# Bundle firmware + boot + rootfs into a single archive. Run inside fbdebian container.
set -e

cd "$(dirname "$0")/.."
. setup.env

MACHINE=${MACHINE:-imx8mpcartzy}
DISTROVARIANT=${DISTROVARIANT:-cartzy}
IMAGES=build_lsdk2506/images

cd "$IMAGES"

FIRMWARE_IMG=$(ls -t firmware_${MACHINE}_sdboot.img 2>/dev/null | head -n1)
BOOT_TAR=$(ls -t boot_IMX_arm64_lts_*.tar.zst | head -n1)
ROOTFS_TAR=$(ls -t rootfs_lsdk2506_debian_${DISTROVARIANT}_arm64.tar.zst 2>/dev/null | head -n1)

if [ -z "$FIRMWARE_IMG" ] || [ -z "$BOOT_TAR" ] || [ -z "$ROOTFS_TAR" ]; then
    echo "ERROR: the artifacts are not complete, run tools/docker-build.sh first" >&2
    exit 1
fi

mkdir -p bundle
cp -L "$FIRMWARE_IMG" "$BOOT_TAR" "$ROOTFS_TAR" flex-installer bundle/

BUNDLE=imx8mpcartzy_bundle_$(date +%Y%m%d_%H%M).tar.zst
tar --zstd -cf "$BUNDLE" -C bundle .

echo ">>> $IMAGES/$BUNDLE"
ls -lh "$BUNDLE"
