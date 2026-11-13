#!/bin/sh
set -eu
# Install the host-side flashing tools under ~/.local - no root needed.
# Replaces the former install-bmaptool/tio/pyserial-local.sh trio; to add
# a tool, copy a stanza below. The layout is exactly what flash-auto.py
# and the tmux helpers expect:
#   ~/.local/bin/bmaptool                    (wrapper -> bmap-tools + six)
#   ~/.local/bin/tio                         (symlink)
#   ~/.local/bin/blkdiscard                  (wrapper -> util-linux + libblkid1)
#   ~/.local/share/pyserial/.../dist-packages (imported by flash-auto.py)

BIN_DIR="$HOME/.local/bin"
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

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

PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
if ! grep -Fqx "$PATH_LINE" "$HOME/.bashrc" 2>/dev/null; then
    printf '%s\n' "$PATH_LINE" >> "$HOME/.bashrc"
fi

fetch() {  # fetch <url> <local-name>
    curl -fSL "$1" -o "$WORKDIR/$2"
}

# --- bmaptool: bmap-tools + python3-six with a PYTHONPATH wrapper -----
{
    INSTALL_DIR="$HOME/.local/share/bmap-tools"
    fetch https://deb.debian.org/debian/pool/main/b/bmap-tools/bmap-tools_3.6-2_all.deb \
        bmap-tools.deb
    fetch https://deb.debian.org/debian/pool/main/s/six/python3-six_1.16.0-4_all.deb \
        python3-six.deb
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
    "$BIN_DIR/bmaptool" --version >/dev/null && echo "ok: $BIN_DIR/bmaptool"
}

# --- tio: console client for --console and the manual tmux flows ------
{
    INSTALL_DIR="$HOME/.local/share/tio"
    fetch https://archive.debian.org/debian/pool/main/t/tio/tio_1.32-1_amd64.deb tio.deb
    mkdir -p "$INSTALL_DIR"
    dpkg-deb -x "$WORKDIR/tio.deb" "$INSTALL_DIR"
    ln -sf "$INSTALL_DIR/usr/bin/tio" "$BIN_DIR/tio"
    "$BIN_DIR/tio" --version >/dev/null && echo "ok: $BIN_DIR/tio"
}

# --- blkdiscard: wipe the card before a sparse copy (util-linux) ------
{
    INSTALL_DIR="$HOME/.local/share/util-linux"
    fetch https://archive.debian.org/debian/pool/main/u/util-linux/util-linux_2.36.1-8+deb11u2_amd64.deb \
        util-linux.deb
    fetch https://archive.debian.org/debian/pool/main/u/util-linux/libblkid1_2.36.1-8+deb11u2_amd64.deb \
        libblkid1.deb
    mkdir -p "$INSTALL_DIR" "$BIN_DIR"
    dpkg-deb -x "$WORKDIR/util-linux.deb" "$INSTALL_DIR"
    dpkg-deb -x "$WORKDIR/libblkid1.deb" "$INSTALL_DIR"
    cat > "$BIN_DIR/blkdiscard" <<EOF
#!/bin/sh
LD_LIBRARY_PATH="$INSTALL_DIR/usr/lib/x86_64-linux-gnu\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
export LD_LIBRARY_PATH
exec "$INSTALL_DIR/sbin/blkdiscard" "\$@"
EOF
    chmod +x "$BIN_DIR/blkdiscard"
    "$BIN_DIR/blkdiscard" --version >/dev/null && echo "ok: $BIN_DIR/blkdiscard"
}

# --- pyserial: flash-auto.py imports it from this exact tree ----------
{
    INSTALL_DIR="$HOME/.local/share/pyserial"
    fetch https://deb.debian.org/debian/pool/main/p/pyserial/python3-serial_3.5-2_all.deb \
        python3-serial.deb
    mkdir -p "$INSTALL_DIR"
    rm -rf "$INSTALL_DIR/usr"
    dpkg-deb -x "$WORKDIR/python3-serial.deb" "$INSTALL_DIR"
    PYTHONPATH="$INSTALL_DIR/usr/lib/python3/dist-packages" \
        /usr/bin/python3 -c 'import serial; print("ok: pyserial", serial.__version__)'
}

printf '\nInstalled under %s (tools/flash-auto.py finds everything automatically).\n' \
    "$HOME/.local"
printf 'Run: source ~/.bashrc   (adds ~/.local/bin to PATH)\n'
