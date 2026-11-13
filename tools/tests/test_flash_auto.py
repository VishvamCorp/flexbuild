"""Tests for tools/flash-auto.py (loaded via importlib: dashed filename)."""

import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "flash_auto",
    os.path.join(os.path.dirname(__file__), "..", "flash-auto.py"),
)
flash_auto = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(flash_auto)


class FakePort:
    """pyserial-compatible test double: scripted console-bound bytes."""

    def __init__(self, initial=b"", chunk_size=4096):
        self.queue = bytearray(initial)
        self.chunk_size = chunk_size
        self.writes = []
        self.breaks = []
        self.drained = False

    def feed(self, data):
        if isinstance(data, str):
            data = data.encode()
        self.queue += data

    def read(self, n):
        take = min(n, self.chunk_size, len(self.queue))
        data = bytes(self.queue[:take])
        del self.queue[:take]
        return data

    def write(self, data):
        self.writes.append(bytes(data))

    def sendBreak(self, duration=0.3):
        self.breaks.append(duration)

    def reset_input_buffer(self):
        self.queue.clear()
        self.drained = True

    def close(self):
        pass


class RespondingPort(FakePort):
    """FakePort that reacts to writes: on_write(data) feeds console bytes."""

    def __init__(self, initial=b"", on_write=None, **kwargs):
        super().__init__(initial=initial, **kwargs)
        self.on_write = on_write or (lambda data: None)

    def write(self, data):
        super().write(data)
        self.on_write(bytes(data))


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        fd, self.log_path = tempfile.mkstemp(suffix=".log")
        os.close(fd)

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)

    def _console(self, port):
        console = flash_auto.Console(port, self.log_path)
        self.addCleanup(console.close)
        return console

    def test_wait_for_matches_and_times_out(self):
        port = FakePort(initial=b"Hit any key to stop autoboot: 2")
        console = self._console(port)
        name, matched = console.wait_for(["autoboot"], 1)
        self.assertEqual(name, "autoboot")
        self.assertIn("Hit any key", matched)

        empty = self._console(FakePort())
        with self.assertRaises(flash_auto.ConsoleTimeout) as ctx:
            empty.wait_for(["autoboot", "prompt"], 0.2)
        self.assertIn("autoboot", str(ctx.exception.names))
        self.assertAlmostEqual(ctx.exception.waited, 0.2, delta=0.15)

    def test_send_break_calls_port_and_logs(self):
        port = FakePort()
        console = self._console(port)
        console.send_break(0.5)
        self.assertEqual(port.breaks, [0.5])
        with open(self.log_path, encoding="utf-8") as f:
            self.assertIn(">>> <BREAK>", f.read())

    def test_phase_board_ip_returns_iface_and_ip(self):
        port = FakePort(initial=b"\r\nsystemd[1]: Started ...\r\n"
                                b"cartzy-board-ip: wlan0 172.16.100.54\r\n")
        result = flash_auto.phase_board_ip(self._console(port), 1)
        self.assertEqual(result, ("wlan0", "172.16.100.54"))

    def test_phase_board_ip_timeout_returns_none(self):
        result = flash_auto.phase_board_ip(self._console(FakePort()), 0.2)
        self.assertIsNone(result)

    def test_boot_validate_stashes_early_board_ip(self):
        # the dispatcher can beat the login prompt (fast wired iface):
        # boot validation must stash the marker instead of consuming it
        port = FakePort(initial=b"Starting kernel ...\r\n"
                                b"cartzy-board-ip: wlan0 10.1.2.3\r\n"
                                b"imx8mpcartzy-x login: ")
        seen = flash_auto.phase_boot_validate(self._console(port), 5)
        self.assertEqual(seen, ("wlan0", "10.1.2.3"))

    def test_boot_validate_returns_none_without_marker(self):
        port = FakePort(initial=b"Starting kernel ...\r\n"
                                b"imx8mpcartzy-x login: ")
        seen = flash_auto.phase_boot_validate(self._console(port), 5)
        self.assertIsNone(seen)

    def test_fragmented_marker(self):
        port = FakePort(initial=b"Hit any key to stop autoboot", chunk_size=1)
        console = self._console(port)
        name, _ = console.wait_for(["autoboot"], 2)
        self.assertEqual(name, "autoboot")

    def test_buffer_cap(self):
        port = FakePort(initial=b"/-\\|" * 32 * 1024)  # 128 KiB of spinner
        port.feed(b"\n=> ")
        console = self._console(port)
        name, _ = console.wait_for(["prompt"], 2)
        self.assertEqual(name, "prompt")
        self.assertLessEqual(len(console._buffer), 64 * 1024)

    def test_send_logged(self):
        port = FakePort()
        console = self._console(port)
        console.send("ums 0 mmc 2:0\r")
        self.assertEqual(port.writes, [b"ums 0 mmc 2:0\r"])
        with open(self.log_path, "r", newline="") as f:
            self.assertIn(">>> ums 0 mmc 2:0\r", f.read())


class PhaseTests(unittest.TestCase):
    def setUp(self):
        fd, self.log_path = tempfile.mkstemp(suffix=".log")
        os.close(fd)
        self.addCleanup(os.unlink, self.log_path)

    def _console(self, port):
        console = flash_auto.Console(port, self.log_path)
        self.addCleanup(console.close)
        return console

    def test_power_wait_interrupts_autoboot(self):
        port = RespondingPort(
            initial=b"\r\nU-Boot 2020.04-00000-g00000000000\r\n"
                    b"Hit any key to stop autoboot:  2 \x08 1 \x08 0",
            on_write=lambda data: port.feed("\n=> ") if data == b"\r" else None,
        )
        console = self._console(port)
        flash_auto.phase_power_wait(console, 5)
        self.assertEqual(port.writes, [b"\r"])

    def test_power_wait_accepts_existing_prompt(self):
        port = FakePort(initial=b"\r\nU-Boot 2020.04 ...\r\n=> ")
        console = self._console(port)
        flash_auto.phase_power_wait(console, 2)
        self.assertEqual(port.writes, [])

    def test_power_wait_missed_interrupt_rearms(self):
        port = RespondingPort(
            initial=b"Starting kernel ...\r\n"
                    b"[    0.000000] Booting Linux on physical CPU\r\n"
                    b"imx8mpcartzy-jgcz login: root\r\n",
            on_write=lambda data: port.feed("\n=> ") if data == b"\r" else None,
        )
        # The operator presses reset only after the missed boot: feed the new
        # U-Boot banner + countdown 0.3 s into the wait.
        reset_press = threading.Timer(
            0.3,
            port.feed,
            args=(b"U-Boot 2020.04 ...\r\n"
                  b"Hit any key to stop autoboot:  2 \x08 1",))
        reset_press.start()
        self.addCleanup(reset_press.cancel)
        console = self._console(port)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            # reboot_inband=False: this test pins the MANUAL rearm path
            # (operator presses reset late); the in-band path has its own
            # PowerWaitInbandTests.
            flash_auto.phase_power_wait(console, 5, reboot_inband=False)
        self.assertIn("interrupt missed - press reset now", out.getvalue())
        self.assertEqual(port.writes, [b"\r"])

    def test_power_wait_timeout(self):
        console = self._console(FakePort())
        with self.assertRaises(flash_auto.ConsoleTimeout):
            flash_auto.phase_power_wait(console, 0.3)

    def test_power_wait_aborts_leftover_ums(self):
        # a board left in ums by an earlier failed run: its spinner matches
        # no boot marker, so the wait must recognize and abort it
        port = RespondingPort(
            initial=b"/\r-\r\\\r|\r/\r-\r\\\r|\r/\r-\r\\\r|\r/\r-\r\\\r|"
                    b"\r/\r-\r\\\r|\r/\r-\r\\\r|\r",
            on_write=lambda data: port.feed(
                b"CTRL+C - Operation aborted\r\n=> ")
            if data == b"\x03" else None)
        console = self._console(port)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            flash_auto.phase_power_wait(console, 5)
        self.assertEqual(port.writes, [b"\x03"])
        self.assertIn("leftover ums", out.getvalue())

    def test_power_wait_silence_asks_for_reset_once(self):
        # a dead-silent console (board off) is the one case that still
        # needs a human: ask exactly once, after a few unanswered probes
        port = FakePort()  # never answers
        console = self._console(port)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(flash_auto.ConsoleTimeout):
                # two full probe windows fit: ask fires after the first
                # probe comes back unanswered (ask_after_probes=1)
                flash_auto.phase_power_wait(
                    console, 8, ask_after_probes=1)
        self.assertEqual(out.getvalue().count("press reset now"), 1)

    def test_power_wait_chatter_never_asks(self):
        # non-matching console output keeps arriving: not a dead board,
        # no reset request
        port = RespondingPort(
            on_write=lambda data: port.feed(b"some console chatter\r\n")
            if data == b"\n" else None)
        console = self._console(port)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(flash_auto.ConsoleTimeout):
                # long enough for a probe round-trip: the board answers
                # the probe with (non-matching) chatter - it is alive,
                # so no reset request may appear
                flash_auto.phase_power_wait(
                    console, 8, ask_after_probes=1)
        self.assertNotIn("press reset now", out.getvalue())

    def test_ums_sends_and_waits(self):
        port = FakePort(
            initial=b"UMS: LUN 0, dev mmc 2, hwpart 0, sector 0x0, "
                    b"count 0x1d34000")
        console = self._console(port)
        flash_auto.phase_ums(console, timeout=2)
        self.assertEqual(port.writes, [b"ums 0 mmc 2:0\r"])

    def test_flash_invokes_umount_wipe_then_bmaptool(self):
        recorded = []

        def fake_run(argv, **kwargs):
            recorded.append(argv)
            return types.SimpleNamespace(returncode=0)

        flash_auto.phase_flash(
            image="/tmp/sdcard.wic.gz", bmap="/tmp/sdcard.wic.bmap",
            device="/dev/sdb", bmaptool="/home/u/.local/bin/bmaptool",
            run=fake_run)
        self.assertEqual(
            recorded[0], "umount /dev/sdb?*")
        self.assertEqual(
            recorded[1], ["blkdiscard", "-f", "/dev/sdb"])
        self.assertEqual(
            recorded[2],
            ["/home/u/.local/bin/bmaptool", "copy", "--bmap",
             "/tmp/sdcard.wic.bmap", "/tmp/sdcard.wic.gz", "/dev/sdb"])

        recorded.clear()
        flash_auto.phase_flash(
            image="/tmp/sdcard.wic.gz", bmap=None,
            device="/dev/sdb", bmaptool="bmaptool", run=fake_run)
        self.assertEqual(recorded, [
            "umount /dev/sdb?*",
            ["bmaptool", "copy", "--nobmap",
             "/tmp/sdcard.wic.gz", "/dev/sdb"]])

    def test_flash_wipe_failure_falls_back_to_full_copy(self):
        recorded = []

        def fake_run(argv, **kwargs):
            recorded.append(argv)
            code = 1 if isinstance(argv, list) and argv[:1] == ["blkdiscard"] else 0
            return types.SimpleNamespace(returncode=code)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            flash_auto.phase_flash(
                image="/tmp/sdcard.wic.gz", bmap="/tmp/sdcard.wic.bmap",
                device="/dev/sdb", bmaptool="bmaptool", run=fake_run)
        self.assertEqual(
            recorded[-1],
            ["bmaptool", "copy", "--nobmap",
             "/tmp/sdcard.wic.gz", "/dev/sdb"])
        self.assertIn("full (non-sparse) copy", out.getvalue())

    def test_flash_wipe_retries_without_force_flag(self):
        # util-linux < 2.36 has no -f; plain blkdiscard asks no questions
        # there, so the wipe must be retried without the flag.
        recorded = []

        def fake_run(argv, **kwargs):
            recorded.append(argv)
            if isinstance(argv, list) and argv == ["blkdiscard", "-f", "/dev/sdb"]:
                return types.SimpleNamespace(returncode=1)
            return types.SimpleNamespace(returncode=0)

        flash_auto.phase_flash(
            image="/tmp/sdcard.wic.gz", bmap="/tmp/sdcard.wic.bmap",
            device="/dev/sdb", bmaptool="bmaptool", run=fake_run)
        self.assertIn(["blkdiscard", "/dev/sdb"], recorded)
        self.assertEqual(
            recorded[-1],
            ["bmaptool", "copy", "--bmap", "/tmp/sdcard.wic.bmap",
             "/tmp/sdcard.wic.gz", "/dev/sdb"])

    def test_flash_wipe_missing_binary_falls_back_to_full_copy(self):
        recorded = []

        def fake_run(argv, **kwargs):
            recorded.append(argv)
            if isinstance(argv, list) and argv[:1] == ["blkdiscard"]:
                raise FileNotFoundError("blkdiscard")
            return types.SimpleNamespace(returncode=0)

        flash_auto.phase_flash(
            image="/tmp/sdcard.wic.gz", bmap="/tmp/sdcard.wic.bmap",
            device="/dev/sdb", bmaptool="bmaptool", run=fake_run)
        self.assertEqual(
            recorded[-1],
            ["bmaptool", "copy", "--nobmap",
             "/tmp/sdcard.wic.gz", "/dev/sdb"])

    def test_flash_failure_message_and_no_reset(self):
        def failing_run(argv, **kwargs):
            return types.SimpleNamespace(returncode=1)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(flash_auto.FlashFailure):
                flash_auto.phase_flash(
                    image="/tmp/sdcard.wic.gz", bmap=None,
                    device="/dev/sdb", bmaptool="bmaptool",
                    run=failing_run)
        self.assertIn(
            "board left in ums mode - inspect, press reset, re-run",
            out.getvalue())

    def test_reset_survives_spinner(self):
        port = RespondingPort(
            on_write=lambda data: port.feed(
                b"/-\\|" * 25 * 1024 +      # 100 KiB of ums spinner
                b"CTRL+C - Operation aborted\r\n=> ")
            if data == b"\x03" else None)
        console = self._console(port)
        flash_auto.phase_reset(console, timeout=5)
        self.assertEqual(port.writes, [b"\x03", b"reset\r"])

    def test_boot_ok_across_reboot(self):
        port = FakePort(initial=(
            b"U-Boot 2020.04 ...\r\n"
            b"Hit any key to stop autoboot:  2 \x08 1 \x08 0\r\n"
            b"7654 bytes read in 1 ms\r\n"
            b"Starting kernel ...\r\n"
            b"[    0.000000] Booting Linux on physical CPU\r\n"
            b"[    8.633821] EXT4-fs (mmcblk2p3): resized filesystem to 3613184\r\n"
            b"reboot: Restarting system\r\n"
            b"U-Boot 2020.04 ...\r\n"
            b"Hit any key to stop autoboot:  2 \x08 1 \x08 0\r\n"
            b"Starting kernel ...\r\n"
            b"[    1.234567] systemd[1]: Detected architecture arm64\r\n"
            b"imx8mpcartzy-hud7 login: "))
        console = self._console(port)
        flash_auto.phase_boot_validate(console, timeout=10)
        self.assertEqual(port.writes, [])

    def test_boot_panic_fails(self):
        port = FakePort(initial=(
            b"Starting kernel ...\r\n"
            b"[    1.000000] Kernel panic - not syncing: VFS\r\n"))
        console = self._console(port)
        with self.assertRaises(flash_auto.BootFailure):
            flash_auto.phase_boot_validate(console, timeout=5)
        self.assertEqual(port.writes, [])

    def test_boot_timeout_fails(self):
        port = FakePort(initial=b"Starting kernel ...\r\n")
        console = self._console(port)
        with self.assertRaises(flash_auto.BootFailure):
            flash_auto.phase_boot_validate(console, timeout=0.5)

    def test_boot_silence_fails(self):
        port = FakePort(initial=b"Starting kernel ...\r\n")
        console = self._console(port)
        with self.assertRaises(flash_auto.BootFailure):
            flash_auto.phase_boot_validate(console, timeout=30,
                                           silence_window=0.3)

    def test_flash_wipes_with_explicit_blkdiscard_path(self):
        recorded = []

        def fake_run(argv, **kwargs):
            recorded.append(argv)
            return types.SimpleNamespace(returncode=0)

        flash_auto.phase_flash(
            image="/tmp/i.gz", bmap="/tmp/i.bmap", device="/dev/sdb",
            bmaptool="bmaptool", run=fake_run,
            blkdiscard="/home/u/.local/bin/blkdiscard")
        self.assertEqual(recorded[1],
                         ["/home/u/.local/bin/blkdiscard", "-f", "/dev/sdb"])

    def test_wipe_explicit_path_retries_without_force_flag(self):
        recorded = []
        path = "/home/u/.local/bin/blkdiscard"

        def fake_run(argv, **kwargs):
            recorded.append(argv)
            if argv == [path, "-f", "/dev/sdb"]:
                return types.SimpleNamespace(returncode=1)
            return types.SimpleNamespace(returncode=0)

        self.assertTrue(flash_auto._wipe_target(
            "/dev/sdb", run=fake_run, blkdiscard=path))
        self.assertEqual(recorded, [[path, "-f", "/dev/sdb"], [path, "/dev/sdb"]])


# Real `lsblk -Jdpno NAME,SIZE,TRAN,TYPE,MODEL` shape (util-linux 2.33
# emits null for empty columns - loop devices have no TRAN; the old
# columnar split collapsed that empty middle column and crashed).
LSBLK_SAMPLE = """\
{
   "blockdevices": [
      {"name":"/dev/loop0", "size":"55.7M", "tran":null, "type":"loop", "model":null},
      {"name":"/dev/loop1", "size":"118.2M", "tran":null, "type":"loop", "model":null},
      {"name":"/dev/sda", "size":"7,5G", "tran":"usb", "type":"disk", "model":"Ultra USB 3.0"},
      {"name":"/dev/sdb", "size":"29,1G", "tran":"usb", "type":"disk", "model":"Linux UMS g_ums"},
      {"name":"/dev/nvme0n1", "size":"476,9G", "tran":"nvme", "type":"disk", "model":"Samsung SSD 970"},
      {"name":"/dev/sdb1", "size":"500M", "tran":"usb", "type":"part", "model":"DOS partitions"},
      {"name":"/dev/sdc", "size":"512M", "tran":"usb", "type":"disk", "model":"SmallReader"}
   ]
}
"""

BMAP_SAMPLE = """\
<?xml version="1.0" encoding="UTF-8"?>
<bmap>
  <ImageSize> 7895644160 </ImageSize>
</bmap>
"""


class HostGlueTests(unittest.TestCase):
    def test_parse_lsblk(self):
        disks = flash_auto.parse_lsblk(LSBLK_SAMPLE)
        by_name = {d["name"]: d for d in disks}
        self.assertEqual(by_name["/dev/sda"]["size_bytes"], 7500000000)
        self.assertEqual(by_name["/dev/sdb1"]["size_bytes"], 500000000)
        self.assertEqual(by_name["/dev/sdb"]["tran"], "usb")
        self.assertEqual(by_name["/dev/sdb"]["model"], "Linux UMS g_ums")
        self.assertEqual(by_name["/dev/sdb1"]["type"], "part")
        # loop devices: empty TRAN/MODEL (JSON null) must not collapse
        self.assertEqual(by_name["/dev/loop0"]["tran"], "")
        self.assertEqual(by_name["/dev/loop0"]["model"], "")
        self.assertEqual(by_name["/dev/loop0"]["type"], "loop")
        self.assertEqual(by_name["/dev/loop0"]["size_bytes"], 55700000)

    def test_image_size_from_bmap(self):
        with tempfile.NamedTemporaryFile("w", suffix=".bmap",
                                         delete=False) as f:
            f.write(BMAP_SAMPLE)
            path = f.name
        self.addCleanup(os.unlink, path)
        self.assertEqual(flash_auto.image_size_from_bmap(path), 7895644160)

    def test_choose_target_happy_path(self):
        disks = flash_auto.parse_lsblk(LSBLK_SAMPLE)
        target = flash_auto.choose_target(disks, image_bytes=8000000000,
                                          explicit=None)
        self.assertEqual(target, "/dev/sdb")

    def test_choose_target_ambiguous(self):
        disks = [d for d in flash_auto.parse_lsblk(LSBLK_SAMPLE)
                 if d["name"] != "/dev/sdb"]
        with self.assertRaises(flash_auto.DiskSelectionError) as ctx:
            flash_auto.choose_target(disks, image_bytes=None, explicit=None)
        self.assertIn("/dev/sda", str(ctx.exception))
        self.assertIn("/dev/sdc", str(ctx.exception))

    def test_choose_target_rejects_partition(self):
        disks = flash_auto.parse_lsblk(LSBLK_SAMPLE)
        with self.assertRaises(flash_auto.DiskSelectionError) as ctx:
            flash_auto.choose_target(disks, image_bytes=None,
                                     explicit="/dev/sdb1")
        self.assertIn("partition", str(ctx.exception))

    def test_choose_target_too_small(self):
        disks = [d for d in flash_auto.parse_lsblk(LSBLK_SAMPLE)
                 if d["name"] in ("/dev/sda", "/dev/nvme0n1")]
        with self.assertRaises(flash_auto.DiskSelectionError) as ctx:
            flash_auto.choose_target(disks, image_bytes=8000000000,
                                     explicit=None)
        self.assertIn("image", str(ctx.exception).lower())

class ChownLogTests(unittest.TestCase):
    """Logs written by the root sudo re-exec must still be the invoking
    user's files (deletable without sudo)."""

    def test_chowns_log_to_sudo_user(self):
        import pwd
        me = pwd.getpwuid(os.getuid())
        chown = mock.Mock()
        with mock.patch.dict(os.environ, {"SUDO_USER": me.pw_name}), \
                mock.patch.object(flash_auto.os, "chown", chown):
            flash_auto._chown_to_sudo_user("/tmp/fake-nxp-boot.log")
        chown.assert_called_once_with(
            "/tmp/fake-nxp-boot.log", me.pw_uid, me.pw_gid)

    def test_no_sudo_user_is_noop(self):
        chown = mock.Mock()
        env = {k: v for k, v in os.environ.items() if k != "SUDO_USER"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(flash_auto.os, "chown", chown):
            flash_auto._chown_to_sudo_user("/tmp/fake-nxp-boot.log")
        chown.assert_not_called()

    def test_unknown_user_is_best_effort(self):
        chown = mock.Mock()
        with mock.patch.dict(os.environ,
                             {"SUDO_USER": "no-such-user-xyz"}), \
                mock.patch.object(flash_auto.os, "chown", chown):
            flash_auto._chown_to_sudo_user("/tmp/fake-nxp-boot.log")
        chown.assert_not_called()


def _disk(name, size_bytes, tran="usb", dtype="disk", model="M"):
    return {"name": name, "size_bytes": size_bytes, "tran": tran,
            "type": dtype, "model": model}


class NativeAcquireTests(unittest.TestCase):
    def _patch(self, name, value):
        orig = getattr(flash_auto, name)
        setattr(flash_auto, name, value)
        self.addCleanup(setattr, flash_auto, name, orig)

    def setUp(self):
        self.args = flash_auto.build_arg_parser().parse_args([])

    def test_native_new_disk_watch_returns_it(self):
        lsblk_sequence = [
            [_disk("/dev/sda", 7500000000)],            # pre-ums snapshot
            [_disk("/dev/sda", 7500000000),
             _disk("/dev/sdb", 29100000000)],           # after ums
        ]
        self._patch("_lsblk_disks",
                    lambda: lsblk_sequence.pop(0)
                    if lsblk_sequence else lsblk_sequence[-1])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            device = flash_auto.default_acquire_disk(
                self.args, 8000000000,
                before_disks=[_disk("/dev/sda", 7500000000)])
        self.assertEqual(device, "/dev/sdb")

    def test_native_several_new_disks_abort(self):
        lsblk_sequence = [
            [_disk("/dev/sda", 7500000000)],
            [_disk("/dev/sda", 7500000000),
             _disk("/dev/sdb", 29100000000),
             _disk("/dev/sdc", 29100000000)],
        ]
        self._patch("_lsblk_disks",
                    lambda: lsblk_sequence.pop(0)
                    if lsblk_sequence else lsblk_sequence[-1])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(flash_auto.DiskSelectionError) as ctx:
                flash_auto.default_acquire_disk(
                    self.args, None,
                    before_disks=[_disk("/dev/sda", 7500000000)])
        self.assertIn("--device", str(ctx.exception))

    def test_native_timeout_falls_back_to_choose_target(self):
        # leftover gadget from an aborted run: disk present since before ums
        present = [_disk("/dev/sda", 7500000000),
                   _disk("/dev/sdb", 29100000000)]
        self._patch("_lsblk_disks", lambda: list(present))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            device = flash_auto.default_acquire_disk(
                self.args, 8000000000, before_disks=list(present),
                watch=0.2)
        self.assertEqual(device, "/dev/sdb")

    def test_native_ignores_non_usb_new_disk(self):
        seq = [
            [_disk("/dev/sda", 7500000000)],
            [_disk("/dev/sda", 7500000000),
             _disk("/dev/sdb", 29100000000, tran="sata")],  # not the gadget
        ]
        self._patch("_lsblk_disks",
                    lambda: seq.pop(0) if len(seq) > 1 else seq[0])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(flash_auto.DiskSelectionError):
                flash_auto.default_acquire_disk(
                    self.args, 8000000000,
                    before_disks=[_disk("/dev/sda", 7500000000)],
                    watch=0.2)


class PyserialLocalTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def test_import_serial_from_user_dir(self):
        pkg = os.path.join(self.tmpdir, "serial")
        os.makedirs(pkg)
        with open(os.path.join(pkg, "__init__.py"), "w") as f:
            f.write("__version__ = '3.5-local-stub'\n")
        # Drop any cached import so the stub at sys.path[0] wins even when
        # a system pyserial is installed.
        saved = sys.modules.pop("serial", None)
        try:
            module = flash_auto._import_serial_from([self.tmpdir])
            self.assertIsNotNone(module)
            self.assertEqual(module.__version__, "3.5-local-stub")
            self.assertIn(self.tmpdir, sys.path)
        finally:
            if self.tmpdir in sys.path:
                sys.path.remove(self.tmpdir)
            sys.modules.pop("serial", None)
            if saved is not None:
                sys.modules["serial"] = saved

    def test_user_pyserial_dirs_include_sudo_user_home(self):
        fake = types.SimpleNamespace(pw_dir="/home/other")
        with mock.patch.dict(os.environ, {"SUDO_USER": "other"}), \
                mock.patch("pwd.getpwnam", return_value=fake):
            dirs = flash_auto._user_pyserial_dirs()
        self.assertEqual(
            dirs[0],
            "/home/other/.local/share/pyserial/usr/lib/python3/dist-packages")
        self.assertTrue(dirs[-1].endswith(
            ".local/share/pyserial/usr/lib/python3/dist-packages"))


class BlkdiscardResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def test_sudo_user_homes_prefers_sudo_user(self):
        fake_pwd = types.SimpleNamespace(
            getpwnam=lambda n: types.SimpleNamespace(pw_dir="/home/other"))
        with mock.patch.dict(os.environ, {"SUDO_USER": "other"}), \
                mock.patch.dict(sys.modules, {"pwd": fake_pwd}):
            homes = flash_auto._sudo_user_homes()
        self.assertEqual(homes[0], "/home/other")
        self.assertGreater(len(homes), 1)

    def test_sudo_user_homes_skips_unknown_user(self):
        def boom(name):
            raise KeyError(name)
        fake_pwd = types.SimpleNamespace(getpwnam=boom)
        with mock.patch.dict(os.environ, {"SUDO_USER": "nope"}), \
                mock.patch.dict(sys.modules, {"pwd": fake_pwd}):
            homes = flash_auto._sudo_user_homes()
        self.assertEqual(homes, [os.path.expanduser("~")])

    def test_find_blkdiscard_prefers_path_which(self):
        self.assertEqual(
            flash_auto._find_blkdiscard(lambda name: "/usr/sbin/blkdiscard"),
            "/usr/sbin/blkdiscard")

    def test_find_blkdiscard_falls_back_to_local_bin(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        local = os.path.join(home, ".local", "bin", "blkdiscard")
        os.makedirs(os.path.dirname(local))
        open(local, "w").close()
        # USERPROFILE too: on Windows expanduser("~") ignores HOME
        with mock.patch.dict(os.environ,
                             {"HOME": home, "USERPROFILE": home}):
            self.assertEqual(
                flash_auto._find_blkdiscard(lambda name: None), local)

    def test_find_blkdiscard_prefers_sudo_user_home(self):
        sudo_home, eff_home = tempfile.mkdtemp(), tempfile.mkdtemp()
        for h in (sudo_home, eff_home):
            os.makedirs(os.path.join(h, ".local", "bin"))
            open(os.path.join(h, ".local", "bin", "blkdiscard"), "w").close()
        fake_pwd = types.SimpleNamespace(
            getpwnam=lambda n: types.SimpleNamespace(pw_dir=sudo_home))
        with mock.patch.dict(os.environ,
                             {"SUDO_USER": "other", "HOME": eff_home}), \
                mock.patch.dict(sys.modules, {"pwd": fake_pwd}):
            picked = flash_auto._find_blkdiscard(lambda name: None)
        self.assertEqual(picked,
                         os.path.join(sudo_home, ".local", "bin", "blkdiscard"))

    def test_find_bmaptool_uses_sudo_user_home(self):
        sudo_home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, sudo_home, ignore_errors=True)
        local = os.path.join(sudo_home, ".local", "bin", "bmaptool")
        os.makedirs(os.path.dirname(local))
        open(local, "w").close()
        fake_pwd = types.SimpleNamespace(
            getpwnam=lambda n: types.SimpleNamespace(pw_dir=sudo_home))
        with mock.patch.dict(os.environ,
                             {"SUDO_USER": "other", "HOME": "/nonexistent"}), \
                mock.patch.dict(sys.modules, {"pwd": fake_pwd}):
            self.assertEqual(flash_auto._find_bmaptool(lambda name: None), local)


class RemoteResetTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def test_remote_reset_writes_b_then_B(self):
        dev = os.path.join(self.tmpdir, "ttyACM0")
        with open(dev, "w") as f:
            f.write("")
        calls = []
        real_open = open

        def spy(file, mode="r", *a, **k):
            calls.append((file, mode))
            return real_open(file, mode, *a, **k)

        out = io.StringIO()
        with mock.patch("builtins.open", spy), \
                contextlib.redirect_stdout(out):
            ok = flash_auto._remote_reset_board(
                pattern=os.path.join(self.tmpdir, "ttyACM*"))
        self.assertTrue(ok)
        writes = [m for _, m in calls if m == "w"]
        self.assertEqual(len(writes), 2)
        with real_open(dev) as f:
            self.assertEqual(f.read(), "B\n")
        self.assertNotIn("power the board", out.getvalue())
        self.assertIn("reset", out.getvalue().lower())

    def test_remote_reset_falls_back_when_no_cdc(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = flash_auto._remote_reset_board(
                pattern=os.path.join(self.tmpdir, "ttyACM*"))
        self.assertFalse(ok)
        self.assertIn("power the board on / press reset now",
                      out.getvalue())

    def test_remote_reset_honors_explicit_dev(self):
        dev = os.path.join(self.tmpdir, "cdc9")
        with open(dev, "w") as f:
            f.write("")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = flash_auto._remote_reset_board(reset_dev=dev)
        self.assertTrue(ok)
        with open(dev) as f:
            self.assertEqual(f.read(), "B\n")

    def test_remote_reset_missing_explicit_dev_errors(self):
        with self.assertRaises(flash_auto.PreflightError):
            flash_auto._remote_reset_board(
                reset_dev=os.path.join(self.tmpdir, "nope"))


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.image = os.path.join(self.tmp, "sdcard.wic.gz")
        with open(self.image, "w") as f:
            f.write("(image)")
        self.bmap = os.path.join(self.tmp, "sdcard.wic.bmap")
        with open(self.bmap, "w") as f:
            f.write(BMAP_SAMPLE)
        self.logdir = os.path.join(self.tmp, "logs")
        os.makedirs(self.logdir)
        self._orig_log_dir = flash_auto._log_dir
        flash_auto._log_dir = lambda: self.logdir
        self.addCleanup(setattr, flash_auto, "_log_dir", self._orig_log_dir)

    def test_find_image_priority(self):
        # explicit wins even with an unrelated repo root
        self.assertEqual(
            flash_auto.find_image(self.image, "/nonexistent-root"),
            self.image)
        # artifacts/ default
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        artifacts = os.path.join(root, "artifacts")
        os.makedirs(artifacts)
        in_artifacts = os.path.join(artifacts, "sdcard.wic.gz")
        with open(in_artifacts, "w") as f:
            f.write("(image)")
        self.assertEqual(flash_auto.find_image(None, root), in_artifacts)
        # ~/sdcard.wic.gz fallback (root without an artifacts image)
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        in_home = os.path.join(home, "sdcard.wic.gz")
        with open(in_home, "w") as f:
            f.write("(image)")
        no_artifacts = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, no_artifacts, ignore_errors=True)
        with mock.patch.dict(os.environ, {"HOME": home}):
            self.assertEqual(
                flash_auto.find_image(None, no_artifacts), in_home)
            # nothing anywhere -> docker-export hint
            os.unlink(in_home)
            with self.assertRaises(flash_auto.PreflightError) as ctx:
                flash_auto.find_image(None, no_artifacts)
        self.assertIn("copy the image", str(ctx.exception))

    def test_arg_parser_flags_and_defaults(self):
        parser = flash_auto.build_arg_parser()
        defaults = parser.parse_args([])
        self.assertEqual(defaults.uart, "/dev/ttyUSB0")
        self.assertEqual(defaults.baud, 115200)
        self.assertEqual(defaults.timeout_power, 120)
        self.assertEqual(defaults.timeout_boot, 300)
        self.assertFalse(defaults.console)
        self.assertFalse(defaults.status)
        self.assertIsNone(defaults.image)
        self.assertIsNone(defaults.bmap)
        self.assertIsNone(defaults.device)

        full = parser.parse_args([
            "--console", "--status", "-i", "X", "-b", "Y", "-d", "/dev/sdz",
            "-u", "/dev/ttyUSB2", "--baud", "9600", "--timeout-power", "60",
            "--timeout-boot", "240"])
        self.assertTrue(full.console)
        self.assertTrue(full.status)
        self.assertEqual(full.image, "X")
        self.assertEqual(full.bmap, "Y")
        self.assertEqual(full.device, "/dev/sdz")
        self.assertEqual(full.uart, "/dev/ttyUSB2")
        self.assertEqual(full.baud, 9600)
        self.assertEqual(full.timeout_power, 60)
        self.assertEqual(full.timeout_boot, 240)

    def test_windows_wsl_options_are_rejected(self):
        parser = flash_auto.build_arg_parser()
        for option in ("--com", "--uart-busid", "--card-busid", "--no-attach"):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args([option, "value"])

    def test_no_wsl_implementation_remains(self):
        for name in ("_is_wsl", "parse_usbipd_list", "attach_usbipd_device",
                     "run_elevated_usbipd", "restart_ums"):
            self.assertFalse(hasattr(flash_auto, name), name)

    def test_status_works_without_image(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = flash_auto.main(
                ["--status", "-i", "/nonexistent/sdcard.wic.gz"],
                which=lambda name: "/fake/bmaptool"
                if name == "bmaptool" else None)
        self.assertEqual(rc, 0)
        self.assertIn("image", out.getvalue())
        self.assertIn("uart", out.getvalue())

    def test_status_honors_bmaptool_path_flag(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = flash_auto.main(
                ["--status", "--bmaptool-path", "/resolved/bmaptool",
                 "-i", "/nonexistent/sdcard.wic.gz"],
                which=lambda name: None)
        self.assertEqual(rc, 0)
        self.assertIn("/resolved/bmaptool", out.getvalue())

    def test_reexec_forwarded_args_include_reset_dev(self):
        args = flash_auto.build_arg_parser().parse_args(
            ["--reset-dev", "/dev/ttyACM2", "--timeout-boot", "240"])
        argv = flash_auto._reexec_forwarded_args(
            args, image="/tmp/img.wic.gz", bmap="/tmp/img.bmap",
            bmaptool="/resolved/bmaptool")
        self.assertIn("--reset-dev", argv)
        self.assertEqual(argv[argv.index("--reset-dev") + 1], "/dev/ttyACM2")
        self.assertIn("--bmaptool-path", argv)
        self.assertIn("240", argv)

    def test_reexec_forwarded_args_include_timeout_ip(self):
        args = flash_auto.build_arg_parser().parse_args(["--timeout-ip", "45"])
        argv = flash_auto._reexec_forwarded_args(
            args, image="/tmp/img.wic.gz", bmap="/tmp/img.bmap",
            bmaptool="/resolved/bmaptool")
        self.assertIn("--timeout-ip", argv)
        self.assertEqual(argv[argv.index("--timeout-ip") + 1], "45")

    def test_main_end_to_end_dialog(self):
        port = RespondingPort()  # console bytes arrive after the drain, as
        # on real hardware where stale bytes precede the open
        boot_start = threading.Timer(
            0.2,
            port.feed,
            args=(b"U-Boot 2020.04 ...\r\n"
                  b"Hit any key to stop autoboot:  2 \x08 1",))
        boot_start.start()
        self.addCleanup(boot_start.cancel)

        def on_write(data):
            if data == b"\r":
                port.feed("\n=> ")
            elif data == b"ums 0 mmc 2:0\r":
                port.feed(b"UMS: LUN 0, dev mmc 2, hwpart 0, sector 0x0, "
                          b"count 0x1d34000\r\n" + b"/-\\" * 4096)
            elif data == b"\x03":
                port.feed(b"CTRL+C - Operation aborted\r\n=> ")
            elif data == b"reset\r":
                port.feed(b"U-Boot 2020.04 ...\r\n"
                          b"Hit any key to stop autoboot:  2 \x08 1 \x08 0\r\n"
                          b"Starting kernel ...\r\n"
                          b"[    1.000000] systemd[1]: Detected architecture\r\n"
                          b"imx8mpcartzy-hud7 login: ")
                # the NM dispatcher announces the address shortly after
                # the login prompt is up
                threading.Timer(
                    0.3, port.feed,
                    args=(b"cartzy-board-ip: wlan0 172.16.100.54\r\n",)).start()

        port.on_write = on_write

        recorded = []

        def fake_run(argv, **kwargs):
            recorded.append(argv)
            return types.SimpleNamespace(returncode=0)

        got = {}

        def fake_acquire(args, image_bytes):
            got["image_bytes"] = image_bytes
            return "/dev/sdb"

        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
                mock.patch.dict(os.environ,
                                {"HOME": self.tmpdir,
                                 "USERPROFILE": self.tmpdir}):
            rc = flash_auto.main(
                ["-i", self.image],
                port_factory=lambda: port,
                run=fake_run,
                acquire_disk=fake_acquire,
                reset_board=lambda: None,
                which=lambda name: "/fake/bmaptool"
                if name == "bmaptool" else None)

        self.assertEqual(rc, 0)
        self.assertTrue(port.drained, "main must drain the port at open")
        self.assertEqual(port.writes,
                         [b"\r", b"ums 0 mmc 2:0\r", b"\x03", b"reset\r"])
        self.assertEqual(port.breaks, [],
                         "happy path (autoboot catchable) must not break")
        self.assertEqual(got["image_bytes"], 7895644160)
        self.assertEqual(recorded[0], "umount /dev/sdb?*")
        self.assertEqual(recorded[1], ["blkdiscard", "-f", "/dev/sdb"])
        self.assertEqual(
            recorded[2],
            ["/fake/bmaptool", "copy", "--bmap", self.bmap, self.image,
             "/dev/sdb"])
        text = out.getvalue()
        markers = ["[1/7]", "[2/7]", "[3/7]", "[4/7]", "[5/7]", "[6/7]",
                   "[7/7]"]
        positions = [text.index(m) for m in markers]
        self.assertEqual(positions, sorted(positions))
        # the reset request is gone from the head of the dialog: reaching
        # the board is now phase [1/7], automatic (in-band reboot), and a
        # manual reset is asked for only when the console stays silent
        self.assertNotIn("power the board on / press reset now", text)
        self.assertIn("reaching the board", text)
        # the operator must be pointed at the runbook right after the image
        # lands on the card, before the reset
        self.assertIn("crash-loop", text)
        self.assertIn("docs/boot-troubleshooting.md", text)
        self.assertIn(
            "blkdiscard not found - run tools/install-local-deps.sh", text)
        self.assertLess(text.index("[4/7]"), text.index("crash-loop"))
        self.assertLess(text.index("crash-loop"), text.index("[5/7]"))
        self.assertIn("PASS", text)
        self.assertIn("board ip : wlan0 172.16.100.54", text)
        self.assertLess(text.index("PASS"), text.index("board ip :"))
        self.assertIn("log:", text)
        logs = [f for f in os.listdir(self.logdir) if f.endswith(".log")]
        self.assertEqual(len(logs), 1)
        with open(os.path.join(self.logdir, logs[0]), newline="") as f:
            content = f.read()
        self.assertIn(">>> ums 0 mmc 2:0", content)
        self.assertIn("UMS: LUN 0", content)


class RebootInbandTests(unittest.TestCase):
    def setUp(self):
        fd, self.log_path = tempfile.mkstemp(suffix=".log")
        os.close(fd)

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)

    def _console(self, port):
        console = flash_auto.Console(port, self.log_path)
        self.addCleanup(console.close)
        return console

    def test_sysrq_reboots_immediately(self):
        port = RespondingPort()

        def on_write(data):
            if data == b"b":
                port.feed("U-Boot SPL 2022.04-63272-gc83270c1f4 "
                          "(Feb 06 2023 - 15:46:50 -0800)\r")

        port.on_write = on_write
        result = flash_auto.phase_reboot_inband(
            self._console(port), sysrq_wait=1)
        self.assertEqual(result, "sysrq")
        self.assertEqual(port.writes, [b"b"])
        self.assertEqual(port.breaks, [0.3])
        self.assertNotIn(b"root\r", port.writes)
        self.assertNotIn(b"reboot\r", port.writes)

    def test_sysrq_silent_falls_back_to_login(self):
        port = RespondingPort(initial=b"imx8mpcartzy-j3oq login: ")
        root_prompts = iter(["Password: ",
                             "root@imx8mpcartzy-j3oq:~# "])

        def on_write(data):
            if data == b"root\r":
                port.feed(next(root_prompts))

        port.on_write = on_write
        result = flash_auto.phase_reboot_inband(
            self._console(port), sysrq_wait=0.3)
        self.assertEqual(result, "login")
        self.assertEqual(port.writes,
                         [b"b", b"root\r", b"root\r", b"reboot\r"])
        self.assertEqual(port.breaks, [0.3])

    def test_fallback_login_timeout_raises(self):
        port = RespondingPort()
        with self.assertRaises(flash_auto.ConsoleTimeout):
            flash_auto.phase_reboot_inband(
                self._console(port), sysrq_wait=0.3, login_wait=0.3)


class PowerWaitInbandTests(unittest.TestCase):
    def setUp(self):
        fd, self.log_path = tempfile.mkstemp(suffix=".log")
        os.close(fd)

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)

    def _console(self, port):
        console = flash_auto.Console(port, self.log_path)
        self.addCleanup(console.close)
        return console

    def test_login_triggers_inband_reboot(self):
        port = RespondingPort(initial=b"imx8mpcartzy-j3oq login: ")

        def on_write(data):
            if data == b"b":
                port.feed("U-Boot SPL 2022.04-63272-gc83270c1f4\r"
                          "Hit any key to stop autoboot:  2 ")
            elif data == b"\r":
                port.feed("\n=> ")

        port.on_write = on_write
        flash_auto.phase_power_wait(self._console(port), 5)
        self.assertEqual(port.writes, [b"b", b"\r"])
        self.assertEqual(port.breaks, [0.3])

    def test_kernel_start_triggers_inband_reboot(self):
        port = RespondingPort(initial=b"Starting kernel ...\r")

        def on_write(data):
            if data == b"b":
                port.feed("U-Boot SPL 2022.04-63272-gc83270c1f4\r"
                          "Hit any key to stop autoboot:  2 ")
            elif data == b"\r":
                port.feed("\n=> ")

        port.on_write = on_write
        flash_auto.phase_power_wait(self._console(port), 5)
        self.assertEqual(port.writes, [b"b", b"\r"])
        self.assertEqual(port.breaks, [0.3])

    def test_prompt_never_reboots(self):
        port = RespondingPort(initial=b"\n=> ")
        flash_auto.phase_power_wait(self._console(port), 1)
        self.assertEqual(port.writes, [])
        self.assertEqual(port.breaks, [])

    def test_second_linux_stays_manual(self):
        port = RespondingPort(initial=b"imx8mpcartzy-j3oq login: ")

        def on_write(data):
            if data == b"b":
                # SysRq worked, but the autoboot countdown is missed:
                # the board sails straight back into Linux
                port.feed("U-Boot SPL 2022.04-63272-gc83270c1f4\r"
                          "Starting kernel ...\r"
                          "imx8mpcartzy-j3oq login: ")

        port.on_write = on_write
        out = io.StringIO()
        console = self._console(port)
        with contextlib.redirect_stdout(out):
            with self.assertRaises(flash_auto.ConsoleTimeout):
                flash_auto.phase_power_wait(console, 1)
        self.assertEqual(port.breaks, [0.3])
        self.assertIn(flash_auto.MISSED_INTERRUPT_MSG, out.getvalue())

    def test_login_trigger_sysrq_dead_falls_back_via_flush(self):
        """Realistic fallback: power_wait consumed the login prompt, SysRq
        is dead, and getty only reprints after the flushing Enter."""
        port = RespondingPort(initial=b"imx8mpcartzy-j3oq login: ")
        cr_writes = [0]
        root_writes = [0]

        def on_write(data):
            if data == b"\r":
                cr_writes[0] += 1
                if cr_writes[0] == 1:      # the flush: 'b' submitted alone
                    port.feed("Login incorrect\r\nimx8mpcartzy-j3oq login: ")
                else:                      # autoboot interrupt
                    port.feed("\n=> ")
            elif data == b"root\r":
                root_writes[0] += 1
                if root_writes[0] == 1:
                    port.feed("Password: ")
                else:
                    port.feed("root@imx8mpcartzy-j3oq:~# ")
            elif data == b"reboot\r":
                port.feed("U-Boot SPL 2022.04-63272-gc83270c1f4\r"
                          "Hit any key to stop autoboot:  2 ")
            # b"b" and the BREAK get no reaction: SysRq disabled

        port.on_write = on_write
        flash_auto.phase_power_wait(self._console(port), 30)
        self.assertEqual(
            port.writes,
            [b"b", b"\r", b"root\r", b"root\r", b"reboot\r", b"\r"])
        self.assertEqual(port.breaks, [0.3])

    def test_probe_wakes_silent_console(self):
        """Idle board (drained prompt banner): one \\n surfaces the state."""
        port = RespondingPort()
        port.on_write = (lambda data: port.feed("\n=> ")
                         if data == b"\n" else None)
        flash_auto.phase_power_wait(self._console(port), 8)
        self.assertEqual(port.writes, [b"\n"])
        self.assertEqual(port.breaks, [])

    def test_budget_clamps_inband_waits(self):
        console = self._console(FakePort())
        start = time.monotonic()
        with self.assertRaises(flash_auto.ConsoleTimeout):
            flash_auto.phase_reboot_inband(
                console, sysrq_wait=10.0, budget=time.monotonic() + 0.5)
        self.assertLess(time.monotonic() - start, 2.5)

    def test_inband_failure_prints_context(self):
        port = RespondingPort(initial=b"imx8mpcartzy-j3oq login: ")
        port.on_write = lambda data: None  # nothing ever answers
        out = io.StringIO()
        console = self._console(port)
        with contextlib.redirect_stdout(out):
            with self.assertRaises(flash_auto.ConsoleTimeout):
                flash_auto.phase_power_wait(console, 2)
        self.assertIn("in-band", out.getvalue())


class MarkerTests(unittest.TestCase):
    def test_markers_match_real_log_bytes(self):
        cases = {
            "autoboot": "Hit any key to stop autoboot:  2 \x08 1 \x08 0 \r",
            "prompt": "\r\nU-Boot 2020.04 ...\r\n=> ",
            "ums_start": "UMS: LUN 0, dev mmc 2, hwpart 0, sector 0x0, "
                         "count 0x1d34000\r",
            "kernel_start": "Starting kernel ...\r",
            "login": "imx8mpcartzy-jgcz login: systemd-rfkill.service: "
                     "Deactivated successfully.\r",
            "spl": "U-Boot SPL 2022.04-63272-gc83270c1f4 "
                   "(Feb 06 2023 - 15:46:50 -0800)\r",
            "password_prompt": "Password: ",
            "shell_prompt": "root@imx8mpcartzy-j3oq:~# \r",
        }
        for name, raw in cases.items():
            with self.subTest(marker=name):
                normalized = flash_auto.normalize(raw)
                self.assertIsNotNone(
                    flash_auto.PATTERNS[name].search(normalized),
                    f"PATTERNS[{name!r}] does not match {raw!r}",
                )

    def test_panic_and_aborted(self):
        self.assertIsNotNone(
            flash_auto.PATTERNS["panic"].search(
                flash_auto.normalize("Kernel panic - not syncing: VFS")))
        self.assertIsNotNone(
            flash_auto.PATTERNS["aborted"].search(
                flash_auto.normalize("CTRL+C - Operation aborted")))


class ManualFlashGuidanceTests(unittest.TestCase):
    """The manual flash flows (tmux hints, README) must never guide a user
    into a silent sparse copy on used media: when blkdiscard fails, the
    fallback must pass --nobmap (bmaptool auto-discovers an adjacent .bmap
    and goes sparse otherwise)."""

    @staticmethod
    def _read(*parts):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts)
        with open(path) as f:
            return f.read()

    def test_manual_flashing_doc_is_full_copy(self):
        body = self._read("..", "..", "docs", "manual-flashing.md")
        self.assertIn("copy --nobmap ~/sdcard.wic.gz", body)

    def test_remote_env_hints_wipe_then_full_copy(self):
        body = self._read("..", "tmux-flash-env.sh")
        self.assertIn("blkdiscard", body)
        self.assertIn("--nobmap", body)

    def test_manual_flows_call_local_blkdiscard(self):
        call = 'sudo "$HOME/.local/bin/blkdiscard" -f /dev/sdb'
        self.assertIn(call, self._read("..", "..", "docs", "manual-flashing.md"))
        self.assertIn(call, self._read("..", "tmux-flash-env.sh"))

    def test_hints_block_has_no_apostrophes(self):
        body = self._read("..", "tmux-flash-env.sh")
        block = body[body.index("Flashing checklist:"):body.index("\nHINTS\n")]
        self.assertNotIn("'", block,
                         "hints run inside a single-quoted ssh argument")


class InstallLocalDepsTests(unittest.TestCase):
    @staticmethod
    def _read(*parts):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts)
        with open(path) as f:
            return f.read()

    def test_blkdiscard_stanza_is_self_contained(self):
        body = self._read("..", "install-local-deps.sh")
        self.assertIn(
            "util-linux_2.36.1-8+deb11u2_amd64.deb", body)
        self.assertIn(
            "libblkid1_2.36.1-8+deb11u2_amd64.deb", body)
        self.assertIn(
            "LD_LIBRARY_PATH=\"$INSTALL_DIR/usr/lib/x86_64-linux-gnu", body)
        # absolute path baked at install time - $HOME is wrong under sudo;
        # \$@ is heredoc-escaped, exactly like the bmaptool wrapper
        self.assertIn('exec "$INSTALL_DIR/sbin/blkdiscard" "\\$@"', body)
        self.assertIn('"$BIN_DIR/blkdiscard" --version', body)


if __name__ == "__main__":
    unittest.main()
