#!/usr/bin/env python3
"""flash-auto: flash the board's SD card over the console with no typing.

Drives the whole flashing dialog over the board's UART: reboot the board
(in-band if it runs Linux; a physical reset is requested only when the
console stays silent), interrupt U-Boot, expose the card with `ums`,
flash it with bmaptool on the host, `reset`, then watch the boot through
to the login prompt. Every run logs both directions of the console to
logs/nxp-boot-<timestamp>.log.

Design: docs/superpowers/specs/2026-11-03-flash-auto-design.md
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime


class ConsoleTimeout(Exception):
    """Raised when wait_for() hits its deadline. Carries what and how long."""

    def __init__(self, names, waited):
        self.names = list(names)
        self.waited = waited
        super().__init__(
            "timed out after %.1fs waiting for: %s" % (waited, ", ".join(self.names))
        )


class Console:
    """Expect-style driver over a pyserial-compatible port.

    All bytes read are normalized into a capped tail buffer that wait_for()
    matches against, and echoed to the log file; everything sent is logged
    with a '>>> ' prefix.
    """

    BUFFER_CAP = 64 * 1024
    READ_SIZE = 4096
    IDLE_SLEEP = 0.02

    def __init__(self, port, log_path):
        self.port = port
        self._buffer = ""
        self.recent = ""
        self.last_rx = time.monotonic()
        self._log = open(log_path, "a", encoding="utf-8", errors="replace",
                         newline="")

    def drain(self):
        self.port.reset_input_buffer()
        self._buffer = ""

    def send(self, text):
        self.port.write(text.encode())
        self._log.write(">>> %s" % text)
        self._log.flush()

    def send_break(self, duration=0.3):
        self.port.sendBreak(duration)
        self._log.write(">>> <BREAK>")
        self._log.flush()

    def close(self):
        self._log.close()
        self.port.close()

    def _absorb(self, data):
        text = data.decode("utf-8", "replace")
        self._log.write(text)
        self._log.flush()
        self.last_rx = time.monotonic()
        self._buffer += normalize(text)
        if len(self._buffer) > self.BUFFER_CAP:
            self._buffer = self._buffer[-self.BUFFER_CAP:]
        lines = [l for l in self._buffer[-200:].split("\n") if l.strip()]
        if lines:
            self.recent = lines[-1].strip()

    def wait_for(self, names, timeout):
        """Wait until one of PATTERNS[names] appears; consume through it.

        Consuming the match keeps already-handled markers from re-matching
        on the next call (expect semantics).
        """
        deadline = time.monotonic() + timeout
        while True:
            for name in names:
                m = PATTERNS[name].search(self._buffer)
                if m:
                    self._buffer = self._buffer[m.end():]
                    return name, m.group(0)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ConsoleTimeout(names, timeout)
            data = self.port.read(self.READ_SIZE)
            if data:
                self._absorb(data)
            else:
                time.sleep(self.IDLE_SLEEP)


# Console markers, verbatim from real nxp-boot-*.log captures. The console is
# carriage-return-heavy; matching always runs against normalize()d text.
PATTERNS = {
    "autoboot": re.compile(r"Hit any key to stop autoboot"),
    "prompt": re.compile(r"(?:^|\n)=> "),
    "ums_start": re.compile(r"UMS: LUN 0"),
    "kernel_start": re.compile(r"Starting kernel \.\.\."),
    "board_ip": re.compile(
        r"cartzy-board-ip: (\S+) ((?:\d{1,3}\.){3}\d{1,3})"),
    "login": re.compile(r" login:"),
    "panic": re.compile(r"Kernel panic|not syncing"),
    "aborted": re.compile(r"CTRL\+C - Operation aborted"),
    "spl": re.compile(r"U-Boot SPL"),
    "password_prompt": re.compile(r"Password: "),
    "shell_prompt": re.compile(r"root@[^:\n]+:~# "),
    # ums' endless spinner: single /-\| chars, one per line (each spinner
    # char ends with \r -> \n after normalize). 12+ in a row cannot appear
    # in kernel boot spew or getty output - every real line is longer.
    "ums_spinner": re.compile(r"(?:[/\\|\-]\n){12,}"),
}


def normalize(text):
    """Make raw console text matchable: \r becomes \n, backspaces dropped."""
    return text.replace("\r", "\n").replace("\x08", "")


MISSED_INTERRUPT_MSG = "interrupt missed - press reset now"

SILENT_RESET_MSG = (
    "console is silent - power the board on / press reset now")

INBAND_FAILED_MSG = (
    "in-band reboot failed - the board is likely still in Linux; "
    "press reset (or power-cycle it) and re-run")

# seconds of total console silence before a single probe newline surfaces
# an idle prompt/getty whose banner was drained at open
PROBE_AFTER = 3.0


def phase_power_wait(console, timeout, reboot_inband=True,
                     ask_after_probes=5):
    """Wait for power-on/reset until the U-Boot prompt is reachable.

    Interrupts autoboot when the countdown appears; accepts an already
    present prompt; aborts a leftover ums (a board parked in ums by an
    earlier failed run matches no boot marker - its spinner is detected
    and Ctrl-C'd); on a missed interrupt (kernel starting) says so and
    keeps waiting for the operator to press reset, within one deadline.

    reboot_inband: when the board is in Linux instead (kernel started or
    a login prompt is up) and nobody is around to press reset, reboot it
    over this console first (phase_reboot_inband) - once; after that (or
    when disabled) fall back to the manual "press reset" behavior.

    A fully silent console gets one newline probe every PROBE_AFTER
    seconds (surfaces an idle prompt/getty whose banner was drained at
    open). When ask_after_probes consecutive probes draw no bytes at
    all, the board is likely powered off: the physical reset request is
    printed once - the ONLY case that still needs a human hand.
    """
    deadline = time.monotonic() + timeout
    attempted = False
    silent_probes = 0
    probe_pending = False
    asked = False
    while True:
        remaining = deadline - time.monotonic()
        try:
            name, _ = console.wait_for(
                ["autoboot", "prompt", "kernel_start", "login",
                 "ums_spinner"],
                min(remaining, PROBE_AFTER))
            silent_probes = 0
            probe_pending = False
        except ConsoleTimeout:
            if remaining <= PROBE_AFTER:
                raise
            # count only windows that FOLLOW a sent probe: the first
            # silent window precedes any probe, and a probe that drew
            # bytes (non-matching chatter) means the board is alive
            if probe_pending and console._buffer == "":
                silent_probes += 1
            else:
                silent_probes = 0
            probe_pending = True
            if silent_probes >= ask_after_probes and not asked:
                print(SILENT_RESET_MSG, flush=True)
                asked = True
            console.send("\n")
            continue
        if name == "autoboot":
            console.send("\r")
            console.wait_for(["prompt"], 15)
            return
        if name == "prompt":
            return
        if name == "ums_spinner":
            print("      aborting a leftover ums (previous run left the "
                  "board exposing its card)", flush=True)
            console.send("\x03")
            console.wait_for(["prompt"], 15)
            return
        # kernel_start / login: the board is in Linux
        if reboot_inband and not attempted:
            attempted = True
            try:
                phase_reboot_inband(console, budget=deadline, trigger=name)
            except ConsoleTimeout:
                print(INBAND_FAILED_MSG, flush=True)
                raise
            continue
        # status message, not a question.
        print(MISSED_INTERRUPT_MSG, flush=True)


def phase_ums(console, timeout=30.0):
    """Expose the board's card over USB: ums 0 mmc 2:0."""
    console.send("ums 0 mmc 2:0\r")
    console.wait_for(["ums_start"], timeout)


def phase_reboot_inband(console, sysrq_wait=10.0, login_wait=60.0,
                        budget=None, trigger=None):
    """Reboot a board that is running Linux, over the console it owns.

    Primary: Magic SysRq - a BREAK followed by 'b' reboots the kernel the
    moment its serial console is up (validated on imx8mpcartzy 2026-11-10;
    BREAK works through the CH340 adapter). Hard reset, no sync: the card
    is about to be re-flashed anyway.
    Fallback (no SysRq reaction): log in as root and run reboot. The
    password is the image's (uEnv.txt: root_password=root). When the
    trigger was the login prompt itself, its bytes were already consumed,
    and getty now holds 'b' as a half-typed username: one deliberate
    Enter flushes it and getty reprints the prompt.
    No \\r spam here - it wedges getty; only clean pattern waits.

    budget: an absolute time.monotonic() deadline the internal waits are
    clamped to (the caller's phase deadline). trigger: the pattern name
    that led here ("login" or "kernel_start").

    Returns "sysrq" or "login".
    """
    def wait(names, t):
        if budget is not None:
            t = min(t, max(budget - time.monotonic(), 0.1))
        return console.wait_for(names, t)

    console.send_break()
    console.send("b")
    try:
        wait(["spl", "kernel_start"], sysrq_wait)
        return "sysrq"
    except ConsoleTimeout:
        pass
    if trigger == "login":
        console.send("\r")  # flush the 'b' getty holds as a username
    wait(["login"], login_wait)
    console.send("root\r")
    wait(["password_prompt"], login_wait)
    console.send("root\r")
    wait(["shell_prompt"], login_wait)
    console.send("reboot\r")
    return "login"


RETRY_CONTRACT = "board left in ums mode - inspect, press reset, re-run"

WIPE_FALLBACK_MSG = (
    "WARNING: blkdiscard failed on %s - falling back to a full "
    "(non-sparse) copy; the flash will take longer")

POST_FLASH_CRASHLOOP_NOTE = (
    "      NOTE: twice now the board crash-looped after re-flashing; the cause\n"
    "      is not understood (one loop cleared on its own). If it happens,\n"
    "      docs/boot-troubleshooting.md has the field-proven steps:\n"
    "      console check, no-M7 fallback boot")


class FlashFailure(Exception):
    pass


def _wipe_target(device, run=subprocess.run, blkdiscard="blkdiscard"):
    """Discard the whole target so a sparse copy cannot leave stale data.

    Returns True when a discard succeeded. util-linux < 2.36 has no -f flag;
    there blkdiscard asks no questions either, so retry without it before
    giving up (the caller then falls back to a full copy).
    """
    for argv in ([blkdiscard, "-f", device], [blkdiscard, device]):
        try:
            proc = run(argv)
        except OSError:
            return False
        if proc.returncode == 0:
            return True
    return False


def phase_flash(image, bmap, device, bmaptool, run=subprocess.run,
                blkdiscard="blkdiscard"):
    """Unmount the target's partitions, wipe it, then bmaptool-copy the image.

    A bmap-guided copy skips the image's zero blocks, so whatever the target
    holds at those offsets survives the flash. On a previously-used eMMC/SD
    that leaves stale data from the earlier image inside the new files (in
    their legitimate zero padding), which breaks them - observed in the field
    as mass dpkg -V checksum mismatches and segfaulting binaries. Wipe the
    target first; if the discard is unsupported, fall back to a full copy
    (--nobmap) that writes the zeros too.

    bmaptool's output is inherited so progress streams live. On failure the
    board is NOT reset: it stays in ums mode so the exposed disk can be
    inspected; the retry is: inspect, press reset, re-run this script.
    """
    run("umount %s?*" % device, shell=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if bmap is not None and not _wipe_target(device, run, blkdiscard=blkdiscard):
        print(WIPE_FALLBACK_MSG % device, flush=True)
        bmap = None  # full copy writes the zeros; correct on dirty media
    argv = [bmaptool, "copy"]
    if bmap is not None:
        argv += ["--bmap", bmap]
    else:
        # --nobmap (one dash pair, as spelled by bmap-tools) skips bmap
        # discovery: without it bmaptool auto-finds <image>.bmap next to
        # the image and goes sparse again, undoing the full-copy fallback.
        argv += ["--nobmap"]
    argv += [image, device]
    proc = run(argv)
    if proc.returncode != 0:
        print(RETRY_CONTRACT, flush=True)
        raise FlashFailure(
            "bmaptool exited %d writing %s" % (proc.returncode, device))


def phase_reset(console, timeout=30.0):
    """Leave ums (Ctrl-C) and reboot the board."""
    console.send("\x03")
    console.wait_for(["prompt"], timeout)
    console.send("reset\r")



class BootFailure(Exception):
    pass


def phase_boot_validate(console, timeout, kernel_grace=120.0,
                        silence_window=60.0, watch_slice=1.0):
    """Watch-only validation: never writes, never interrupts the boot.

    Expects the kernel to start within kernel_grace, then the login prompt
    within timeout, tolerating intermediate reboots (rootfs grow). Fails on
    kernel panic, overall timeout, or silence_window seconds without input.

    Returns the board's IP announcement if it lands BEFORE the login
    prompt (a fast interface can beat getty); wait_for consumes matched
    bytes, so a later phase_board_ip() would never see it otherwise.
    """
    try:
        console.wait_for(["kernel_start"], kernel_grace)
    except ConsoleTimeout as exc:
        raise BootFailure("kernel never started: %s" % exc)
    board_ip = None
    deadline = time.monotonic() + timeout
    while True:
        if time.monotonic() >= deadline:
            raise BootFailure(
                "login prompt not reached within %.0fs" % timeout)
        try:
            name, matched = console.wait_for(
                ["panic", "board_ip", "login"], watch_slice)
        except ConsoleTimeout:
            if time.monotonic() - console.last_rx >= silence_window:
                raise BootFailure(
                    "console silent for %.0fs while waiting for login"
                    % silence_window)
            continue
        if name == "panic":
            raise BootFailure("kernel panic detected")
        if name == "board_ip":
            m = PATTERNS["board_ip"].search(matched)
            if board_ip is None:
                board_ip = (m.group(1), m.group(2))
            continue
        return board_ip  # login prompt reached


def phase_board_ip(console, timeout):
    """Wait for the board's own IP announcement; None if it never comes.

    The image's NM dispatcher prints "cartzy-board-ip: <iface> <ip>" to
    the console when an interface gets an address; missing marker means
    an older image or no board.env build - never a failure.
    """
    try:
        _, matched = console.wait_for(["board_ip"], timeout)
    except ConsoleTimeout:
        return None
    m = PATTERNS["board_ip"].search(matched)
    return m.group(1), m.group(2)


class DiskSelectionError(Exception):
    pass



_SIZE_RE = re.compile(r"^([\d.,]+)\s*([KMGT]?)(?:i?B)?$", re.IGNORECASE)
_SIZE_MULT = {"": 1, "K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4}


def _parse_lsblk_size(token):
    m = _SIZE_RE.match(token.strip())
    if not m:
        raise DiskSelectionError(
            "cannot parse lsblk SIZE column: %r" % token)
    number = float(m.group(1).replace(",", "."))
    return int(number * _SIZE_MULT[m.group(2).upper()])


def parse_lsblk(text):
    """Parse `lsblk -Jdpno NAME,SIZE,TRAN,TYPE,MODEL` output into dicts.

    JSON, not columnar text: loop devices have an empty TRAN, and a
    whitespace split collapses that empty middle column (hosts with snap
    loops crashed on it). JSON nulls become empty strings here.
    """
    disks = []
    for dev in json.loads(text).get("blockdevices", []):
        disks.append({
            "name": dev["name"],
            "size_bytes": _parse_lsblk_size(dev["size"]),
            "tran": dev.get("tran") or "",
            "type": dev["type"],
            "model": dev.get("model") or "",
        })
    return disks


def image_size_from_bmap(bmap_path):
    """Total image size in bytes from the bmap's <ImageSize> element."""
    for elem in ET.parse(bmap_path).getroot().iter("ImageSize"):
        return int(elem.text.strip())
    raise DiskSelectionError("no <ImageSize> in %s" % bmap_path)


def choose_target(disks, image_bytes, explicit):
    """Pick the one safe whole-disk target; refuse anything ambiguous.

    An explicit device is the operator's decision and only has to be a whole
    disk. Otherwise: exactly one USB disk at least as large as the image.
    """
    if explicit is not None:
        for d in disks:
            if d["name"] == explicit:
                if d["type"] != "disk":
                    raise DiskSelectionError(
                        "%s is a partition, not a whole disk - "
                        "pass the whole device, e.g. /dev/sdb" % explicit)
                return explicit
        raise DiskSelectionError(
            "explicit device %s not found among: %s"
            % (explicit, ", ".join(d["name"] for d in disks)))

    candidates = [
        d for d in disks
        if d["tran"] == "usb" and d["type"] == "disk"
        and (image_bytes is None or d["size_bytes"] >= image_bytes)
    ]
    listing = ", ".join(
        "%s (%s, %.1fG)" % (d["name"], d["model"], d["size_bytes"] / 1e9)
        for d in disks if d["tran"] == "usb" and d["type"] == "disk")
    if len(candidates) > 1:
        raise DiskSelectionError(
            "several USB disks qualify - pass --device: %s" % listing)
    if not candidates:
        detail = "no USB disk is at least the image size (%s bytes)" \
            % image_bytes if image_bytes else "no USB disk found"
        raise DiskSelectionError(
            "%s; USB disks seen: %s" % (detail, listing or "(none)"))
    return candidates[0]["name"]


# ------------------------------------------------------------- preflight

class PreflightError(Exception):
    pass




def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _log_dir():
    repo_logs = os.path.join(_repo_root(), "logs")
    if os.path.isdir(repo_logs) and os.access(repo_logs, os.W_OK):
        return repo_logs
    return os.path.expanduser("~")


def _chown_to_sudo_user(path):
    """Best effort: hand a root-written artifact to the invoking user.

    The sudo re-exec runs everything as root, so the console log would
    be root-owned and undeletable for the user afterwards; root keeps
    writing to the same inode regardless of ownership.
    """
    sudo_user = os.environ.get("SUDO_USER")
    if not sudo_user:
        return
    try:
        import pwd
        pw = pwd.getpwnam(sudo_user)
        os.chown(path, pw.pw_uid, pw.pw_gid)
    except (KeyError, OSError):
        pass  # best effort - a run must not fail over log ownership


def find_image(explicit, repo_root):
    """Image lookup order: -i PATH, artifacts/sdcard.wic.gz, ~/sdcard.wic.gz."""
    candidates = [explicit] if explicit else [
        os.path.join(repo_root, "artifacts", "sdcard.wic.gz"),
        os.path.join(os.path.expanduser("~"), "sdcard.wic.gz"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    hint = "copy the image to ~/sdcard.wic.gz or pass -i PATH"
    if explicit:
        raise PreflightError("image %s not found - %s" % (explicit, hint))
    raise PreflightError(
        "no image found (artifacts/sdcard.wic.gz, ~/sdcard.wic.gz) - %s"
        % hint)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="flash-auto",
        description="Flash the board's SD card over the console: interrupt "
                    "U-Boot, ums, bmaptool, reset, validate boot. "
                    "The operator only presses the board's reset button.")
    parser.add_argument("-i", "--image", help="image to flash "
                        "(default: artifacts/sdcard.wic.gz, then ~/sdcard.wic.gz)")
    parser.add_argument("-b", "--bmap", help="matching .bmap "
                        "(default: <image>.bmap when present)")
    parser.add_argument("-d", "--device", help="target whole disk, e.g. /dev/sdb "
                        "(default: auto-detect the ums gadget)")
    parser.add_argument("-u", "--uart", default="/dev/ttyUSB0",
                        help="serial device (default: %(default)s)")
    parser.add_argument("--baud", type=int, default=115200,
                        help="console baud rate (default: %(default)s)")
    parser.add_argument("--reset-dev",
                        help="CDC reset device on remote hosts "
                             "(default: first /dev/ttyACM*)")
    parser.add_argument("--bmaptool-path", help=argparse.SUPPRESS)
    parser.add_argument("--status", action="store_true",
                        help="print device/image state and exit")
    parser.add_argument("--console", action="store_true",
                        help="exec tio on the console after success")
    parser.add_argument("--timeout-power", type=int, default=120,
                        help="seconds to wait for power-on/U-Boot (default: %(default)s)")
    parser.add_argument("--timeout-boot", type=int, default=300,
                        help="seconds to wait for the login prompt (default: %(default)s)")
    parser.add_argument("--timeout-ip", type=int, default=90,
                        help="seconds to wait for the board's IP announcement"
                             " (default: %(default)s; 0 skips)")
    return parser


# ------------------------------------------------- host glue (subprocess)


def _lsblk_disks():
    proc = subprocess.run(
        ["lsblk", "-Jdpno", "NAME,SIZE,TRAN,TYPE,MODEL"],
        capture_output=True, text=True)
    return parse_lsblk(proc.stdout)



def _watch_new_disk(before_names, image_bytes, watch):
    """Wait for exactly one NEW usb whole-disk; fallback to choose_target.

    The gadget disk appears when ums starts. A new non-USB disk is ignored.
    """
    print("      waiting for the disk device")
    deadline = time.monotonic() + watch
    while time.monotonic() < deadline:
        new = [d for d in _lsblk_disks()
               if d["name"] not in before_names
               and d["type"] == "disk" and d["tran"] == "usb"]
        if len(new) == 1:
            disk = new[0]
            if image_bytes and disk["size_bytes"] < image_bytes:
                raise DiskSelectionError(
                    "gadget disk %s (%.1fG) is smaller than the image (%.1fG)"
                    % (disk["name"], disk["size_bytes"] / 1e9,
                       image_bytes / 1e9))
            return disk["name"]
        if len(new) > 1:
            raise DiskSelectionError(
                "several new disks appeared (%s) - pass --device"
                % ", ".join(d["name"] for d in new))
        time.sleep(min(2.0, max(0.05, watch / 4)))
    # Attached but no new disk: fall through to the same safety rules
    # (handles a leftover gadget attached before this run).
    return choose_target(_lsblk_disks(), image_bytes, None)


def default_acquire_disk(args, image_bytes, before_disks=None, watch=120.0):
    """Return the UMS whole-disk, waiting for a new local USB disk."""
    if args.device:
        return choose_target(_lsblk_disks(), image_bytes, args.device)
    disks = before_disks if before_disks is not None else _lsblk_disks()
    before = {d["name"] for d in disks}
    return _watch_new_disk(before, image_bytes, watch)


def _prepare_uart(args):
    """Verify the native Linux console device before opening it."""
    if os.path.exists(args.uart):
        if shutil.which("fuser"):
            subprocess.run(["fuser", "-k", args.uart],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        return True
    print("FAIL: %s not present on this host - pass --uart /dev/ttyUSBx"
          % args.uart)
    return False




def _reexec_forwarded_args(args, image, bmap, bmaptool):
    """Argv tail for the sudo re-exec: user paths resolved to absolute,
    every operator flag carried over (--reset-dev included)."""
    forwarded = ["-i", os.path.abspath(image),
                 "-u", args.uart, "--baud", str(args.baud)]
    if bmap:
        forwarded += ["-b", os.path.abspath(bmap)]
    if bmaptool:
        forwarded += ["--bmaptool-path", bmaptool]
    if args.reset_dev:
        forwarded += ["--reset-dev", args.reset_dev]
    if args.device:
        forwarded += ["-d", args.device]
    if args.console:
        forwarded += ["--console"]
    forwarded += ["--timeout-power", str(args.timeout_power),
                  "--timeout-boot", str(args.timeout_boot),
                  "--timeout-ip", str(args.timeout_ip)]
    return forwarded


def _maybe_sudo_reexec(args, image, bmap, bmaptool):
    """Real run only: serial and whole-disk writes need root; re-exec under
    sudo with user paths (image, bmap, bmaptool) resolved to absolute ones
    first, so root does not depend on the invoking user's HOME/PATH."""
    if not hasattr(os, "geteuid") or os.geteuid() == 0:
        return
    forwarded = _reexec_forwarded_args(args, image, bmap, bmaptool)
    print("flashing needs root (serial port + disk writes) - "
          "re-running under sudo")
    os.execvp("sudo",
              ["sudo", "-E", sys.executable,
               os.path.abspath(__file__)] + forwarded)


def _sudo_user_homes():
    """Homes where install-local-deps.sh may have installed tools for the
    invoking user: under sudo that is $SUDO_USER's home, not root's; the
    effective home comes last."""
    homes = []
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            import pwd
            homes.append(pwd.getpwnam(sudo_user).pw_dir)
        except (ImportError, KeyError):
            pass
    homes.append(os.path.expanduser("~"))
    return homes


def _user_pyserial_dirs():
    """Directories where install-local-deps.sh may have unpacked
    pyserial: the invoking user's ~/.local (under sudo that is $SUDO_USER,
    not root's home), then the effective home."""
    return [os.path.join(home, ".local", "share", "pyserial",
                         "usr", "lib", "python3", "dist-packages")
            for home in _sudo_user_homes()]


def _import_serial_from(dirs):
    """Import serial from one of the given dirs (first with serial/ wins)."""
    for path in dirs:
        if not os.path.isdir(os.path.join(path, "serial")):
            continue
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            import serial
            return serial
        except ImportError:
            continue
    return None


def _import_serial():
    try:
        import serial
        return serial
    except ImportError:
        pass
    module = _import_serial_from(_user_pyserial_dirs())
    if module is not None:
        return module
    raise PreflightError(
        "pyserial missing - run tools/install-local-deps.sh "
        "(no root needed) or sudo apt install python3-serial")


def _open_real_port(args):
    serial = _import_serial()
    return serial.Serial(port=args.uart, baudrate=args.baud, timeout=0.1)


def _print_status(args, image, bmap, bmaptool):
    print("image     : %s" % (image or "(not found)"))
    print("bmap      : %s" % (bmap or "(none)"))
    print("bmaptool  : %s" % (bmaptool or "(missing)"))
    print("uart      : %s %s" % (
        args.uart, "(present)" if os.path.exists(args.uart) else "(missing)"))
    print("baud      : %d" % args.baud)
    try:
        _import_serial()
        have = "yes"
    except PreflightError:
        have = "missing (run tools/install-local-deps.sh)"
    print("pyserial  : %s" % have)




def _remote_reset_board(reset_dev=None, pattern="/dev/ttyACM*"):
    """Reset the board over its CDC interface: write 'b' then 'B'
    (the remote-host equivalent of: echo b > /dev/ttyACM0; echo B > ...).

    Falls back to the human prompt when no CDC device exists.
    """
    device = reset_dev
    if device:
        if not os.path.exists(device):
            raise PreflightError("reset device %s not present" % device)
    else:
        matches = sorted(glob.glob(pattern))
        if not matches:
            print("no CDC reset device - power the board on / "
                  "press reset now", flush=True)
            return False
        device = matches[0]
    for letter in ("b", "B"):
        with open(device, "w") as f:
            f.write(letter + "\n")  # byte parity with: echo b > dev; echo B > dev
    print("board reset via %s (b/B)" % device, flush=True)
    return True


# ------------------------------------------------------------- main flow

def _default_bmap_for(image, explicit):
    if explicit:
        return explicit
    if not image:
        return None
    candidate = (image[:-3] + ".bmap") if image.endswith(".gz") \
        else image + ".bmap"
    return candidate if os.path.isfile(candidate) else None


def _find_bmaptool(which, explicit=None):
    if explicit:
        return explicit
    bmaptool = which("bmaptool") if which else None
    if not bmaptool:
        for home in _sudo_user_homes():
            local = os.path.join(home, ".local", "bin", "bmaptool")
            if os.path.isfile(local):
                bmaptool = local
                break
    return bmaptool


def _find_blkdiscard(which):
    """blkdiscard to use: PATH first, else the wrapper installed by
    tools/install-local-deps.sh (~/.local/bin, SUDO_USER-aware under
    sudo). None when neither exists."""
    found = which("blkdiscard")
    if found:
        return found
    for home in _sudo_user_homes():
        local = os.path.join(home, ".local", "bin", "blkdiscard")
        if os.path.isfile(local):
            return local
    return None


def main(argv=None, port_factory=None, run=subprocess.run,
         acquire_disk=None, reset_board=None, which=shutil.which):
    args = build_arg_parser().parse_args(argv)
    try:
        image = find_image(args.image, _repo_root())
    except PreflightError as exc:
        if not args.status:
            print("FAIL: %s" % exc, flush=True)
            return 2
        print("image     : not found (%s)" % exc, flush=True)
        image = None

    if args.status:
        _print_status(args, image, _default_bmap_for(image, args.bmap),
                      _find_bmaptool(which, args.bmaptool_path))
        return 0


    try:
        bmap = _default_bmap_for(image, args.bmap)
        image_bytes = image_size_from_bmap(bmap) if bmap else None
        bmaptool = _find_bmaptool(which, args.bmaptool_path)
        if not bmaptool:
            raise PreflightError(
                "bmaptool not found - run tools/install-local-deps.sh")
    except (PreflightError, DiskSelectionError) as exc:
        print("FAIL: %s" % exc, flush=True)
        return 2

    if port_factory is None:
        if not _prepare_uart(args):
            return 2
        _maybe_sudo_reexec(args, image, bmap, bmaptool)
        before_disks = _lsblk_disks()
        make_port = lambda: _open_real_port(args)
        acquire = (acquire_disk or
                   (lambda a, ib: default_acquire_disk(
                       a, ib, before_disks=before_disks)))
    else:
        make_port = port_factory
        acquire = acquire_disk or default_acquire_disk
    announce = reset_board or (lambda: _remote_reset_board(args.reset_dev))

    log_path = os.path.join(
        _log_dir(),
        "nxp-boot-%s.log" % datetime.now().strftime("%Y%m%d-%H%M%S"))
    console = None
    try:
        console = Console(make_port(), log_path)
        _chown_to_sudo_user(log_path)
        console.drain()  # drop stale bytes from before this run
        print("console log: %s" % log_path, flush=True)
        announce()
        print("[1/7] reaching the board (reboots it over this console; "
              "press reset only if it stays silent)", flush=True)
        phase_power_wait(console, args.timeout_power)
        print("[2/7] exposing the card: ums 0 mmc 2:0", flush=True)
        phase_ums(console)
        print("[3/7] waiting for the card on this host", flush=True)
        device = acquire(args, image_bytes)
        print("      target: %s" % device, flush=True)
        print("[4/7] flashing %s" % os.path.basename(image), flush=True)
        resolved_blkdiscard = _find_blkdiscard(which)
        if resolved_blkdiscard is None:
            print("blkdiscard not found - run tools/install-local-deps.sh "
                  "(continuing with a full copy)", flush=True)
        phase_flash(image, bmap, device, bmaptool, run=run,
                    blkdiscard=resolved_blkdiscard or "blkdiscard")
        print(POST_FLASH_CRASHLOOP_NOTE, flush=True)
        print("[5/7] resetting the board", flush=True)
        phase_reset(console)
        print("[6/7] validating boot", flush=True)
        board_ip = phase_boot_validate(console, args.timeout_boot)
        print("[7/7] waiting for the board's IP", flush=True)
        if board_ip is not None:
            print("      already announced during boot", flush=True)
        elif args.timeout_ip > 0:
            print("      waiting up to %ss" % args.timeout_ip, flush=True)
            board_ip = phase_board_ip(console, args.timeout_ip)
    except (PreflightError, DiskSelectionError, ConsoleTimeout,
            FlashFailure, BootFailure) as exc:
        print("FAIL: %s" % exc, flush=True)
        if log_path:
            print("log: %s" % log_path, flush=True)
        return 1
    finally:
        if console is not None:
            console.close()

    print("PASS: flashed %s to %s, booted to login"
          % (os.path.basename(image), device), flush=True)
    if board_ip:
        print("board ip : %s %s" % board_ip, flush=True)
    elif args.timeout_ip <= 0:
        print("board ip : skipped (--timeout-ip 0)", flush=True)
    else:
        print("board ip : no announcement (older image, no board.env,"
              " or wifi/dhcp failed - see the log)", flush=True)
    print("log: %s" % log_path, flush=True)
    if args.console:
        tio = which("tio") if which else None
        if not tio:
            local = os.path.join(os.path.expanduser("~"),
                                 ".local", "bin", "tio")
            tio = local if os.path.isfile(local) else None
        if tio:
            os.execvp(tio, [tio, "-b", str(args.baud), args.uart])
        print("--console given but tio not found; console stays on %s"
              % args.uart)
    return 0


if __name__ == "__main__":
    sys.exit(main())

