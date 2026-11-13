#!/bin/bash
# Export transfer-ready SD-card artifacts to a remote host or this checkout.
# Usage: docker compose exec fbdebian tools/docker-export.sh <user@host[:remote-path]> [remote-directory]
#        tools/docker-export.sh --local
set -e

if [ "${1:-}" = --local ]; then
    [ "$#" -eq 1 ] || { echo "Usage: $0 --local" >&2; exit 1; }
    ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
    mkdir -p "$ROOT/artifacts"
    cd "$ROOT"
    docker compose cp fbdebian:/flexbuild/artifacts/sdcard.wic.gz artifacts/
    docker compose cp fbdebian:/flexbuild/artifacts/sdcard.wic.bmap artifacts/
    exit 0
fi

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ] || [ -z "$1" ]; then
    echo "Usage: $0 <user@host[:remote-path]> [remote-directory] | --local" >&2
    exit 1
fi

DEST=$1
if [[ "$DEST" == *:* ]]; then
    if [ "$#" -eq 2 ]; then
        echo "ERROR: specify the remote path in the destination or as the second argument, not both" >&2
        exit 1
    fi
    TARGET=$DEST
else
    TARGET="$DEST:${2:-"~"}"
fi
ARTIFACTS_DIR=/flexbuild/artifacts

for file in sdcard.wic.gz sdcard.wic.bmap; do
    if [ ! -f "$ARTIFACTS_DIR/$file" ]; then
        echo "ERROR: missing $ARTIFACTS_DIR/$file - run tools/docker-sdcard.sh first" >&2
        exit 1
    fi
done

scp "$ARTIFACTS_DIR/sdcard.wic.gz" "$ARTIFACTS_DIR/sdcard.wic.bmap" "$TARGET"
