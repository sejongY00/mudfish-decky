import types
import unittest

from mudfish_decky.routes import delete_routes, host_routes, leftover_routes

BEFORE = """default via 192.168.1.1 dev wlan0 proto dhcp src 192.168.1.50 metric 600
192.168.1.0/24 dev wlan0 proto kernel scope link src 192.168.1.50 metric 600
"""
AFTER = BEFORE + """1.201.174.247 via 192.168.1.1 dev wlan0
2.58.243.110 via 192.168.1.1 dev wlan0
10.254.100.5 via 10.254.100.1 dev tap0
"""


class RoutesTest(unittest.TestCase):
    def test_host_routes_excludes_default_prefix_and_proto(self):
        self.assertEqual(host_routes(BEFORE), set())

    def test_host_routes_normalizes_trailing_space(self):
        self.assertEqual(host_routes("1.2.3.4 via 192.168.1.1 dev wlan0 \n"),
                         {"1.2.3.4 via 192.168.1.1 dev wlan0"})

    def test_leftover_routes_only_new_non_tap(self):
        self.assertEqual(leftover_routes(host_routes(BEFORE), AFTER),
                         ["1.201.174.247 via 192.168.1.1 dev wlan0", "2.58.243.110 via 192.168.1.1 dev wlan0"])

    def test_leftover_routes_none_snapshot_deletes_nothing(self):
        self.assertEqual(leftover_routes(None, AFTER), [])

    def test_leftover_routes_keeps_preexisting_host_routes(self):
        before = host_routes(AFTER.replace("2.58.243.110", "9.9.9.9"))
        self.assertNotIn("1.201.174.247 via 192.168.1.1 dev wlan0", leftover_routes(before, AFTER))

    def test_delete_routes_runs_ip_route_del(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return types.SimpleNamespace(returncode=0)

        self.assertEqual(delete_routes(["1.2.3.4 via 192.168.1.1 dev wlan0"], run=run), 1)
        self.assertEqual(calls, [["ip", "route", "del", "1.2.3.4", "via", "192.168.1.1", "dev", "wlan0"]])

    def test_delete_routes_counts_failures_as_not_deleted(self):
        def run(cmd, **kw):
            raise OSError("boom")

        self.assertEqual(delete_routes(["1.2.3.4 via 192.168.1.1 dev wlan0"], run=run), 0)


if __name__ == "__main__":
    unittest.main()
