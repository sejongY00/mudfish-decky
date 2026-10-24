import unittest

from mudfish_decky.nodes import japan_nodes, pick_auto, rtts_from_response

STATIC = [
    {"sid": 9, "location": "JP Asia (Tokyo - Linode3 IDC)"},
    {"sid": 11, "location": "JP Asia (Osaka - SakuraNet 4)"},
    {"sid": 46, "location": "JP Asia (Hokkaido - SakuraNet 6)"},
    {"sid": 300, "location": "US West (Los Angeles - HostUS)"},
]
RESP = {"status": 200, "rtts": [
    {"sid": 9, "rttavg": 38.5, "success": 4, "failure": 0},
    {"sid": 11, "rttavg": 31.0, "success": 4, "failure": 0},
    {"sid": 46, "rttavg": 0.0, "success": 0, "failure": 4},
    {"sid": 300, "rttavg": 5.0, "success": 4, "failure": 0},
]}


class NodesTest(unittest.TestCase):
    def test_rtts_skip_failed(self):
        self.assertEqual(rtts_from_response(RESP), {9: 38.5, 11: 31.0, 300: 5.0})

    def test_rtts_empty_while_measuring(self):
        self.assertEqual(rtts_from_response({"status": 300, "n_checked": 11}), {})

    def test_japan_only_sorted_by_rtt_unmeasured_last(self):
        nodes = japan_nodes(STATIC, rtts_from_response(RESP))
        self.assertEqual([n.sid for n in nodes], [11, 9, 46])
        self.assertEqual(nodes[0].label, "Osaka - SakuraNet 4")
        self.assertIsNone(nodes[2].rtt)

    def test_pick_auto_lowest(self):
        self.assertEqual(pick_auto(japan_nodes(STATIC, rtts_from_response(RESP))).sid, 11)

    def test_pick_auto_none_without_rtts(self):
        self.assertIsNone(pick_auto(japan_nodes(STATIC, {})))


if __name__ == "__main__":
    unittest.main()
