# firmware-cache — offline mirror for blocked downloads

NXP's `lgfiles` CDN (`www.nxp.com/lgfiles/NMG/MAD/YOCTO/...`) returns **403 for
whole networks** (observed: every path blocked from one office IP, browser and
wget alike). The BSP build needs one installer from there:

    firmware-imx-8.26-d4c33ab.bin     (~2 MB, self-extracting installer)
    https://www.nxp.com/lgfiles/NMG/MAD/YOCTO/firmware-imx-8.26-d4c33ab.bin

If the build machine cannot reach it (the build then fails with
"firmware-imx download failed (empty or missing file)"):

1. download the file once from any network that is not blocked
   (phone tethering, home, a colleague),
2. put it here unchanged, as `firmware-imx-8.26-d4c33ab.bin`,
3. re-run `tools/docker-build.sh` — `src/bsp/imx_firmware.mk` picks the
   copy up automatically (via `FIRMWARE_IMX_LOCAL`, exported by
   `tools/docker-build.sh`).

This directory lives in the repo, so it survives `docker volume rm`.
NOTE: the .bin is git-ignored, so `git clean -xfd` DOES delete it — restore
step 1-2 above if that happens (the failure signature is "firmware-imx
download failed (empty or missing file)"). For a permanent team fix,
upload the installer to a GitHub release (like `VishvamCorp/libimxdmabuffer`
already does) and point `repo_firmware_imx_bin_url` in `configs/sdk.yml` there.
