import os
import tempfile
import unittest

from mudfish_decky.client import AuthError, SigninError
from mudfish_decky.controller import (MSG_MISSING, MSG_NO_RESPONSE, MSG_RELOGIN, MSG_RTT, MSG_SLEEP, MSG_STILL_UP,
                                      MSG_TIMEOUT, Controller)
from mudfish_decky.store import Store
from tests.test_nodes import STATIC

BEFORE = "default via 192.168.1.1 dev wlan0 proto dhcp src 192.168.1.50 metric 600\n"
NEW_ROUTES = "1.201.174.247 via 192.168.1.1 dev wlan0\n2.58.243.110 via 192.168.1.1 dev wlan0\n"


class FakeSystem:
    def __init__(self):
        self.installed = True
        self.tap = False
        self.routes = BEFORE
        self.deleted = []
        self.daemon_calls = 0
        self.ip = {"ip": "13.73.234.162", "country": "JP"}

    def find_mudfish(self):
        return ("/opt/mudfish/6.6.0/bin/mudrun-headless", "/opt/mudfish/6.6.0/var") if self.installed else None

    def ensure_daemon(self, bin_path, is_up):
        self.daemon_calls += 1

    def tap_up(self):
        return self.tap

    def route_text(self):
        return self.routes

    def delete_routes(self, lines):
        self.deleted.extend(lines)
        return len(lines)

    def public_ip(self):
        return self.ip


class FakeClient:
    def __init__(self, system):
        self.system = system
        self.st = {"status": 200, "isSignedIn": True, "core_running": False, "core_ready": False,
                   "client_ready": False, "jwt": "JWT", "api_server": "api.mudfish.net"}
        self.signin_error = None
        self.rtt_map = {9: 38.5, 11: 31.0}
        self.conf = {"mudfishFullvpnSid": 0, "mudfishFullvpnVid": 0, "mudfishFullvpnExceptions": "", "mudfishMtu": 1350}
        self.saved = []
        self.start_calls = 0
        self.stop_calls = 0
        self.refresh_calls = []
        self.need_restart = True
        self.ready_on_start = True

    def status(self):
        return dict(self.st)

    def ensure_signed_in(self, force=False):
        if self.signin_error:
            raise self.signin_error
        return dict(self.st)

    def start(self):
        self.start_calls += 1
        self.st["core_running"] = True
        if self.ready_on_start:
            self.st.update(core_ready=True, client_ready=True)
            self.system.tap = True
            self.system.routes = BEFORE + NEW_ROUTES

    def stop(self):
        self.stop_calls += 1
        self.st.update(core_running=False, core_ready=False, client_ready=False)
        self.system.tap = False

    def rtts(self):
        return dict(self.rtt_map)

    def static_nodes(self, jwt, api):
        return STATIC

    def prog_conf(self, jwt, api):
        return dict(self.conf)

    def save_prog_conf(self, jwt, api, conf):
        self.saved.append(dict(conf))
        self.conf = dict(conf)
        return {"status": 200, "need_restart": self.need_restart}

    def fullvpn_refresh(self, sid, exceptions):
        self.refresh_calls.append((sid, exceptions))


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "settings.json")
        self.system = FakeSystem()
        self.client = FakeClient(self.system)
        self.now = 1000.0

    def tearDown(self):
        self.tmp.cleanup()

    def make(self):
        return Controller(self.client, self.system, Store(self.path), clock=lambda: self.now, sleep=lambda s: None)

    def test_state_missing_when_not_installed(self):
        self.system.installed = False
        st = self.make().state()
        self.assertEqual(st["phase"], "missing")
        self.assertEqual(st["message"], MSG_MISSING)

    def test_state_off_never_starts_core(self):
        st = self.make().state()
        self.assertEqual(st["phase"], "off")
        self.assertEqual(self.client.start_calls, 0)

    def test_state_off_shows_auto_pick(self):
        st = self.make().state()
        self.assertEqual(st["node_mode"], "auto")
        self.assertEqual(st["node"], {"sid": 11, "label": "Osaka - SakuraNet 4", "rtt": 31.0})

    def test_connect_auto_picks_lowest_and_saves_sid(self):
        st = self.make().connect()
        self.assertEqual(self.client.conf["mudfishFullvpnSid"], 11)
        self.assertEqual(self.client.conf["mudfishFullvpnVid"], 0)
        self.assertEqual(self.client.conf["mudfishMtu"], 1350)
        self.assertEqual(st["phase"], "on")
        self.assertEqual(st["connected_since"], 1000.0)
        self.assertEqual((st["ip"], st["country"]), ("13.73.234.162", "JP"))

    def test_connect_skips_save_when_sid_unchanged(self):
        self.client.conf["mudfishFullvpnSid"] = 11
        self.make().connect()
        self.assertEqual(self.client.saved, [])

    def test_connect_auto_without_rtts_does_not_start(self):
        self.client.rtt_map = {}
        st = self.make().connect()
        self.assertEqual(st["phase"], "error")
        self.assertEqual(st["message"], MSG_RTT)
        self.assertEqual(self.client.start_calls, 0)

    def test_connect_uses_cached_rtts_when_measuring(self):
        c = self.make()
        c.state()  # caches rtts
        self.client.rtt_map = {}  # mid-round: endpoint has no rtts
        self.assertEqual(self.make().connect()["phase"], "on")

    def test_connect_signin_failure_shows_relogin(self):
        self.client.signin_error = SigninError("401")
        st = self.make().connect()
        self.assertEqual(st["phase"], "error")
        self.assertEqual(st["message"], MSG_RELOGIN)
        self.assertEqual(self.client.start_calls, 0)

    def test_connect_timeout_stops_core(self):
        self.client.ready_on_start = False
        st = self.make().connect()
        self.assertEqual(self.client.stop_calls, 1)
        self.assertEqual(st["phase"], "error")
        self.assertEqual(st["message"], MSG_TIMEOUT)

    def test_connect_manual_uses_saved_sid(self):
        c = self.make()
        c.set_node("9")
        c.connect()
        self.assertEqual(self.client.conf["mudfishFullvpnSid"], 9)

    def test_disconnect_deletes_only_new_routes_and_keeps_sid(self):
        c = self.make()
        c.connect()
        saves = len(self.client.saved)
        st = c.disconnect()
        self.assertEqual(self.system.deleted,
                         ["1.201.174.247 via 192.168.1.1 dev wlan0", "2.58.243.110 via 192.168.1.1 dev wlan0"])
        self.assertEqual(len(self.client.saved), saves)
        self.assertEqual(self.client.conf["mudfishFullvpnSid"], 11)
        self.assertEqual(st["phase"], "off")
        self.assertIsNone(Store(self.path).load().get("connected_since"))

    def test_disconnect_without_snapshot_deletes_nothing(self):
        self.client.st.update(core_running=True, client_ready=True)
        self.system.tap = True
        self.system.routes = BEFORE + NEW_ROUTES
        self.make().disconnect()
        self.assertEqual(self.system.deleted, [])

    def test_state_on_survives_restart_uses_saved_since(self):
        Store(self.path).save({"connected_since": 100.0})
        self.client.st.update(core_running=True, core_ready=True, client_ready=True)
        self.system.tap = True
        st = self.make().state()
        self.assertEqual(st["phase"], "on")
        self.assertEqual(st["connected_since"], 100.0)
        self.assertEqual(self.client.start_calls, 0)

    def test_state_on_without_saved_since_starts_clock_now(self):
        self.client.st.update(core_running=True, core_ready=True, client_ready=True)
        self.system.tap = True
        self.assertEqual(self.make().state()["connected_since"], 1000.0)

    def test_state_connecting_when_core_running_not_ready(self):
        self.client.st.update(core_running=True)
        self.assertEqual(self.make().state()["phase"], "connecting")

    def test_set_node_while_off_only_saves_choice(self):
        st = self.make().set_node("9")
        self.assertEqual(self.client.saved, [])
        self.assertEqual(Store(self.path).load()["manual_sid"], 9)
        self.assertEqual(st["node_mode"], "manual")
        self.assertEqual(st["node"]["sid"], 9)

    def test_set_node_while_on_refreshes(self):
        c = self.make()
        c.connect()
        self.client.need_restart = False
        st = c.set_node("9")
        self.assertEqual(self.client.refresh_calls, [(9, "")])
        self.assertEqual(self.client.start_calls, 1)
        self.assertEqual(st["node"]["sid"], 9)

    def test_set_node_while_on_restarts_when_needed(self):
        c = self.make()
        c.connect()
        self.client.need_restart = True
        c.set_node("9")
        self.assertEqual((self.client.stop_calls, self.client.start_calls), (1, 2))

    def test_set_node_back_to_auto(self):
        c = self.make()
        c.set_node("9")
        st = c.set_node("auto")
        self.assertEqual(st["node_mode"], "auto")
        self.assertEqual(st["node"]["sid"], 11)

    # ---- final review fixes ------------------------------------------------------------------

    def test_connect_status_error_after_start_tears_down(self):
        real_start = self.client.start

        def start():
            real_start()
            self.client.status = lambda: (_ for _ in ()).throw(OSError("launcher busy"))

        self.client.start = start
        st = self.make().connect()
        self.assertEqual(self.client.stop_calls, 1)
        self.assertEqual(st["phase"], "error")
        self.assertEqual(len(self.system.deleted), 2)

    def test_connect_timeout_cleans_routes_and_store(self):
        self.client.ready_on_start = False
        self.client.start = self._start_adding_routes_not_ready()
        self.make().connect()
        self.assertEqual(len(self.system.deleted), 2)
        data = Store(self.path).load()
        self.assertIsNone(data.get("routes_before"))
        self.assertIsNone(data.get("active_sid"))

    def _start_adding_routes_not_ready(self):
        def start():
            self.client.start_calls += 1
            self.client.st["core_running"] = True
            self.system.routes = BEFORE + NEW_ROUTES
        return start

    def test_disconnect_keeps_snapshot_when_tap_stays_up(self):
        c = self.make()
        c.connect()
        real_stop = self.client.stop

        def stop():
            real_stop()
            self.system.tap = True  # tunnel did not go away

        self.client.stop = stop
        st = c.disconnect()
        self.assertEqual(st["phase"], "error")
        self.assertEqual(st["message"], MSG_STILL_UP)
        self.assertTrue(st["tunnel"])
        data = Store(self.path).load()
        self.assertIsNotNone(data.get("routes_before"))
        self.assertEqual(data.get("connected_since"), 1000.0)
        self.assertEqual(self.system.deleted, [])

    def test_state_reports_tunnel_when_core_stuck(self):
        self.client.st.update(core_running=True)
        st = self.make().state()
        self.assertEqual(st["phase"], "connecting")
        self.assertTrue(st["tunnel"])

    def test_state_tunnel_false_when_off(self):
        self.assertFalse(self.make().state()["tunnel"])

    def test_state_status_failure_with_tap_up_is_error_not_off(self):
        Store(self.path).save({"connected_since": 100.0})
        self.system.tap = True
        self.client.status = lambda: (_ for _ in ()).throw(OSError("no answer"))
        st = self.make().state()
        self.assertEqual(st["phase"], "error")
        self.assertEqual(st["message"], MSG_NO_RESPONSE)
        self.assertTrue(st["tunnel"])
        self.assertEqual(Store(self.path).load()["connected_since"], 100.0)

    def test_connect_resigns_once_when_cloud_rejects_jwt(self):
        calls = []
        real_prog_conf = self.client.prog_conf

        def prog_conf(jwt, api):
            calls.append(jwt)
            if len(calls) == 1:
                raise AuthError("graphql returned no user")
            return real_prog_conf(jwt, api)

        forced = []
        self.client.prog_conf = prog_conf
        self.client.ensure_signed_in = lambda force=False: forced.append(force) or dict(self.client.st)
        st = self.make().connect()
        self.assertEqual(st["phase"], "on")
        self.assertIn(True, forced)
        self.assertEqual(len(calls), 2)

    def test_connect_stale_rtt_cache_is_ignored(self):
        Store(self.path).save({"rtts": {"11": 31.0}, "rtts_at": 1000.0 - 601})
        self.client.rtt_map = {}
        st = self.make().connect()
        self.assertEqual(st["message"], MSG_RTT)
        self.assertEqual(self.client.start_calls, 0)

    # ---- sleep / shutdown --------------------------------------------------------------------

    def test_resume_jump_turns_tunnel_off_with_notice(self):
        c = self.make()
        c.connect()
        self.assertFalse(c.check_resume(5.0))   # first sample only sets the baseline
        self.assertFalse(c.check_resume(5.5))   # small drift: not a resume
        self.assertTrue(c.check_resume(65.5))   # suspended ~60s
        st = c.state()
        self.assertEqual(self.client.stop_calls, 1)
        self.assertEqual(st["phase"], "off")
        self.assertEqual(st["message"], MSG_SLEEP)
        self.assertEqual(len(self.system.deleted), 2)

    def test_resume_while_off_does_nothing(self):
        c = self.make()
        c.check_resume(5.0)
        c.check_resume(100.0)
        self.assertEqual(self.client.stop_calls, 0)
        self.assertIsNone(c.state()["message"])

    def test_resume_never_starts_core(self):
        c = self.make()
        c.check_resume(5.0)
        c.check_resume(100.0)
        self.assertEqual(self.client.start_calls, 0)

    def test_notice_cleared_by_next_connect(self):
        c = self.make()
        c.connect()
        c.check_resume(5.0)
        c.check_resume(100.0)
        self.assertIsNone(c.connect()["message"])

    def test_shutdown_turns_tunnel_off(self):
        c = self.make()
        c.connect()
        c.shutdown()
        self.assertEqual(self.client.stop_calls, 1)
        self.assertEqual(len(self.system.deleted), 2)
        self.assertIsNone(Store(self.path).load().get("connected_since"))

    def test_shutdown_while_off_does_not_call_stop(self):
        self.make().shutdown()
        self.assertEqual(self.client.stop_calls, 0)

    def test_prepare_signs_in_and_caches_nodes_without_starting(self):
        self.client.st["isSignedIn"] = False
        signed = []
        self.client.ensure_signed_in = lambda: signed.append(1) or dict(self.client.st, isSignedIn=True)
        c = self.make()
        c.prepare()
        self.assertEqual(self.system.daemon_calls, 1)
        self.assertEqual(signed, [1])
        self.assertEqual(self.client.start_calls, 0)
        self.assertEqual([n["sid"] for n in Store(self.path).load()["static_nodes"]], [9, 11, 46, 300])

    def test_prepare_tolerates_signin_failure(self):
        self.client.signin_error = SigninError("401")
        self.make().prepare()
        self.assertEqual(self.client.start_calls, 0)

    def test_nodes_lists_japan_by_ping(self):
        self.assertEqual([n["sid"] for n in self.make().nodes()], [11, 9, 46])


if __name__ == "__main__":
    unittest.main()
