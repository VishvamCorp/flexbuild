#!/bin/bash
# Startup script for fbdebian compose service. Sources setup.env, installs host deps on first run.
cd /flexbuild || exit 1
mkdir -p logs
. setup.env

# flex-builder would normally add this on first run, but it's guarded by a marker in
# the bind-mounted logs/ dir that persists across container restarts. Add it
# unconditionally here to eliminate `sudo: unable to resolve host fbdebian` noise on
# every sudo invocation during the build.
grep -q '^127\.0\.0\.1[[:space:]]*fbdebian' /etc/hosts 2>/dev/null || \
    echo '127.0.0.1   fbdebian' >> /etc/hosts

# Make apt resilient: retry transient CDN connect failures (seen under heavy parallel
# downloads) and force IPv4 (IPv6 is unusable in some Docker Desktop setups).
# If apt-cacher-ng is running (compose service `apt-cache`, port 3142 by default),
# route apt through it. Probe without -f because apt-cacher-ng returns 4xx on "/".
APTCACHE_PORT=${APT_CACHER_NG_PORT:-3142}
APTCACHE=${APT_CACHER_NG:-http://127.0.0.1:$APTCACHE_PORT}
if curl -sS -o /dev/null --max-time 3 "$APTCACHE" 2>/dev/null; then
    echo ">>> Using apt-cacher-ng proxy: $APTCACHE"
    cat > /etc/apt/apt.conf.d/99flexbuild-net.conf <<EOF
Acquire::Retries "10";
Acquire::ForceIPv4 "true";
Acquire::http::Timeout "60";
Acquire::http::Proxy "$APTCACHE";
Acquire::https::Proxy "$APTCACHE";
EOF
else
    cat > /etc/apt/apt.conf.d/99flexbuild-net.conf <<'EOF'
Acquire::Retries "10";
Acquire::ForceIPv4 "true";
Acquire::http::Timeout "60";
EOF
fi

# Make git clones abort quickly on a stalled connection (instead of hanging forever),
# so fetch failures surface fast and can be retried.
git config --global http.lowSpeedLimit 1000
git config --global http.lowSpeedTime 60

# Register qemu-user binfmt handlers so mmdebstrap/bdebstrap can build the arm64 rootfs
# on an x86 host (executes arm64 binaries transparently inside the chroot).
mountpoint -q /proc/sys/fs/binfmt_misc || mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc 2>/dev/null
update-binfmts --enable qemu-aarch64 2>/dev/null || true

if [ -f /var/lib/cartzy/.host-deps-installed ] || dpkg -s meson >/dev/null 2>&1; then
    echo ">>> Host dependencies already installed"
else
    echo ">>> Installing host-dependent packages (bld host-dep) ..."
    bld host-dep || echo ">>> WARNING: 'bld host-dep' failed - re-run it inside the container, or 'docker compose restart fbdebian'"
fi

# The Cartzy C++ packages (NeoProcessor -> CPPCartzyCapture / CPPEventProcessor) require
# cmake >= 3.28, but Debian bookworm ships 3.25. Install the same cmake version the
# arm64 build container uses (Ubuntu 24.04 -> cmake 3.28.3) so the cross-build matches.
if ! cmake --version 2>/dev/null | head -1 | grep -qE 'cmake version 3\.28\.'; then
    echo ">>> Installing cmake 3.28.3 (bookworm ships 3.25, the packages need >= 3.28) ..."
    pip3 install -q --break-system-packages "cmake==3.28.3" || \
        echo ">>> WARNING: cmake >= 3.28 is not available - the cross-build of the Cartzy packages will fail"
fi

# Readiness handshake: docker-build.sh waits for this marker so it never races
# the first-run setup above (apt config, binfmt) — /var/lib/cartzy lives in the
# container fs, so the marker exists only after this entrypoint has completed.
touch /var/lib/cartzy/.entrypoint-done

exec "${@:-bash}"
