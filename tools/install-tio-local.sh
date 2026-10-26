#!/bin/sh
set -eu

for cmd in curl dpkg-deb mktemp; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: required command not found: $cmd" >&2
        exit 1
    fi
done

INSTALL_DIR="$HOME/.local/share/tio"
BIN_DIR="$HOME/.local/bin"
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

curl -fSL https://archive.debian.org/debian/pool/main/t/tio/tio_1.32-1_amd64.deb \
    -o "$WORKDIR/tio.deb"

mkdir -p "$INSTALL_DIR" "$BIN_DIR"
dpkg-deb -x "$WORKDIR/tio.deb" "$INSTALL_DIR"
ln -sf "$INSTALL_DIR/usr/bin/tio" "$BIN_DIR/tio"

PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
if ! grep -Fqx "$PATH_LINE" "$HOME/.bashrc" 2>/dev/null; then
    printf '%s\n' "$PATH_LINE" >> "$HOME/.bashrc"
fi

"$BIN_DIR/tio" --version
printf '\nInstalled: %s\n' "$BIN_DIR/tio"
printf 'Run: source ~/.bashrc\n'
