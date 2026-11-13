"""Tests for configure_rootfs_docker in tools/distro_debian (bash; driven via subprocess).

Run with Python 3 on a Linux host:
  python3 -m unittest discover -s tools/tests -p 'test_distro_debian_docker.py' -v
"""

import os
import re
import stat
import subprocess
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
DISTRO_DEBIAN = os.path.join(TESTS_DIR, "..", "distro_debian")

FAKE_KEY = "-----BEGIN PGP PUBLIC KEY BLOCK-----\nFAKE\n"

EXPECTED_SOURCES = (
    "Types: deb\n"
    "URIs: https://download.docker.com/linux/debian\n"
    "Suites: bookworm\n"
    "Components: stable\n"
    "Architectures: arm64\n"
    "Signed-By: /etc/apt/keyrings/docker.asc\n"
)

# Parses "-o FILE" from args and writes a fake armored key; no -o -> exit 1.
CURL_OK = """#!/bin/sh
out=""
while [ $# -gt 0 ]; do
    case "$1" in
        -o) out="$2"; shift 2 ;;
        *) shift ;;
    esac
done
[ -n "$out" ] || exit 1
printf '%s\\n' '-----BEGIN PGP PUBLIC KEY BLOCK-----' 'FAKE' > "$out"
"""

CURL_FAIL = "#!/bin/sh\nexit 22\n"


def _write(path, content):
    with open(path, "w", newline="") as f:
        f.write(content)
    os.chmod(path, 0o755)


GROUP_HELPERS_HARNESS = """
fbprint_e() { echo "ERR: $*" >&2; }
source "%s"
RFSDIR="%%s"
sudopt=""
add_rootfs_docker_group_members
""" % DISTRO_DEBIAN


class AddRootfsDockerGroupMembersTests(unittest.TestCase):
    """cartzy is created at first boot, so docker-group membership must be
    claimed by name in /etc/group at build time (usermod cannot do it)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "rootfs")
        self.etc = os.path.join(self.root, "etc")
        os.makedirs(self.etc)

    def _group(self, content):
        _write(os.path.join(self.etc, "group"), content)

    def _read_group(self):
        with open(os.path.join(self.etc, "group")) as f:
            return f.read()

    def _run(self):
        harness = GROUP_HELPERS_HARNESS % self.root
        return subprocess.run(["bash", "-c", harness],
                              capture_output=True, text=True)

    def test_appends_to_empty_member_list(self):
        self._group("sudo:x:27:debian\ndocker:x:994:\n")
        res = self._run()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("docker:x:994:cartzy,debian", self._read_group())

    def test_appends_to_existing_members(self):
        self._group("docker:x:994:alice\n")
        res = self._run()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("docker:x:994:alice,cartzy,debian", self._read_group())

    def test_is_idempotent(self):
        self._group("docker:x:994:alice,cartzy,debian\n")
        res = self._run()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual("docker:x:994:alice,cartzy,debian\n",
                         self._read_group().strip() + "\n")

    def test_missing_docker_group_is_noop(self):
        self._group("sudo:x:27:debian\n")
        res = self._run()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("docker:", self._read_group())


class ConfigureRootfsDockerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "rootfs")
        os.makedirs(self.root)
        self.bindir = os.path.join(self.tmp.name, "bin")
        os.makedirs(self.bindir)
        _write(os.path.join(self.bindir, "curl"), CURL_OK)

    def _harness(self, knob="docker-ce docker-ce-cli containerd.io docker-compose-plugin",
                 codename="bookworm", arch="arm64"):
        return (
            'fbprint_e() { echo "ERR: $*" >&2; }\n'
            'source "%s"\n'
            'PATH="%s:$PATH"\n'
            'export PATH\n'
            'RFSDIR="%s"\n'
            'sudopt=""\n'
            'ROOTFS_DOCKER_PACKAGES="%s"\n'
            'DEBIAN_CODENAME="%s"\n'
            'DESTARCH="%s"\n'
            'configure_rootfs_docker\n' % (
                DISTRO_DEBIAN, self.bindir, self.root, knob, codename, arch)
        )

    def _run(self, harness):
        return subprocess.run(["bash", "-c", harness],
                              capture_output=True, text=True)

    def _read(self, *parts):
        with open(os.path.join(self.root, *parts)) as f:
            return f.read()

    def _mode(self, *parts):
        return stat.S_IMODE(os.stat(os.path.join(self.root, *parts)).st_mode)

    def test_writes_keyring_and_sources(self):
        res = self._run(self._harness())
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self._read("etc", "apt", "keyrings", "docker.asc"),
                         FAKE_KEY)
        self.assertEqual(self._mode("etc", "apt", "keyrings", "docker.asc"),
                         0o644)
        self.assertEqual(self._mode("etc", "apt", "keyrings"), 0o755)
        self.assertEqual(self._read("etc", "apt", "sources.list.d",
                                    "docker.sources"),
                         EXPECTED_SOURCES)

    def test_empty_knob_is_noop(self):
        res = self._run(self._harness(knob=""))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(
            os.path.exists(os.path.join(self.root, "etc", "apt", "keyrings")))
        self.assertFalse(os.path.exists(
            os.path.join(self.root, "etc", "apt", "sources.list.d",
                         "docker.sources")))

    def test_curl_failure_fails_loudly(self):
        _write(os.path.join(self.bindir, "curl"), CURL_FAIL)
        res = self._run(self._harness())
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("docker GPG key", res.stderr)
        self.assertFalse(os.path.exists(
            os.path.join(self.root, "etc", "apt", "keyrings", "docker.asc")))
        self.assertFalse(os.path.exists(
            os.path.join(self.root, "etc", "apt", "sources.list.d",
                         "docker.sources")))

    def test_sources_use_env_codename_arch(self):
        res = self._run(self._harness(codename="trixie"))
        self.assertEqual(res.returncode, 0, res.stderr)
        sources = self._read("etc", "apt", "sources.list.d", "docker.sources")
        self.assertIn("Suites: trixie", sources)
        self.assertNotIn("Suites: bookworm", sources)


BOARD_CONF = os.path.join(TESTS_DIR, "..", "..", "configs", "board",
                          "imx8mpcartzy.conf")

APT_UPDATE_LINE = ("chroot $RFSDIR env DEBIAN_FRONTEND=noninteractive "
                   "apt-get update")


class DistroDebianWiringTests(unittest.TestCase):
    """Source-content checks pinning the build wiring for preinstalled Docker."""

    def setUp(self):
        with open(DISTRO_DEBIAN) as f:
            self.distro = f.read()

    def test_profile_signature_includes_docker_knob(self):
        self.assertIn("docker_pkgs=${ROOTFS_DOCKER_PACKAGES:-}", self.distro)

    def test_configure_call_precedes_apt_update(self):
        # The bare call on its own line (not the definition) must run before
        # the chroot apt-get update that has to pick up the docker repo.
        call = re.search(r"^[ \t]*configure_rootfs_docker[ \t]*$", self.distro,
                         re.M)
        self.assertIsNotNone(call, "bare configure_rootfs_docker call missing")
        self.assertLess(self.distro.index(call.group(0)),
                        self.distro.index(APT_UPDATE_LINE))

    def test_install_and_enable_block(self):
        self.assertIn("apt-get install -y $ROOTFS_DOCKER_PACKAGES",
                      self.distro)
        self.assertIn(
            'ln -sfn /lib/systemd/system/docker.service '
            '"$RFSDIR/etc/systemd/system/multi-user.target.wants/'
            'docker.service"', self.distro)
        self.assertIn(
            'ln -sfn /lib/systemd/system/containerd.service '
            '"$RFSDIR/etc/systemd/system/multi-user.target.wants/'
            'containerd.service"', self.distro)
        # Group membership is claimed in /etc/group (cartzy only exists after
        # first boot, so usermod cannot work at build time).
        self.assertIn("add_rootfs_docker_group_members", self.distro)
        self.assertNotIn("usermod -aG docker", self.distro)

    def test_board_conf_declares_docker_packages(self):
        with open(BOARD_CONF) as f:
            conf = f.read()
        self.assertIn(
            'ROOTFS_DOCKER_PACKAGES="docker-ce docker-ce-cli containerd.io '
            'docker-compose-plugin"', conf)


if __name__ == "__main__":
    unittest.main()
