#!/usr/bin/env bash
# Flash on a Linux host, either directly or over SSH.
#
# Usage:
#   tools/flash-auto.sh --remote <linux-host> --uart /dev/ttyUSB0
#   tools/flash-auto.sh -i ~/sdcard.wic.gz       # on the Linux host itself
#
# Remote runs copy flash-auto.py to the host and fetch the console log into
# logs/. They reset the board through its CDC interface when one is present.
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PY_SCRIPT="$SCRIPT_DIR/flash-auto.py"

if [ "${1:-}" = "--remote" ]; then
    DEST=${2:?"--remote needs a destination, e.g. <linux-host>"}
    shift 2
    for cmd in ssh scp; do
        command -v "$cmd" >/dev/null 2>&1 \
            || { echo "ERROR: required command not found: $cmd" >&2; exit 1; }
    done
    export MSYS2_ARG_CONV_EXCL='*'
    SCP_SRC=$PY_SCRIPT
    command -v cygpath >/dev/null 2>&1 && SCP_SRC=$(cygpath -m "$PY_SCRIPT")
    scp -q "$SCP_SRC" "$DEST:flash-auto.py"

    RUN_OUT=$(mktemp)
    trap 'rm -f "$RUN_OUT"' EXIT
    RC=0
    ssh -t "$DEST" python3 flash-auto.py "$@" 2>&1 | tee "$RUN_OUT" || RC=$?
    REMOTE_LOG=$(sed -n 's/^console log: //p' "$RUN_OUT" | head -1 | tr -d '\r')
    if [ -n "$REMOTE_LOG" ]; then
        LOGS_DIR="$SCRIPT_DIR/../logs"
        mkdir -p "$LOGS_DIR"
        if scp -q "$DEST:$REMOTE_LOG" "$LOGS_DIR/"; then
            echo "log fetched: $LOGS_DIR/$(basename "$REMOTE_LOG")"
        else
            echo "WARNING: could not fetch $REMOTE_LOG from $DEST" >&2
        fi
    fi
    exit "$RC"
fi

[ "$(uname -s)" = Linux ] \
    || { echo "ERROR: local flashing requires Linux; use --remote HOST" >&2; exit 1; }
exec python3 "$PY_SCRIPT" "$@"
