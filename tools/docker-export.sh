#!/bin/bash
# Export transfer-ready SD-card artifacts directly to a remote host.
# Usage: docker compose exec fbdebian tools/docker-export.sh <user@host[:remote-path]> [remote-directory]
set -e

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ] || [ -z "$1" ]; then
    echo "Usage: $0 <user@host[:remote-path]> [remote-directory]" >&2
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
