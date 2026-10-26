#!/bin/bash
# Generate sdcard.wic from built artifacts. Run inside fbdebian container.
# Usage: docker compose exec fbdebian tools/docker-sdcard.sh [machine]
set -e

MACHINE=${1:-imx8mpcartzy}
FB_ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$FB_ROOT/build_lsdk2506/images"
IMAGES_DIR=$PWD

# bld refreshes this copy only during a full build; make sure mkwic runs the
# current script even when docker-build.sh was not re-run after an edit.
cp -f "$FB_ROOT/tools/flex-installer" "$IMAGES_DIR/flex-installer"

FIRMWARE_IMG=$(ls -t firmware_${MACHINE}_sdboot.img 2>/dev/null | head -n1)
BOOT_TAR=$(ls -t boot_IMX_arm64_lts_*.tar.zst 2>/dev/null | head -n1)
ROOTFS_TAR=$(ls -t rootfs_lsdk2506_debian_cartzy_arm64.tar.zst 2>/dev/null | head -n1)

if [ -z "$FIRMWARE_IMG" ] || [ -z "$BOOT_TAR" ] || [ -z "$ROOTFS_TAR" ]; then
    echo "ERROR: missing artifacts in $PWD - run docker-build.sh first:" >&2
    echo "  firmware: ${FIRMWARE_IMG:-MISSING}" >&2
    echo "  boot:     ${BOOT_TAR:-MISSING}" >&2
    echo "  rootfs:   ${ROOTFS_TAR:-MISSING}" >&2
    exit 1
fi

echo ">>> Generating sdcard.wic for $MACHINE from:"
echo "  firmware: $FIRMWARE_IMG"
echo "  boot:     $BOOT_TAR"
echo "  rootfs:   $ROOTFS_TAR"

# Run mkwic on the container's own filesystem: the Windows bind mount is slow
# for the multi-GB of writes mkwic does (sdcard.wic, rootfs extraction). The
# inputs are still read once from the bind mount, via absolute paths.
WORKDIR=$(mktemp -d /tmp/mkwic.XXXXXX)
trap 'rm -rf "$WORKDIR"' EXIT
FIRMWARE_ABS=$(readlink -f "$FIRMWARE_IMG")
BOOT_ABS=$(readlink -f "$BOOT_TAR")
ROOTFS_ABS=$(readlink -f "$ROOTFS_TAR")
(
    cd "$WORKDIR"
    "$IMAGES_DIR/flex-installer" -i mkwic -m "$MACHINE" \
        -f "$FIRMWARE_ABS" -b "$BOOT_ABS" -r "$ROOTFS_ABS"
)

cp --sparse=always "$WORKDIR/sdcard.wic" "$WORKDIR/sdcard-normalized.wic"
mv "$WORKDIR/sdcard-normalized.wic" "$WORKDIR/sdcard.wic"
bmaptool create -o "$WORKDIR/sdcard.wic.bmap" "$WORKDIR/sdcard.wic"
bmaptool copy "$WORKDIR/sdcard.wic" "$WORKDIR/sdcard-verify.wic"
cmp "$WORKDIR/sdcard.wic" "$WORKDIR/sdcard-verify.wic"
rm "$WORKDIR/sdcard-verify.wic"
mkdir -p /flexbuild/artifacts
# cp auto-detects the sparseness of sdcard.wic, so only allocated blocks are written
cp -aL "$WORKDIR/sdcard.wic" "$WORKDIR/sdcard.wic.bmap" "$FIRMWARE_IMG" "$BOOT_TAR" "$ROOTFS_TAR" flex-installer /flexbuild/artifacts/
pigz -kf /flexbuild/artifacts/sdcard.wic
echo ">>> Artifacts stored in /flexbuild/artifacts (Docker volume: flexbuild-artifacts):"
ls -lh /flexbuild/artifacts/
