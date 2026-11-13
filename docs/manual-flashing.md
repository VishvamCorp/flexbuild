# Manual flashing (optional)

Automatic path: `tools/flash-auto.sh` (README, "Cartzy Usage").
This is the manual tmux + bmaptool flow.

```bash
# Left pane: tio console. Right pane: the steps below.
# First reboot the board in tio (left side) the flash-auto way: send a
# break (Ctrl-t, then b), then press b - a Magic SysRq hard reboot while
# Linux is up. Console silent? Press the board's reset button /
# power-cycle it. No SysRq reaction? Log in (root/root) and run: reboot
# In tio: clear = Ctrl-t then l, exit = Ctrl-t then q.
# Left side: press any key to stop autoboot, then run:
ums 0 mmc 2:0
# Right side: find the SD card and unmount its partitions:
lsblk -p -o NAME,SIZE,MODEL,TRAN
# Wipe the card first: a bmap-guided copy skips zero blocks, and a used
# card keeps stale data there - it corrupts the new image (random
# segfaults, dpkg -V checksum mismatches):
if sudo "$HOME/.local/bin/blkdiscard" -f /dev/sdb; then
    sudo "$HOME/.local/bin/bmaptool" copy --bmap ~/sdcard.wic.bmap ~/sdcard.wic.gz /dev/sdb
else
    # --nobmap is required: bmaptool would auto-discover the adjacent
    # .bmap and silently go sparse on the used card.
    sudo "$HOME/.local/bin/bmaptool" copy --nobmap ~/sdcard.wic.gz /dev/sdb
fi
# Left side: press Ctrl-C, then run: reset

# First boot on the UART console (115200 baud): the root filesystem
# grows (one automatic reboot), then waits. Log in as root (empty
# password) or cartzy/cartzy. Give it network - plug in Ethernet (DHCP),
# or (only for images built without board.env):
sudo "$HOME/.local/bin/tio" -b 115200 -t \
    -l "nxp-boot-$(date +%Y%m%d-%H%M%S).log" \
    /dev/ttyUSB0
nmcli radio wifi on
nmcli dev wifi connect "SSID" password "PASS" ifname wlan0
# How to reach the board (hostname gets a random suffix at first boot):
hostname; ip -4 addr
```
