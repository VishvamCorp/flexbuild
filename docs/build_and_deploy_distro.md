## Build and Deploy Various Distro
----------------------------------
FlexBuild supports generating various distro in different scale, including rich OS (Debian-based) and embedded
Linux distro (Yocto-based, Buildroot-based). Users can choose an appropriate distro according to use case.

```
Usage: bld rfs [ -r <distro_type>:<distro_variant> ] [ -a <arch> ]
$ bld rfs -r debian:base          # generate Debian-based base userland with basic packages
$ bld rfs -r debian:desktop       # generate Debian-based desktop userland (with GPU/NPU/VPU/ISP HW acceleration) for HMI/Multimedia use case
$ bld rfs -r debian:server        # generate Debian-based server userland (w/o GUI desktop) for Industrial/IoT/Networking/Connectivity use case
$ bld rfs -r poky:tiny            # generate Yocto-based tiny arm64 userland
$ bld rfs -r poky:devel           # generate Yocto-based devel arm64 userland
$ bld rfs -r buildroot:tiny       # generate Buildroot-based tiny arm64 userland
$ bld rfs -r buildroot:devel      # generate Buildroot-based devel arm64 userland
```
To quickly install a new .deb package onto the target debian-based arm64 userland on host machine, run the command as below
```
$ sudo chroot build/rfs/rootfs_<sdk_version>_debian_desktop_arm64 apt install <package-name>
```



__Example: Build and deploy debian-based desktop distro for multimedia graphics scenario__
```
$ bld bsp -m imx8mpevk       # generate BSP composite firmware (firmware_imx8mpevk_sdboot_lpddr4.img)
$ bld rfs                    # generate debian-based desktop userland ('-r debian:desktop' by default)
$ bld boot                   # genrate boot_IMX_arm64_lts_<version>.tar.zst  ('-p IMX' by default)
$ bld apps                   # build all apps components against debian-based desktop userland
$ bld merge-apps             # merge apps components into target debian-based desktop userland
$ bld packrfs                # pack target userland as .tar.zst (optionally)

$ cd build_lsdk/images
$ flex-installer -i pf -d /dev/sdx
$ flex-installer -d /dev/sdx -m imx8mpevk -f firmware_imx8mpevk_sdboot_lpddr4.img -b boot_IMX_arm64_lts_xx.tgz \
                 -r ../../build_lsdk/rfs/rootfs_lsdkxx_debian_desktop_arm64
```



__Example: Build and deploy debian-based server distro for industrial/iot/networking scenario__
```
$ bld bsp -m lx2160ardb              # generate composite firmware_lx2160ardb_xxboot.img
$ bld rfs -r debian:server           # generate debian-based server userland
$ bld boot -p LS                     # genrate boot_LS_arm64_lts_<version>.tar.zst
$ bld apps -r debian:server -p LS    # build NXP-specific apps components against debian-based server userland
$ bld merge-apps -r debian:server    # merge apps components into target debian-based server userland
$ bld packrfs -r debian:server       # pack and compress target userland as .tgz

$ cd build_lsdk/images
$ flex-installer -i pf -d /dev/sdx
$ flex-installer -d /dev/sdx -m lx2160ardb -f firmware_lx2160ardb_sdboot.img -b boot_LS_arm64_lts_xx.tgz \
                 -r ../../build_lsdk/rfs/rootfs_lsdkxx_debian_server_arm64
```
User can add/remove the default deb packages by modifying configs/debian/debian-xx-arm64.yaml.




__Example: Build and deploy Buildroot-based distro__
```
Usage: bld rfs -r buildroot:<distro_scale> -a <arch>
The <distro_scale> can be tiny, devel, imaevm,  <arch> can be arm32, arm64
$ bld rfs -r buildroot:devel:custom      # customize buildroot .config in interactive menu
$ bld rfs -r buildroot:devel             # generate buildroot userland
$ bld rfs -r buildroot:tiny              # generate arm64 rootfs as per arm64_tiny_defconfig
$ bld rfs -r buildroot:devel -a arm32    # generate arm32 rootfs as per arm32_devel_defconfig
$ bld rfs -r buildroot:imaevm            # generate arm64 rootfs as per arm64_imaevm_defconfig
$ bld bsp -m ls1046ardb
$ bld bsp -m imx8mpevk
$ bld boot -p LS
$ cd build_lsdk/images
$ flex-installer -r rootfs_<sdk_version>_buildroot_tiny_arm64.tgz -b boot_LS_arm64_lts_<version>.tgz -f firmware_ls1046ardb_sdboot.img -d /dev/mmcblk0
```
User can modify the config file configs/buildroot/<arch>_<distro_scale>_defconfig to customize various packages.


__Cartzy build modes__
```
# Full build: use after application, kernel, BSP or rootfs changes
$ tools/docker-build.sh imx8mpcartzy

# Rootfs only: use after rootfs content or config changes
$ tools/docker-build.sh imx8mpcartzy --rootfs-only
```

__Preinstalled Docker__

Docker packages are set in `configs/board/imx8mpcartzy.conf`:
```
ROOTFS_DOCKER_PACKAGES="docker-ce docker-ce-cli containerd.io docker-compose-plugin"
```
After changing it, rerun the rootfs-only build (one rebuild is enough; the
board never needs internet). Docker is installed at build time from
download.docker.com, its services are enabled, and the `cartzy` and
`debian` users are in the `docker` group.

__Docker data lives on the secondary medium (SD card / second eMMC)__

`/var/lib/docker` is never on the boot eMMC. At every boot
`cartzy-docker-storage.service` finds a secondary medium (any mmc disk
except the boot device, with a partition larger than 6G) and mounts it at
`/var/lib/docker`. docker and containerd require that unit, so without a
usable medium docker does not start (fail-closed) - it never silently
fills the OS partition.

What the service does with the medium it finds:
- ext4 with docker data (`overlay2/` + `image/`) or label `docker-data`:
  mounted as is - **data survives re-flashing the boot eMMC**;
- empty card (vfat leftovers, blank partition, only `lost+found`):
  reformatted and labeled `docker-data`;
- anything else: never touched automatically.

Check on the flashed board:
```
$ ssh root@<board-ip> systemctl status cartzy-docker-storage   # active (exited)
$ ssh root@<board-ip> findmnt /var/lib/docker                  # /dev/mmcblk0p1
$ ssh root@<board-ip> lsblk -o NAME,SIZE,LABEL                 # docker-data
$ ssh root@<board-ip> cartzy-docker-storage.sh status          # classification dump
$ ssh root@<board-ip> docker version                          # Server: section = daemon is up
$ ssh root@<board-ip> docker compose version  # Docker Compose version v2...
$ ssh root@<board-ip> docker ps
$ ssh root@<board-ip> id cartzy               # groups include docker
```

If the boot log shows a medium warning:
```
# no usable medium: insert the SD card / attach the eMMC, then:
$ ssh root@<board-ip> /usr/local/sbin/cartzy-docker-storage.sh adopt   # no reboot needed
# medium refused because it holds other data - wipe it explicitly:
$ ssh root@<board-ip> /usr/local/sbin/cartzy-docker-storage.sh adopt --force /dev/mmcblk0p1
```

__Cartzy worktree cleanup__

```bash
# Full cleanup: deletes all ignored/untracked files (images, caches).
# firmware-cache/ is hard to redownload - back it up first:
docker compose down -v
cp -r firmware-cache ~/firmware-cache-backup
git clean -xnd    # preview what gets deleted
git clean -xfd
cp -r ~/firmware-cache-backup/. firmware-cache/
```
