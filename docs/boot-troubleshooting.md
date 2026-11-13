# Board does not boot after flashing (runbook)

The image comes from the README quick guide ("Cartzy Usage").

Seen twice on imx8mpcartzy: right after re-flashing, the board
crash-looped (U-Boot -> `Starting kernel ...` -> instant reset). The
cause is unknown: the same image booted fine before and after, and one
loop cleared on its own. What worked in the field:

```bash
# 1. Console completely silent? Check that nothing else owns the UART,
#    then reconnect with tio on the Linux flashing host:
ssh -t <linux-host> 'sudo fuser -v /dev/ttyUSB0; exec sudo "$HOME/.local/bin/tio" /dev/ttyUSB0'
#
# 2. Still crash-looping? Boot the no-M7 fallback by hand - it reached
#    login on a looping board. Interrupt autoboot first: press Enter
#    repeatedly during the "Hit any key" countdown:
setenv bootargs log_buf_len=2M systemd.unit=multi-user.target systemd.log_target=console earlycon clk_ignore_unused console=ttymxc1,115200 consoleblank=0 rootwait fixrtc systemd.gpt_auto=0 net.ifnames=0 root=/dev/mmcblk2p3 snd.slots=,snd-soc-imx-hdmi rw
load mmc 2:1 0x40800000 /Image
load mmc 2:1 0x48000000 /imx8mp-ezcart-v12-disp.dtb
booti 0x40800000 - 0x48000000
#    (raw /Image, not Image.gz: needs no kernel_comp_addr_r env vars)
#
# earlycon is in the default cmdline (2026-11-10), so kernel deaths are
# no longer silent: if a boot shows kernel output before the reset,
# capture the last lines - they name the failing subsystem.
#
# Manual-boot gotchas:
#  - clk_ignore_unused is REQUIRED: without it the kernel gates "unused"
#    clocks early and dies within seconds (display/camera pipelines).
#  - clk-imx8mp.mcore_booted was removed from boot.txt (2026-11-10): on
#    Cartzy the M7 starts from Linux (remoteproc), not from U-Boot, so
#    the flag described a state that never existed. Do not copy it back
#    into manual bootargs.
```
