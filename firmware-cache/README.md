# firmware-cache - offline mirror for blocked downloads

NXP's `lgfiles` CDN (`www.nxp.com/lgfiles/NMG/MAD/YOCTO/...`) returns
**403 for whole networks**. The BSP build needs this installer from there:

    firmware-imx-8.26-d4c33ab.bin     (~2 MB, self-extracting installer)
    https://www.nxp.com/lgfiles/NMG/MAD/YOCTO/firmware-imx-8.26-d4c33ab.bin

If the build fails with "firmware-imx download failed (empty or missing
file)":

1. download the file once from any unblocked network (phone tethering,
   home, a colleague),
2. put it here unchanged as `firmware-imx-8.26-d4c33ab.bin`,
3. re-run `tools/docker-build.sh` - it finds the copy automatically
   (`FIRMWARE_IMX_LOCAL`, used by `src/bsp/imx_firmware.mk`).

The directory survives `docker volume rm`. But the .bin is git-ignored:
`git clean -xfd` deletes it - just repeat steps 1-2. A permanent team fix:
upload the installer to a GitHub release (like `VishvamCorp/libimxdmabuffer`)
and point `repo_firmware_imx_bin_url` in `configs/sdk.yml` there.
