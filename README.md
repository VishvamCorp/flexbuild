## FlexBuild Overview
---------------------
FlexBuild is a component-oriented lightweight build system and integration platform with
capabilities of flexible, ease-to-use, scalable system build and distro deployment.

Users can use flexbuild to easily build Debian-based RootFS, linux kernel, BSP
components and miscellaneous userspace applications (e.g. graphics, multimedia,
networking, connectivity, security, AI/ML, robotics, etc) against Debian-based library
dependencies to streamline the system build with efficient CI/CD.

With flex-installer, users also can easily install various distro to target storage
device (SD/eMMC card or USB/SATA disk) on target board or on host machine.


## Build Environment
--------------------
- Cross-build in Debian Docker container hosted on x86 Ubuntu or any other distro for arm64 target
- Cross-build on x86 host machine running Debian 12 for arm64 target
- Native-build on ARM board running Debian for arm64 target

## Host system requirement
- Docker hosted on Ubuntu LTS host (e.g. 22.04, 24.04) or other any distro
  Refer to [docker-setup](docs/FAQ-docker-setup.md)
  User can run 'bld docker' to create a Debian docker and build it in docker.
- Debian 12 host
  Refer to [host_requirement](docs/host_requirement.md)


## Supported distro for target arm64
------------------------------------------
- Debian-based userland    (base, desktop, server)


## Supported platforms
----------------------
- __iMX platform__:
imx8mpcartzy, imx8mmevk, imx8mpevk, imx8mpfrdm, imx8mqevk, imx8ulpevk, imx93evk, imx93frdm, imx91evk, imx91frdm

- __Layerscape platform__:
ls1028ardb, ls1043ardb, ls1046ardb, ls2160ardb


## Cartzy Usage
---------------
End-to-end flow for building an `imx8mpcartzy` image and writing it to an SD card.
Run the commands from the `flexbuild` directory.

### 1. Prepare the build environment

A one-time setup that creates (or attaches to) the Debian docker container and installs
the host-dependent packages. Note that `setup.env` is sourced twice — once on the host to
bootstrap docker, then again inside the container.

```console
$ cd flexbuild
$ . setup.env        # in the host environment
$ bld docker         # create or attach to the docker container
$ . setup.env        # again, now inside docker
$ bld host-dep       # install host-dependent packages
```

### 2. Configure the Cartzy overlay

`CARTZY_SYSTEM_PATH` points at the `cartzy_system` tree that sits next to `flexbuild`. Its
`imx8/os` subtree is rsynced into the rootfs as an overlay; `boot` and `kernel` are
excluded because those come from the BSP/kernel build, not the overlay.

```console
$ export CARTZY_SYSTEM_PATH=$(pwd)/../cartzy_system
$ export RFS_OVERLAY_DIR=$CARTZY_SYSTEM_PATH/imx8/os
$ export RFS_OVERLAY_EXCLUDES="boot kernel"
```

### 3. (Optional) Select the device tree

`boot.txt` defaults to the v1 DTB. To boot a different variant, override `fdt_file` either
interactively in U-Boot or persistently in `/boot/uEnv.txt`.

```bash
# In U-Boot:
setenv fdt_file imx8mp-cartzy-v2-base.dtb; saveenv; reset

# or in /boot/uEnv.txt:
fdt_file=imx8mp-cartzy-v2-disp.dtb
```

### 4. Build the image

Two interchangeable options - pick one. Option 1 is the plain flexbuild invocation.
Option 2 runs the same build through [tools/fbld.py](tools/fbld.py), which collapses the
noisy output into a single live status line while streaming the full log to `fb-logs/`.
Set `LOG_LEVEL=0` for debug-level detail. On macOS docker, pass `-j6` to cap parallelism
and avoid "Too many open files" errors.

```console
# Option 1 — plain flexbuild
$ bld -m imx8mpcartzy

# Option 2 — same build, wrapped for readable progress + full log
$ LOG_LEVEL=0 tools/fbld.py -- bld -m imx8mpcartzy -j6
```

### 5. (Optional) Bundle the artifacts (optional, for running `flex-installer` on another machine)

Collect the firmware, boot, rootfs and `flex-installer` into a single compressed archive
so it can be moved to the machine that will write the SD card.

```console
$ cd build_lsdk2506/images
$ mkdir -p bundle

$ FIRMWARE_IMG=$(ls -t firmware_imx8mpcartzy_sdboot.img 2>/dev/null | head -n1)
$ BOOT_TAR=$(ls -t boot_IMX_arm64_lts_*.tar.zst | head -n1)
$ ROOTFS_TAR=$(ls -t rootfs_lsdk2506_debian_cartzy_arm64.tar.zst 2>/dev/null | head -n1)

$ cp -L "$FIRMWARE_IMG" "$BOOT_TAR" "$ROOTFS_TAR" flex-installer bundle/
$ tar --zstd -cf imx8mpcartzy_bundle_$(date +%Y%m%d_%H%M).tar.zst -C bundle .
```

On the other machine, unpack the bundle (substitute the real timestamp):

```console
$ tar --zstd -xf imx8mpcartzy_bundle_YYYYMMDD_HHMM.tar.zst
```

### 6. Generate the SD-card image

```console
$ ./flex-installer -i mkwic -m imx8mpcartzy \
    -f firmware_imx8mpcartzy_sdboot.img \
    -b boot_IMX_arm64_lts_6.6.52.tar.zst \
    -r rootfs_lsdk2506_debian_cartzy_arm64.tar.zst
```

(Optional) You can also archive `sdcard.wic` and later flash it directly from the compressed file:
```console
$ zstd -19 -T0 sdcard.wic -o sdcard.wic.zst
$ zstd -dc sdcard.wic.zst | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress
```

### 7. Flash to the target device

> **Identify the correct block device first.** The UART console may appear as
> `/dev/ttyUSB0`, but that is **not** the storage device. Writing to the wrong device can
> destroy your host system disk — double-check before running `dd`.

```console
# Watch kernel messages while reconnecting the target storage / USB gadget:
$ sudo dmesg -w

# In another terminal, list block devices and identify the board by size/model
# (it often shows up as e.g. /dev/sda with model "UMS disk 0"):
$ lsblk -p -o NAME,SIZE,MODEL,TRAN,RM,MOUNTPOINT

# Then write sdcard.wic to the detected device (replace sdX):
$ sudo dd if=sdcard.wic of=/dev/sdX bs=4M conv=fsync status=progress
$ sudo sync
```

## Flexbuild Usage
------------------

```console
$ cd flexbuild
$ . setup.env  # (in host environment)
$ bld docker   # (create or attach to docker)
$ . setup.env  # (in docker environment)
$ bld host-dep # (install host dependent packages)

Usage: bld -m <machine>
   or  bld <target> [ <option> ]
```

Most used example with automated build:
```bash
 bld -m imx8mpevk                # automatically build BSP + kernel + NXP-specific components + Debian RootFS for imx8mpevk platform
 bld -m lx2160ardb               # same as above, for lx2160ardb platform
 bld auto -p IMX (or -p LS)      # same as above, for all arm64 iMX (or Layerscape) platforms
```

Most used example with separate command:
```bash
 bld bsp -m imx93frdm            # generate BSP composite firmware (including atf/u-boot/kernel/dtb/peripheral-firmware/initramfs) for single machine
 bld bspall [ -p IMX|LS ]        # generate BSP composite firmware for all i.MX or LS machines
 bld rfs [ -r debian:desktop ]   # generate Debian-based Desktop rootfs  (with more graphics/multimedia packages for Desktop)
 bld rfs -r debian:server        # generate Debian-based Server rootfs   (with more server related packages, no GUI Desktop)
 bld rfs -r debian:base          # generate Debian-based base rootfs     (small footprint with base packages)
 bld linux [ -p IMX|LS]          # compile linux kernel for all arm64 IMX or LS machines
 bld atf -m lx2160rdb -b sd      # compile atf image for SD boot on lx2160ardb
 bld boot [ -p IMX|LS ]          # generate boot partition tarball (including kernel,dtb,modules,distro bootscript) for iMX/LS machines
 bld apps                        # compile NXP-specific components against the runtime dependencies of Debian Desktop rootfs for i.MX machines
 bld apps -r debian:server -p LS # compile NXP-specific components against the runtime dependencies of Debian Server rootfs for LS machines
 bld merge-apps [ -r <type> ]    # merge NXP-specific components into target Debian rootfs (Desktop by default,add '-r debian:server' for Server)
 bld packrfs [ -r <type> ]       # pack and compress target rootfs as rootfs_xx.tar.zst (or add '-r debian:server' for Server)
 bld packapps [ -r <type> ]      # pack and compress target app components as apps_xx.tar.zst (add '-p LS' for Layerscape platforms)
 bld docker                      # create or attach docker container to build in docker
 bld clean                       # clean all obsolete firmware/linux/apps binary images except distro rootfs
 bld clean-apps [ -r <type> ]    # clean the obsolete NXP-specific apps components binary images
 bld clean-rfs [ -r <type> ]     # clean target debian-based server arm64 rootfs
 bld clean-bsp                   # clean obsolete BSP (u-boot/atf/firmware) images
 bld clean-linux                 # clean obsolete linux image
 bld list                        # list enabled machines and supported various components
 bld host-dep                    # automatically install the depended deb packages on host
```

## More info
------------
Please refer to https://nxp.com/nxpdebian for more information about NXP Debian Linux SDK Distribution.
[Debian Linux SDK User's Guide]((https://docs.nxp.com/bundle/UG10155).

[flexbuild_usage](docs/flexbuild_usage.md), [build_and_deploy_distro](docs/build_and_deploy_distro.md), [nxp_linux_sdk](docs/nxp_linux_sdk.md) for detailed information.
