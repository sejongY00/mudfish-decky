import hashlib
import io
import os
import stat
import tarfile
import tempfile
import unittest

from mudfish_decky.installer import (InstallError, carry_login, install_package, latest_version, parse_makeself,
                                     prune_versions, remove_all)

FILES = {
    "./bin/mudrun-headless": b"#!bin",
    "./bin/mudfish": b"#!bin",
    "./bin/pkg_linux_setup.sh": b"#!/bin/sh\nrm -rf /\n",
    "./sbin/mudovpn": b"#!sbin",
    "./etc/htdocs-www-6.7.0.tar": b"tar",
    "./share/mudrun_logo.png": b"png",
}


def make_payload(files=FILES, extra=None):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))
        if extra:
            extra(tar)
    return buf.getvalue()


def make_package(payload, version="6.7.0", md5=None, skip=12):
    header = [
        "#!/bin/sh",
        "# This script was generated using Makeself 2.5.0",
        f'MD5="{md5 or hashlib.md5(payload).hexdigest()}"',
        'SHA="0000000000000000000000000000000000000000000000000000000000000000"',
        f'label="Mudfish Cloud VPN v{version}"',
        'script="./bin/pkg_linux_setup.sh"',
        f'targetdir="{version}"',
        f'filesizes="{len(payload)}"',
        f'skip="{skip}"',
    ]
    header += ["# filler"] * (skip - 1 - len(header)) + ["eval $finish; exit $res"]
    return ("\n".join(header) + "\n").encode() + payload


class ParseTest(unittest.TestCase):
    def test_latest_version_picks_highest(self):
        html = ('<a href="/releases/mudfish-6.5.5-linux-x86_64.sh">x</a>'
                '<a href="/releases/mudfish-6.10.0-linux-x86_64.sh">y</a>'
                '<a href="/releases/mudfish-6.6.0-linux-x86_64.sh">z</a>')
        self.assertEqual(latest_version(fetch=lambda url: html), "6.10.0")

    def test_latest_version_none_when_page_has_none(self):
        self.assertIsNone(latest_version(fetch=lambda url: "<html></html>"))

    def test_parse_makeself(self):
        payload = make_payload()
        header, body = parse_makeself(make_package(payload))
        self.assertEqual(header["targetdir"], "6.7.0")
        self.assertEqual(body, payload)

    def test_parse_rejects_non_makeself(self):
        with self.assertRaises(InstallError):
            parse_makeself(b"<html>not found</html>")


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "mudfish")

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_package_lays_out_version_dir(self):
        self.assertEqual(install_package(make_package(make_payload()), self.root), "6.7.0")
        base = os.path.join(self.root, "6.7.0")
        binary = os.path.join(base, "bin", "mudrun-headless")
        self.assertTrue(os.path.isfile(binary))
        self.assertEqual(stat.S_IMODE(os.stat(binary).st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(base, "share", "mudrun_logo.png")).st_mode), 0o644)
        self.assertTrue(os.path.isdir(os.path.join(base, "var")))
        self.assertFalse(os.path.exists(os.path.join(base, "bin", "pkg_linux_setup.sh")))
        self.assertEqual(sorted(os.listdir(self.root)), ["6.7.0"])

    def test_md5_mismatch_installs_nothing(self):
        with self.assertRaises(InstallError):
            install_package(make_package(make_payload(), md5="0" * 32), self.root)
        self.assertFalse(os.path.exists(os.path.join(self.root, "6.7.0")))

    def test_path_traversal_installs_nothing(self):
        bad = make_payload({"../../evil": b"x", "./bin/mudrun-headless": b"#!bin"})
        with self.assertRaises(InstallError):
            install_package(make_package(bad), self.root)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "evil")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "6.7.0")))

    def test_symlink_member_rejected(self):
        def add_link(tar):
            link = tarfile.TarInfo("./bin/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/shadow"
            tar.addfile(link)
        with self.assertRaises(InstallError):
            install_package(make_package(make_payload(extra=add_link)), self.root)

    def test_missing_daemon_binary_rejected(self):
        with self.assertRaises(InstallError):
            install_package(make_package(make_payload({"./bin/mudfish": b"x"})), self.root)

    def test_bad_version_string_rejected(self):
        with self.assertRaises(InstallError):
            install_package(make_package(make_payload(), version="../x"), self.root)

    def test_carry_login_copies_conf_files(self):
        old, new = os.path.join(self.tmp.name, "old"), os.path.join(self.tmp.name, "new")
        os.makedirs(old)
        os.makedirs(new)
        for name in (".conf", ".conf.db", ".cache.db"):
            with open(os.path.join(old, name), "w") as f:
                f.write(name)
        carry_login(old, new)
        self.assertEqual(sorted(os.listdir(new)), [".conf", ".conf.db"])

    def test_prune_versions_keeps_listed(self):
        for v in ("6.5.5", "6.6.0", "6.7.0"):
            os.makedirs(os.path.join(self.root, v, "bin"))
        prune_versions(self.root, keep=["6.7.0", "6.6.0"])
        self.assertEqual(sorted(os.listdir(self.root)), ["6.6.0", "6.7.0"])

    def test_remove_all(self):
        os.makedirs(os.path.join(self.root, "6.6.0", "bin"))
        remove_all(self.root)
        self.assertFalse(os.path.exists(self.root))
        remove_all(self.root)  # idempotent


if __name__ == "__main__":
    unittest.main()
