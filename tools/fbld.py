#!/usr/bin/env python3
"""
fbld - progress wrapper for noisy build tools (flexbuild-aware).

Runs a command under a pseudo-terminal, collapses its output into a single
live status line (spinner + current stage + elapsed + last line), and streams
the full, unmodified output to a timestamped log file. The on-screen view stays
clean; the log keeps everything for post-mortem.

Usage:
    fbld -- bld -m imx8mpcartzy
    fbld bld -m imx8mpcartzy
    LOG_LEVEL=0 fbld bld -m imx8mpcartzy      # recommended: full detail in log

Env:
    FBLD_LOGDIR   directory for log files (default: ./fb-logs)

Exit code mirrors the wrapped command.
"""

import os
import sys
import re
import pty
import select
import shutil
import struct
import fcntl
import termios
import time
import threading
from datetime import datetime

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# (pattern, label_fn) - order matters, first match wins; only a *changed*
# label starts a new stage. A label_fn of None marks the line as known noise:
# it is recognised but must NOT change the current stage (e.g. apt chatter that
# repeats inside every component build).
#
# Real flexbuild stage boundaries are the "<Verb> <name> ..." headers and the
# "[Done]" suffix - not the internals of each component's build tool.
STAGE_RULES = [
    (re.compile(r"^Building dependency tree"),               None),  # apt noise
    (re.compile(r"is already the newest version"),           None),  # apt noise
    (re.compile(r"^Building linux with"),                    lambda m: "build: linux"),
    (re.compile(r"^Building\s+(\S+)"),                        lambda m: f"build: {m.group(1)}"),
    (re.compile(r"^Generating initial rootfs"),              lambda m: "rootfs: debootstrap"),
    (re.compile(r"installing essential packages"),           lambda m: "rootfs: essential pkgs"),
    (re.compile(r"installing remaining packages"),           lambda m: "rootfs: apt install (slow)"),
    (re.compile(r"^Applying rootfs overlay"),                lambda m: "rootfs: overlay"),
    (re.compile(r"^Installing kernel headers into rootfs"),  lambda m: "rootfs: kernel headers"),
    (re.compile(r"^Installing kernel and dtb"),              lambda m: "install: kernel + dtb"),
    (re.compile(r"^Installing kernel modules"),              lambda m: "install: kernel modules"),
    (re.compile(r"^Installing distro boot script"),          lambda m: "bsp: boot script"),
    (re.compile(r"^Generating boot\.scr|\bboot\.scr\b"),     lambda m: "bsp: boot script"),
    (re.compile(r"flex-installer|mkwic|\.wic\b|Compressing"), lambda m: "image: packaging"),
]

ERROR_RE = re.compile(
    r"\bError\s+\d+\b|fatal error:|\*\*\*\s+\[|mmdebstrap failed|"
    r"returned an error code|Too many open files|No such file or directory \(2\)"
)
WARN_RE = re.compile(r"\bWARNING\b|\bwarning:")

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
)


def fmt_dur(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


class Renderer:
    def __init__(self, logfile, interactive: bool):
        self._log = logfile
        self._interactive = interactive
        self._lock = threading.Lock()
        self._stage = "starting"
        self._stage_start = time.monotonic()
        self._detail = ""
        self._spin = 0
        self._start = time.monotonic()
        self._done = []  # list of (label, duration)
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._interactive:
            self._thread = threading.Thread(target=self._tick, daemon=True)
            self._thread.start()

    def _tick(self):
        while not self._stop.is_set():
            with self._lock:
                self._render()
            time.sleep(0.12)

    def _status_text(self) -> str:
        self._spin = (self._spin + 1) % len(SPINNER)
        elapsed = fmt_dur(time.monotonic() - self._stage_start)
        head = f"{SPINNER[self._spin]} {BOLD}{self._stage}{RESET} {DIM}{elapsed}{RESET}"
        if not self._detail:
            return head
        width = shutil.get_terminal_size((100, 24)).columns
        plain_head = f"X {self._stage} {elapsed}  |  "
        budget = max(10, width - len(plain_head) - 1)
        detail = self._detail[:budget]
        return f"{head}  {DIM}|{RESET}  {detail}"

    def _render(self):
        if not self._interactive:
            return
        sys.stdout.write("\r\033[2K" + self._status_text())
        sys.stdout.flush()

    def _persist(self, line: str):
        """Print a line that survives above the live status line."""
        if self._interactive:
            sys.stdout.write("\r\033[2K" + line + "\n")
            self._render()
        else:
            sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def feed(self, raw: str):
        self._log.write(raw + "\n")
        line = ANSI_RE.sub("", raw).rstrip()
        if not line:
            return

        with self._lock:
            matched_noise = False
            for pattern, label_fn in STAGE_RULES:
                m = pattern.search(line)
                if m:
                    if label_fn is None:
                        matched_noise = True  # known noise: keep current stage
                        break
                    label = label_fn(m)
                    if label != self._stage:
                        self._finish_stage()
                        self._stage = label
                        self._stage_start = time.monotonic()
                        self._detail = ""
                    break

            if matched_noise:
                return

            if ERROR_RE.search(line):
                self._persist(f"{RED}✗ {line}{RESET}")
            elif WARN_RE.search(line):
                self._persist(f"{YELLOW}! {line}{RESET}")
            elif line.endswith("[Done]"):
                # flexbuild's explicit end-of-stage marker; show it but keep
                # timing tied to the running stage.
                self._detail = line
            else:
                self._detail = line

    def _finish_stage(self):
        if self._stage == "starting":
            return
        dur = time.monotonic() - self._stage_start
        self._done.append((self._stage, dur))
        self._persist(f"{GREEN}✓{RESET} {self._stage} {DIM}({fmt_dur(dur)}){RESET}")

    def finish(self, ok: bool, logpath: str):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        with self._lock:
            self._finish_stage()
            if self._interactive:
                sys.stdout.write("\r\033[2K")
            total = fmt_dur(time.monotonic() - self._start)
            mark = f"{GREEN}BUILD OK{RESET}" if ok else f"{RED}BUILD FAILED{RESET}"
            sys.stdout.write(f"\n{mark}  {DIM}total {total}{RESET}\n")
            if self._done:
                width = max(len(s) for s, _ in self._done)
                for label, dur in self._done:
                    sys.stdout.write(f"  {label.ljust(width)}  {DIM}{fmt_dur(dur)}{RESET}\n")
            sys.stdout.write(f"{DIM}log: {logpath}{RESET}\n")
            sys.stdout.flush()


def set_winsize(fd: int):
    try:
        cols, rows = shutil.get_terminal_size((100, 24))
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        sys.stderr.write("usage: fbld [--] <command> [args...]\n")
        return 2

    logdir = os.environ.get("FBLD_LOGDIR", "fb-logs")
    os.makedirs(logdir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    logpath = os.path.join(logdir, f"build-{stamp}.log")
    logfile = open(logpath, "w", buffering=1, encoding="utf-8", errors="replace")

    interactive = sys.stdout.isatty()
    renderer = Renderer(logfile, interactive)

    pid, master_fd = pty.fork()
    if pid == 0:
        try:
            os.execvp(args[0], args)
        except Exception as exc:
            sys.stderr.write(f"exec failed: {exc}\n")
        os._exit(127)

    set_winsize(master_fd)
    renderer.start()

    buf = b""
    try:
        while True:
            try:
                ready, _, _ = select.select([master_fd], [], [], 0.2)
            except InterruptedError:
                continue
            if master_fd in ready:
                try:
                    chunk = os.read(master_fd, 65536)
                except OSError:
                    chunk = b""  # PTY closed on child exit -> EIO
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    renderer.feed(raw.decode("utf-8", "replace"))
    finally:
        if buf:
            renderer.feed(buf.decode("utf-8", "replace"))

    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    renderer.finish(ok=(code == 0), logpath=logpath)
    logfile.close()
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.stderr.write("\ninterrupted\n")
        sys.exit(130)
