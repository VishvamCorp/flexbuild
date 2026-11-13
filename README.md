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
Build the `imx8mpcartzy` image and flash it to an SD card.
Run all commands from the `flexbuild` directory.

### Quick guide
Prepare once:
```bash
# Optional: pre-download the IMX firmware (NXP CDN blocks some networks):
curl -fSL --retry 3 -o ~/firmware-imx-8.26-d4c33ab.bin https://www.nxp.com/lgfiles/NMG/MAD/YOCTO/firmware-imx-8.26-d4c33ab.bin
curl -fSL --retry 3 -o ~/imx-dsp-2.1.8.bin https://www.nxp.com/lgfiles/NMG/MAD/YOCTO/imx-dsp-2.1.8.bin
cp ~/firmware-imx-8.26-d4c33ab.bin ~/imx-dsp-2.1.8.bin firmware-cache/

# Board config:
cp board.env.example board.env   # then edit:
# WIFI_SSID=MyNetwork
# WIFI_PASS=MyPassword
# SSH_PUBKEY=ssh-keys/imx8.pub   # optional

# SSH key for the board:
mkdir -p ssh-keys ~/.ssh
[ -f ~/.ssh/imx8 ] || ssh-keygen -t ed25519 -f ~/.ssh/imx8 -N ""
cp ~/.ssh/imx8.pub ssh-keys/     # the build sees only the repo, not ~/.ssh
cat >> ~/.ssh/config <<'EOF'

# imx8 board
Host imx8
  HostName 172.16.100.54        # board IP - shown after flash-auto.sh
  User root
  IdentityFile ~/.ssh/imx8
  StrictHostKeyChecking accept-new
EOF

# Linux flashing host (the board is attached to it); replace <linux-host>
# with your SSH alias or user@host. In VirtualBox: set the USB 3.0 (xHCI)
# controller, add USB filters for UART (1a86:7523) and UMS (3016:0001),
# restart the VM.
scp tools/install-local-deps.sh <linux-host>:~/
ssh <linux-host> "sh ~/install-local-deps.sh"
# Optional: passwordless sudo for automatic flashing:
ssh -t <linux-host> 'echo "$(id -un) ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/99-nopasswd >/dev/null && sudo chmod 440 /etc/sudoers.d/99-nopasswd'
```

Build and flash:
```bash
cd flexbuild
# 1. Start the build container (host deps install on the first run):
docker compose up -d --build
# 2. Build the image: BSP + kernel + rootfs with Docker and i.MX libs
#    (cold build ~50 min):
docker compose exec fbdebian tools/docker-build.sh
# 3. Make the SD-card image (.gz + .bmap) in /flexbuild/artifacts:
docker compose exec fbdebian tools/docker-sdcard.sh
# 4. Flash the card (8 GB minimum; a bigger card is used in full).
#    Export the image to the Linux host; if the SSH alias is not visible
#    inside the container, use user@IP:
docker compose exec fbdebian tools/docker-export.sh user@<linux-host>:~/
#    Automatic flashing from the workstation:
tools/flash-auto.sh --remote <linux-host> --uart /dev/ttyUSB0
#    Or manual mode (tmux with hints):
tools/tmux-flash-env.sh <linux-host>
# 5. Done: flash-auto.sh prints the board IP. Set it in ~/.ssh/config
#    (Host imx8), then:
ssh imx8
# Flashing and boot logs are saved locally:
ls -lh ./logs
```

### Further docs
- Board does not boot: [boot-troubleshooting.md](docs/boot-troubleshooting.md)
- Manual flashing (tmux + bmaptool): [manual-flashing.md](docs/manual-flashing.md)
- Board setup on the target (deploy user, NPU/camera checks): `cartzy_system` repo, `SETUP_BOARD.md`
- Flashing control boards (camera / motor modules): `cartzy_system` repo, `FLASHING_BOARDS.md`
- Docker on the board and worktree cleanup: [build_and_deploy_distro.md](docs/build_and_deploy_distro.md)

## Flexbuild Usage
------------------

```console
$ cd flexbuild
$ docker compose up -d --build
$ docker compose exec fbdebian bash
$ . setup.env                   # inside the container (the entrypoint already ran it once)

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

1. [flexbuild_usage](docs/flexbuild_usage.md)
1. [build_and_deploy_distro](docs/build_and_deploy_distro.md)
1. [nxp_linux_sdk](docs/nxp_linux_sdk.md) for detailed information.
1. [Debian Linux SDK User's Guide](https://docs.nxp.com/bundle/UG10155).
