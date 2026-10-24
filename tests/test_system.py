import os
import tempfile
import types
import unittest

from mudfish_decky.system import api_base, ensure_daemon, find_mudfish


def make_install(root, version):
    os.makedirs(os.path.join(root, version, "bin"))
    os.makedirs(os.path.join(root, version, "var"))
    open(os.path.join(root, version, "bin", "mudrun-headless"), "w").close()


class SystemTest(unittest.TestCase):
    def test_find_mudfish_picks_highest_version(self):
        with tempfile.TemporaryDirectory() as root:
            for v in ["5.11.0", "6.6.0", "6.10.1"]:
                make_install(root, v)
            os.makedirs(os.path.join(root, "6.99.0"))  # no binary: ignored
            self.assertEqual(find_mudfish(root),
                             (os.path.join(root, "6.10.1", "bin", "mudrun-headless"), os.path.join(root, "6.10.1", "var")))

    def test_find_mudfish_none_when_missing(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(find_mudfish(os.path.join(root, "nope")))

    def test_api_base_reads_ipport(self):
        with tempfile.TemporaryDirectory() as var:
            with open(os.path.join(var, ".ipport"), "w") as f:
                f.write("127.0.0.1:9123")
            self.assertEqual(api_base(var), "http://127.0.0.1:9123")

    def test_api_base_default(self):
        with tempfile.TemporaryDirectory() as var:
            self.assertEqual(api_base(var), "http://127.0.0.1:8282")

    def test_lan_ip_from_route_get(self):
        from mudfish_decky.system import lan_ip
        out = "1.1.1.1 via 192.168.1.1 dev wlan0 src 192.168.1.50 uid 0 \n    cache \n"
        self.assertEqual(lan_ip(run=lambda cmd, **kw: types.SimpleNamespace(stdout=out, returncode=0)),
                         "192.168.1.50")

    def test_lan_ip_none_without_route(self):
        from mudfish_decky.system import lan_ip
        self.assertIsNone(lan_ip(run=lambda cmd, **kw: types.SimpleNamespace(stdout="", returncode=2)))

    def test_sleep_offset_is_boottime_minus_monotonic(self):
        from mudfish_decky.system import sleep_offset
        clocks = {"boot": 500.0, "mono": 420.0}
        self.assertEqual(sleep_offset(lambda c: clocks["boot"] if c == "boot" else clocks["mono"],
                                      boot="boot", mono="mono"), 80.0)

    def test_ensure_daemon_noop_when_up(self):
        calls = []
        ensure_daemon("/bin/x", lambda: True, run=lambda cmd, **kw: calls.append(cmd))
        self.assertEqual(calls, [])

    def test_ensure_daemon_starts_transient_unit(self):
        calls, ups = [], iter([False, False, True])

        def run(cmd, **kw):
            calls.append(cmd)
            return types.SimpleNamespace(returncode=0)

        ensure_daemon("/opt/mudfish/6.6.0/bin/mudrun-headless", lambda: next(ups), run=run, sleep=lambda s: None)
        self.assertEqual(calls, [["systemd-run", "--unit=mudfish-decky", "--collect",
                                  "/opt/mudfish/6.6.0/bin/mudrun-headless", "-B"]])


if __name__ == "__main__":
    unittest.main()
