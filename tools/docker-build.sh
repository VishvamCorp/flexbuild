#!/bin/bash
# Build flexbuild images (BSP + boot + rootfs) for a machine.
# Run inside fbdebian container: docker compose exec fbdebian tools/docker-build.sh [machine]
set -e

cd "$(dirname "$0")/.."
. setup.env
mkdir -p logs

# Persist full output (including TIMING lines) for post-run analysis.
if [ -z "${FB_TEE_ACTIVE:-}" ]; then
    export FB_TEE_ACTIVE=1
    exec > >(tee -a "$FBDIR/logs/docker-build.log") 2>&1
fi

# Never race the entrypoint's first-run setup: it touches .entrypoint-done
# as its last act (fresh container: a few minutes).
if [ ! -f /var/lib/cartzy/.entrypoint-done ]; then
    echo ">>> Waiting for container entrypoint to finish first-run setup ..."
    for i in $(seq 1 120); do
        [ -f /var/lib/cartzy/.entrypoint-done ] && break
        sleep 5
    done
    [ -f /var/lib/cartzy/.entrypoint-done ] || { echo "ERROR: entrypoint did not become ready in 10 min" >&2; exit 1; }
fi

# Parse the SDK config once for the flexbuild variables (repo lists etc.).
if [ ! -f "$FBDIR/configs/.sdk.cfg" ]; then
    "$FBDIR/tools/parse_yaml" "$FBDIR/configs/sdk.yml" > "$FBDIR/configs/.sdk.cfg"
    "$FBDIR/tools/parse_yaml" "$FBDIR/configs/ml.yml" >> "$FBDIR/configs/.sdk.cfg"
    chmod 666 "$FBDIR/configs/.sdk.cfg"
fi
. "$FBDIR/configs/.sdk.cfg"
CONFIGLIST=.sdk.cfg
export CONFIGLIST

# Bare git mirrors of cloned repos survive volume wipes and accelerate re-clones.
export GIT_REFERENCE_DIR="$PWD/firmware-cache/git-reference"
mkdir -p "$GIT_REFERENCE_DIR"

ensure_git_reference() {
    local name=$1 clone_dir=$2
    [ -z "${GIT_REFERENCE_DIR:-}" ] && return
    local ref="$GIT_REFERENCE_DIR/$name.git"
    [ -d "$ref" ] && return
    [ -d "$clone_dir/.git" ] || return
    # A mirror of a shallow clone is itself shallow, and git refuses a
    # shallow --reference; only mirror full clones.
    if [ "$(git -C "$clone_dir" rev-parse --is-shallow-repository 2>/dev/null)" = "true" ]; then
        echo ">>> git reference: skipping $name (shallow clone; mirror would be unusable)"
        return
    fi
    echo ">>> Creating git reference mirror: $name"
    git clone --bare "$clone_dir" "$ref" >/dev/null 2>&1 || true
}

MACHINE=${1:-imx8mpcartzy}
shift || true
ROOTFS_ONLY=0
if [ "$#" -gt 0 ]; then
    if [ "$#" -eq 1 ] && [ "$1" = --rootfs-only ]; then
        ROOTFS_ONLY=1
        shift
    else
        echo "Usage: $0 [machine] [--rootfs-only]" >&2
        exit 2
    fi
fi

tst() { echo "TIMING|$(date -u +%s)|$(date -u +%H:%M:%S)|$1|$2"; }

# Enable ccache for the cross + host compilers so rebuilds are fast.
export CCACHE_DIR=/flexbuild/build_lsdk2506/.ccache
export CCACHE_MAXSIZE=${CCACHE_MAXSIZE:-20G}
export CCACHE_COMPRESS=${CCACHE_COMPRESS:-1}
export CCACHE_NLEVELS=3
mkdir -p /opt/ccache-bin "$CCACHE_DIR"
ccache --max-size "$CCACHE_MAXSIZE" >/dev/null 2>&1 || true
for t in gcc g++ cc aarch64-linux-gnu-gcc aarch64-linux-gnu-g++ arm-linux-gnueabihf-gcc arm-linux-gnueabihf-g++; do
    [ -e "/opt/ccache-bin/$t" ] || ln -s /usr/bin/ccache "/opt/ccache-bin/$t"
done
export PATH=/opt/ccache-bin:$PATH

JOBS=${BUILD_JOBS:-$(nproc)}

# Multithreaded zstd at a moderate level: the default (15-19) is very
# CPU-heavy and the size difference is small for a build artifact.
export ZSTD_CLEVEL=${ZSTD_CLEVEL:-3}
export ZSTD_NBTHREADS=${ZSTD_NBTHREADS:-$JOBS}

# Avoid any interactive apt prompts that might slip through.
export DEBIAN_FRONTEND=noninteractive

# flexbuild skips re-bootstrapping if the rootfs dir merely exists, so drop
# stale half-bootstrapped dirs (no etc/buildinfo marker).
clean_stale_rootfs_dirs() {
    for d in components_lsdk2506/bookworm_*_arm64*; do
        [ -d "$d" ] || continue
        [ -f "$d/rootfs/etc/buildinfo" ] || { echo ">>> removing stale rootfs dir: $d"; rm -rf "$d"; }
    done
}

# Cartzy overlay (README step 2): the sibling checkout is mounted at
# /cartzy_system; boot/ and kernel/ come from the build, not the overlay.
export CARTZY_SYSTEM_PATH=${CARTZY_SYSTEM_PATH:-/cartzy_system}
export RFS_OVERLAY_DIR="$CARTZY_SYSTEM_PATH/imx8/os"
export RFS_OVERLAY_EXCLUDES="boot kernel"

# NXP's lgfiles CDN 403s whole networks; a local copy under firmware-cache/
# (host dir, survives volume wipes) replaces the download — see its README.
if [ -z "${FIRMWARE_IMX_LOCAL:-}" ] && [ -d firmware-cache ]; then
    fwbin=$(ls firmware-cache/firmware-imx-*.bin 2>/dev/null | head -1)
    if [ -n "$fwbin" ]; then
        export FIRMWARE_IMX_LOCAL="$PWD/$fwbin"
        echo ">>> firmware-imx: using the local copy $(basename "$fwbin")"
    fi
fi

# Pre-extract the firmware-imx installer once (otherwise the self-extractor
# runs on every build). The extracted tree is cached in firmware-cache/.
if [ -n "${FIRMWARE_IMX_LOCAL:-}" ] && [ -f "$FIRMWARE_IMX_LOCAL" ]; then
    fwextract="firmware-cache/firmware-imx"
    if [ ! -d "$fwextract" ]; then
        echo ">>> firmware-imx: extracting $(basename "$FIRMWARE_IMX_LOCAL") ..."
        # Remove stale extracted trees only — the glob must NOT match the
        # firmware-imx-*.bin installer itself.
        find firmware-cache -maxdepth 1 -type d -name 'firmware-imx-*' -exec rm -rf {} +
        fwname=$(basename "$FIRMWARE_IMX_LOCAL")
        (
            cd firmware-cache
            chmod +x "$fwname"
            if ! "./$fwname" --auto-accept; then
                echo ">>> WARNING: firmware-imx self-extractor failed" >&2
                exit 1
            fi
        ) || true
        extracted=$(find firmware-cache -maxdepth 1 -type d -name 'firmware-imx-*' | head -1)
        if [ -n "$extracted" ]; then
            mv "$extracted" "$fwextract"
            echo ">>> firmware-imx: extracted to $fwextract"
        else
            echo ">>> WARNING: firmware-imx extraction did not produce a firmware-imx-* directory; the build will try to self-extract" >&2
        fi
    fi
    if [ -d "$fwextract" ]; then
        export FIRMWARE_IMX_EXTRACTED="$PWD/$fwextract"
        echo ">>> firmware-imx: using pre-extracted tree $fwextract"
    fi
fi

[ -d "$RFS_OVERLAY_DIR" ] || { echo "ERROR: Cartzy overlay not found: $RFS_OVERLAY_DIR" >&2; exit 1; }

# The auto build fetches repos lazily during bspall/apps; download them
# up-front in parallel so network waits overlap the CPU-bound build steps.
# A repo counts as fetched only with a usable checkout of the configured
# branch: 'bld repo-fetch' reports success for any existing dir, even a
# broken clone with an empty tree (seen on a cold run with uboot).
repo_fetched_ok() {
    local repo=$1 dir="components_lsdk2506/bsp/$repo" branch
    [ -d "$dir/.git" ] || return 1
    git -C "$dir" rev-parse --verify HEAD >/dev/null 2>&1 || return 1
    eval "branch=\${repo_${repo}_branch:-}"
    [ -z "$branch" ] && return 0
    [ "$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null)" = "$branch" ]
}

prefetch_bsp_repos() {
    local pids=() repo marker
    for repo in uboot atf imx_mkimage; do
        marker="components_lsdk2506/bsp/.${repo}.fetchdone"
        [ -f "$marker" ] && continue
        if repo_fetched_ok "$repo"; then
            touch "$marker"
            ensure_git_reference "$repo" "components_lsdk2506/bsp/$repo"
            continue
        fi
        rm -rf "components_lsdk2506/bsp/$repo"
        (
            set +e
            rc=1
            for i in 1 2 3; do
                echo ">>> Pre-fetching $repo repo (attempt $i/3) ..."
                # Clone from a clean slate: a failed attempt leaves a broken
                # dir, and 'bld repo-fetch' skips the clone for any existing
                # dir (then fails the checkout on the leftovers).
                rm -rf "components_lsdk2506/bsp/$repo"
                bld repo-fetch "$repo"
                rc=$?
                [ $rc -eq 0 ] && repo_fetched_ok "$repo" && break
                rc=1
                [ "$i" != 3 ] && sleep $((5 * i))
            done
            if [ $rc -eq 0 ]; then
                touch "$marker"
                ensure_git_reference "$repo" "components_lsdk2506/bsp/$repo"
            else
                # Never leave a broken clone for the auto build to trip over.
                rm -rf "components_lsdk2506/bsp/$repo"
            fi
        ) &
        pids+=($!)
    done
    for pid in "${pids[@]}"; do wait "$pid" || true; done
}

# The kernel repo is a multi-GB clone and the most fragile step on a shaky
# network: fetch it up-front with retries, moving aside broken dirs (an
# existing dir would make flexbuild skip the clone on the next attempt).
# Kernel fetch, BSP prefetch and host-dep are independent and run as three
# concurrent background jobs; only the post-wait checks gate the build.

# Host deps are baked into the fbdebian image, so claim the flexbuild
# host-dep/proxy/repo markers up front: without .deppkgdonefbdeb EVERY bld
# invocation (each parallel repo fetch included) re-runs 'apt-get update',
# and the concurrent apt runs lock each other out. The host-dep job below
# still validates for real and aborts the build on genuine failure.
touch "$FBDIR/logs/.checkproxydone" "$FBDIR/logs/.repodone" "$FBDIR/logs/.deppkgdonefbdeb"

tst prefetch_all start
tst kernel_fetch start
KERNEL_REPO_DIR=components_lsdk2506/linux/linux
(
    set +e
    # mv moves aside a broken clone; on a cold volume the dir does not
    # exist and mv must not abort the subshell. A dir with .git but no
    # usable checkout is a broken clone, not a fetched repo.
    if [ ! -d "$KERNEL_REPO_DIR/.git" ] || ! git -C "$KERNEL_REPO_DIR" rev-parse --verify HEAD >/dev/null 2>&1; then
        mv "$KERNEL_REPO_DIR" "/tmp/linux.broken.$(date +%s)" 2>/dev/null || true
        for i in 1 2 3 4 5; do
            echo ">>> Fetching kernel repo (attempt $i/5) ..."
            bld repo-fetch linux
            { [ -d "$KERNEL_REPO_DIR/.git" ] && git -C "$KERNEL_REPO_DIR" rev-parse --verify HEAD >/dev/null 2>&1; } && break
            mv "$KERNEL_REPO_DIR" "/tmp/linux.fail.$i" 2>/dev/null || true
            sleep $((5 * i))
        done
    fi
    # Propagate failure so the wait below can report it.
    { [ -d "$KERNEL_REPO_DIR/.git" ] && git -C "$KERNEL_REPO_DIR" rev-parse --verify HEAD >/dev/null 2>&1; } || exit 1
) &
kernel_pid=$!
tst kernel_fetch launched

tst bsp_prefetch start
prefetch_bsp_repos &
bsp_pid=$!

tst host_dep start
(
    set +e
    bld host-dep || exit 1
) &
host_pid=$!

wait "$kernel_pid" || { echo "ERROR: kernel repo fetch failed repeatedly" >&2; exit 1; }
[ -d "$KERNEL_REPO_DIR/.git" ] || { echo "ERROR: kernel repo fetch failed repeatedly" >&2; exit 1; }
ensure_git_reference linux "$KERNEL_REPO_DIR"
tst kernel_fetch done
wait "$bsp_pid" || true
tst bsp_prefetch done
# A repo that failed all prefetch attempts is not fatal (flexbuild falls
# back to a lazy fetch during bspall/apps), but say so loudly.
for repo in uboot atf imx_mkimage; do
    [ -f "components_lsdk2506/bsp/.${repo}.fetchdone" ] || \
        echo ">>> WARNING: $repo repo was not prefetched; it will be fetched lazily during the build" >&2
done
wait "$host_pid" || { echo "ERROR: bld host-dep failed" >&2; exit 1; }
tst host_dep done
tst prefetch_all done

# App-group membership changed (ML/robotics off, dpdk/tsntool LS-gated):
# drop the accumulated apps output; build caches survive, so it's cheap.
if [ ! -f "$FBDIR/logs/.appgroups_v2" ]; then
    echo ">>> app groups changed; purging stale apps output"
    rm -rf build_lsdk2506/apps
    rm -rf build_lsdk2506/rfs
    rm -f build_lsdk2506/images/rootfs_lsdk2506_debian_cartzy_arm64*
    touch "$FBDIR/logs/.appgroups_v2"
fi

echo ">>> Building images for machine: $MACHINE (overlay: $RFS_OVERLAY_DIR)"

run_build() {
    if [ "$ROOTFS_ONLY" = 1 ]; then
        echo ">>> Using rootfs-only pipeline"
        bld rfs -m "$MACHINE" && bld merge-apps -m "$MACHINE" && bld packrfs -m "$MACHINE"
    elif [ "${FB_PARALLEL_BUILD:-1}" = 1 ]; then
        echo ">>> Using parallel CPU/rootfs pipeline"
        bld auto_build_parallel -m "$MACHINE" -j"$JOBS" "$@"
    else
        echo ">>> Using sequential auto build"
        bld -m "$MACHINE" -j"$JOBS" "$@"
    fi
}

tst bld_auto start
# flexbuild returns 0 even when a sub-step fails: grep the attempt output
# for hard-failure signatures to abort early instead of burning the whole
# pipeline before the fresh-artifact check notices.
BUILD_FAIL_RE='make: \*\*\* .*Error [1-9]|Error: Command .* failed|ERROR: .*failed'
for attempt in 1 2 3; do
    echo ">>> Build attempt $attempt/3"
    # A failed attempt leaves a half-populated bootstrap dir behind; drop
    # it so the next attempt really re-bootstraps.
    clean_stale_rootfs_dirs
    marker=$(mktemp)
    attempt_log=$(mktemp)
    run_build "$@" 2>&1 | tee "$attempt_log" || true
    # Completion = a FRESH rootfs artifact from THIS attempt, not a stale one.
    if find build_lsdk2506/images -maxdepth 1 -name 'rootfs_*_arm64.tar.zst' -newer "$marker" 2>/dev/null | grep -q .; then
        echo ">>> Build completed (fresh rootfs artifact produced)"
        rm -f "$marker" "$attempt_log"; break
    fi
    if grep -qE "$BUILD_FAIL_RE" "$attempt_log"; then
        echo ">>> Attempt $attempt FAILED (build error detected in output); not waiting for the full pipeline" >&2
        grep -E "$BUILD_FAIL_RE" "$attempt_log" | head -5 >&2
        rm -f "$marker" "$attempt_log"
        if [ "$attempt" = 3 ]; then echo "ERROR: build failed after 3 attempts" >&2; exit 1; fi
        sleep $((10 * attempt))
        continue
    fi
    rm -f "$marker" "$attempt_log"
    if [ "$attempt" = 3 ]; then echo "ERROR: build failed after 3 attempts (no fresh rootfs artifact)" >&2; exit 1; fi
    echo ">>> Attempt $attempt incomplete (no fresh rootfs artifact); retrying in $((10 * attempt))s"
    sleep $((10 * attempt))
done
tst bld_auto done

if command -v ccache >/dev/null 2>&1; then
    echo ">>> ccache stats:"
    ccache -s | tail -n +2
fi
