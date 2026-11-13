"""Tests for tools/board-provision (bash; driven via subprocess)."""

import os
import stat
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "board-provision")


class BoardProvisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "rootfs")
        os.makedirs(self.root)

    def _env(self, lines, name="board.env"):
        """Write an env file with the exact given lines (verbatim)."""
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", newline="") as f:
            f.write(lines)
        return path

    def _run(self, env_path):
        return subprocess.run(
            ["bash", SCRIPT, env_path, self.root],
            capture_output=True, text=True)

    def _keyfile(self):
        return os.path.join(
            self.root, "etc", "NetworkManager", "system-connections",
            "board-wifi.nmconnection")

    def _read(self, path):
        with open(path) as f:
            return f.read()

    def _mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    def test_happy_path(self):
        pub = os.path.join(self.tmp.name, "key.pub")
        with open(pub, "w") as f:
            f.write("ssh-ed25519 AAAA board@test\n")
        env = self._env(
            "WIFI_SSID=MyNet\nWIFI_PASS=secret123\n"
            "SSH_PUBKEY=%s\n" % pub)
        res = self._run(env)
        self.assertEqual(res.returncode, 0, res.stderr)
        keyfile = self._read(self._keyfile())
        for needle in ("[connection]", "id=board-wifi", "type=wifi",
                       "interface-name=wlan0",
                       "ssid=MyNet", "key-mgmt=wpa-psk", "psk=secret123"):
            self.assertIn(needle, keyfile)
        self.assertEqual(self._mode(self._keyfile()), 0o600)
        auth = os.path.join(self.root, "root", ".ssh", "authorized_keys")
        self.assertEqual(self._read(auth), "ssh-ed25519 AAAA board@test\n")
        self.assertEqual(self._mode(auth), 0o600)
        self.assertEqual(
            self._mode(os.path.join(self.root, "root", ".ssh")), 0o700)

    def test_strips_crlf(self):
        env = self._env("WIFI_SSID=MyNet\r\nWIFI_PASS=secret123\r\n")
        res = self._run(env)
        self.assertEqual(res.returncode, 0, res.stderr)
        keyfile = self._read(self._keyfile())
        self.assertIn("psk=secret123", keyfile)
        self.assertNotIn("\r", keyfile)
        self.assertIn("ssid=MyNet", keyfile)

    def test_strips_utf8_bom_first_line(self):
        env = self._env("\ufeffWIFI_SSID=MyNet\r\n"
                        "WIFI_PASS=secret123\r\n")
        res = self._run(env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("ssid=MyNet", self._read(self._keyfile()))

    def test_psk_verbatim_special_chars(self):
        env = self._env("WIFI_SSID=MyNet\nWIFI_PASS=my pass # word\n")
        res = self._run(env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("psk=my pass # word", self._read(self._keyfile()))

    def test_missing_ssid_fails_loudly(self):
        env = self._env("WIFI_PASS=secret123\n")
        res = self._run(env)
        self.assertEqual(res.returncode, 2)
        self.assertIn("WIFI_SSID", res.stderr)

    def test_bad_pubkey_path_fails_loudly(self):
        env = self._env(
            "WIFI_SSID=MyNet\nWIFI_PASS=secret123\n"
            "SSH_PUBKEY=missing.pub\n")
        res = self._run(env)
        self.assertEqual(res.returncode, 2)
        self.assertIn("SSH_PUBKEY", res.stderr)

    def test_no_ssh_pubkey_skips_authorized_keys(self):
        env = self._env("WIFI_SSID=MyNet\nWIFI_PASS=secret123\n")
        res = self._run(env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(os.path.exists(
            os.path.join(self.root, "root", ".ssh")))

    def test_missing_env_file(self):
        res = self._run(os.path.join(self.tmp.name, "nope.env"))
        self.assertEqual(res.returncode, 2)

    def test_git_mode_executable(self):
        """The script must be committed +x: flex-installer execs it directly."""
        out = subprocess.run(
            ["git", "ls-files", "-s", "tools/board-provision"],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), "..", ".."))
        self.assertTrue(out.stdout.startswith("100755"), out.stdout)

    def test_psk_backslash_rejected(self):
        """GLib keyfile interprets backslash escapes - silent breakage."""
        env = self._env("WIFI_SSID=MyNet\nWIFI_PASS=has\\backslash\n")
        res = self._run(env)
        self.assertEqual(res.returncode, 2)
        self.assertIn("WIFI_PASS", res.stderr)

    def test_value_edge_whitespace_rejected(self):
        for bad in (" lead", "trail "):
            env = self._env("WIFI_SSID=MyNet\nWIFI_PASS=%s\n" % bad)
            res = self._run(env)
            self.assertEqual(res.returncode, 2, bad)
            self.assertIn("WIFI_PASS", res.stderr)

    def test_quoted_value_rejected(self):
        env = self._env('WIFI_SSID=MyNet\nWIFI_PASS="my pass"\n')
        res = self._run(env)
        self.assertEqual(res.returncode, 2)
        self.assertIn("quotes", res.stderr)

    def test_ssid_too_long_rejected(self):
        env = self._env("WIFI_SSID=%s\nWIFI_PASS=secret123\n" % ("x" * 33))
        res = self._run(env)
        self.assertEqual(res.returncode, 2)
        self.assertIn("WIFI_SSID", res.stderr)

    def test_psk_too_short_rejected(self):
        env = self._env("WIFI_SSID=MyNet\nWIFI_PASS=seven77\n")
        res = self._run(env)
        self.assertEqual(res.returncode, 2)
        self.assertIn("WIFI_PASS", res.stderr)

    def test_ssid_not_printed_to_log(self):
        env = self._env("WIFI_SSID=SecretNet42\nWIFI_PASS=secret123\n")
        res = self._run(env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("SecretNet42", res.stdout)

    def test_installs_ip_announcer(self):
        env = self._env("WIFI_SSID=MyNet\nWIFI_PASS=secret123\n")
        res = self._run(env)
        self.assertEqual(res.returncode, 0, res.stderr)
        d = os.path.join(
            self.root, "etc", "NetworkManager", "dispatcher.d",
            "99-cartzy-announce-ip")
        self.assertTrue(os.path.isfile(d), d)
        self.assertEqual(self._mode(d), 0o755)
        body = self._read(d)
        self.assertIn("cartzy-board-ip:", body)
        self.assertIn("/dev/console", body)
        self.assertIn('"$1"', body)   # interface argument
        self.assertIn('"$2" = "up"', body)  # action gate
        self.assertIn('"$1" = "lo"', body)  # loopback skip
        self.assertIn("169\\.254", body)   # link-local never announced
        syntax = subprocess.run(["sh", "-n", d], capture_output=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)


if __name__ == "__main__":
    unittest.main()
