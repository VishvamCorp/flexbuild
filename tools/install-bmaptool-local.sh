#!/bin/sh
set -eu

for cmd in curl dpkg-deb mktemp; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: required command not found: $cmd" >&2
        exit 1
    fi
done

if [ ! -x /usr/bin/python3 ]; then
    echo "ERROR: /usr/bin/python3 is required" >&2
    exit 1
fi

INSTALL_DIR="$HOME/.local/share/bmap-tools"
BIN_DIR="$HOME/.local/bin"
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

curl -fSL https://deb.debian.org/debian/pool/main/b/bmap-tools/bmap-tools_3.6-2_all.deb \
    -o "$WORKDIR/bmap-tools.deb"
curl -fSL https://deb.debian.org/debian/pool/main/s/six/python3-six_1.16.0-4_all.deb \
    -o "$WORKDIR/python3-six.deb"

mkdir -p "$INSTALL_DIR" "$BIN_DIR"
dpkg-deb -x "$WORKDIR/bmap-tools.deb" "$INSTALL_DIR"
dpkg-deb -x "$WORKDIR/python3-six.deb" "$INSTALL_DIR"

cat > "$BIN_DIR/bmaptool" <<EOF
#!/bin/sh
PYTHONPATH="$INSTALL_DIR/usr/lib/python3/dist-packages\${PYTHONPATH:+:\$PYTHONPATH}"
export PYTHONPATH
exec /usr/bin/python3 "$INSTALL_DIR/usr/bin/bmaptool" "\$@"
EOF
chmod +x "$BIN_DIR/bmaptool"

PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
if ! grep -Fqx "$PATH_LINE" "$HOME/.bashrc" 2>/dev/null; then
    printf '%s\n' "$PATH_LINE" >> "$HOME/.bashrc"
fi

"$BIN_DIR/bmaptool" --version
printf '\nInstalled: %s\n' "$BIN_DIR/bmaptool"
printf 'Run: source ~/.bashrc\n'
