#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 <user@host>" >&2
    exit 1
}

case ${1:-} in
    --uart|--hints)
        [ "$#" -eq 2 ] || usage
        MODE=$1
        DEST=$2
        ;;
    *)
        [ "$#" -eq 1 ] && [ -n "$1" ] || usage
        MODE=
        DEST=$1
        ;;
esac

for cmd in tmux ssh; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: required command not found: $cmd" >&2
        exit 1
    fi
done

if [ "$MODE" = --uart ]; then
    exec ssh -t "$DEST" 'sudo fuser -v /dev/ttyUSB0 || true
sudo fuser -k /dev/ttyUSB0 || true
exec sudo "$HOME/.local/bin/tio" \
 -b 115200 -t -l "nxp-boot-$(date +%Y%m%d-%H%M%S).log" \
 /dev/ttyUSB0'
fi

if [ "$MODE" = --hints ]; then
    exec ssh -t "$DEST" '
cat <<'"'"'HINTS'"'"'
Flashing checklist:

1. Reset the board on this host:
   echo b > /dev/ttyACM0;echo B > /dev/ttyACM0
2. Left pane: interrupt U-Boot and run:  ums 0 mmc 2:0
3. Identify the SD card:  lsblk -p -o NAME,SIZE,MODEL,TRAN
   Unmount any mounted SD-card partitions.
4. Flash the whole disk (replace sdb if needed):
   sudo "$HOME/.local/bin/bmaptool" copy ~/sdcard.wic.gz /dev/sdb
5. Left pane: press Ctrl-C, then run: reset

Clear the tio screen with Ctrl-t, then l.
Exit tio with Ctrl-t, then q.
HINTS
exec "${SHELL:-/bin/sh}" -l'
fi

SCRIPT_PATH=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")
SESSION=tmux-flash-$$
printf -v UART_CMD 'bash %q --uart %q' "$SCRIPT_PATH" "$DEST"
printf -v HINTS_CMD 'bash %q --hints %q' "$SCRIPT_PATH" "$DEST"

tmux new-session -d -s "$SESSION"
tmux split-window -h -t "$SESSION:0"
tmux send-keys -t "$SESSION:0.0" "$UART_CMD" C-m
tmux send-keys -t "$SESSION:0.1" "$HINTS_CMD" C-m
tmux select-pane -t "$SESSION:0.0"
exec tmux attach-session -t "$SESSION"
