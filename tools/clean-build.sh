#!/bin/bash
# Reset the build environment for a clean start while preserving caches.
#
# Keeps:
#   - firmware-cache/ (local NXP firmware installer + extracted tree)
#   - git repository state
# Removes:
#   - Docker containers and named volumes (components, build, apt-cache)
#   - build artifacts in build_lsdk2506/images/ and artifacts/
#
# Usage:
#   tools/clean-build.sh
#   tools/clean-build.sh --full    # also remove firmware-cache

set -e

cd "$(dirname "$0")/.."

FULL=0
for arg in "$@"; do
    case "$arg" in
        --full) FULL=1 ;;
        -h|--help) awk 'NR > 1 && /^#/ { print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    esac
done

echo ">>> Stopping and removing containers + named volumes ..."
docker compose down -v || true

echo ">>> Removing build artifacts ..."
rm -rf build_lsdk2506/images/* artifacts/*

if [ "$FULL" = 1 ]; then
    echo ">>> Removing firmware-cache (full reset) ..."
    rm -rf firmware-cache
else
    echo ">>> Preserving firmware-cache/ (use --full to remove it too)"
fi

echo ">>> Rebuilding the container image ..."
docker compose up -d --build

echo ">>> Done. Start a fresh build with:"
echo "    docker compose exec fbdebian tools/docker-build.sh"
