import os
import tempfile
import unittest

from mudfish_decky.client import AuthError, MudfishError, SigninError
from mudfish_decky.controller import (MSG_INSTALLED, MSG_LOGGED_IN, MSG_MISSING, MSG_NO_LAN, MSG_NO_RESPONSE,
                                      MSG_RELOGIN, MSG_REMOVED, MSG_RTT, MSG_SLEEP, MSG_STILL_UP, MSG_TIMEOUT,
                                      MSG_UP_TO_DATE, MSG_UPDATE_NEED_OFF, MSG_UPDATED, Controller)
from mudfish_decky.installer import InstallError
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
        self.lan = "192.168.1.50"
        self.version = "6.6.0"
        self.daemon_bins = []
        self.daemon_stops = 0
        self.nm_removed = 0

    def lan_ip(self):
        return self.lan

    def find_mudfish(self):
        if not self.installed:
            return None
        return (f"/opt/mudfish/{self.version}/bin/mudrun-headless", f"/opt/mudfish/{self.version}/var")

    def version_of(self, bin_path):
        return bin_path.split("/")[3]

    def ensure_daemon(self, bin_path, is_up):
        self.daemon_calls += 1
        self.daemon_bins.append(bin_path)

    def stop_daemon(self, wait=True):
        self.daemon_stops += 1

    def remove_nm_connection(self):
        self.nm_removed += 1

    def tap_up(self):
        return self.tap

    def route_text(self):
        return self.routes

    def delete_routes(self, lines):
        self.deleted.extend(lines)
        return len(lines)

    def public_ip(self):
        return self.ip


class FakeInstaller:
    MUDFISH_ROOT = "/opt/mudfish"

    def __init__(self, system):
        self.system = system
        self.latest = "6.7.0"
        self.calls = []

    def latest_version(self):
        self.calls.append("latest")
        return self.latest

    def download(self, version):
        self.calls.append(("download", version))
        return b"pkg"

    def install_package(self, data, root):
        self.calls.append(("install", root))
        self.system.installed = True
        self.system.version = self.latest
        return self.latest

    def carry_login(self, old_var, new_var):
        self.calls.append(("carry", old_var, new_var))

    def prune_versions(self, root, keep):
        self.calls.append(("prune", sorted(keep)))

    def remove_all(self, root):
        self.calls.append(("remove_all", root))
        self.system.installed = False


class FakeRelay:
    token = "tok"
    expires_at = 1300.0

    def __init__(self):
        self.active = False
        self.started = False
        self.start_calls = 0

    def start(self, host="0.0.0.0"):
        self.started = True
        self.active = True
        self.start_calls += 1
        return 40123

    def stop(self):
        self.active = False


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

    def test_disconnect_deletes_only_new_routes(self):
        c = self.make()
        c.connect()
        st = c.disconnect()
        self.assertEqual(self.system.deleted,
                         ["1.201.174.247 via 192.168.1.1 dev wlan0", "2.58.243.110 via 192.168.1.1 dev wlan0"])
        self.assertEqual(st["phase"], "off")
        self.assertIsNone(Store(self.path).load().get("connected_since"))

    # ---- account Full VPN setting is restored when the tunnel goes down ------------------------

    def test_connect_remembers_original_fullvpn_setting(self):
        self.client.conf.update(mudfishFullvpnSid=0, mudfishFullvpnVid=5)
        self.make().connect()
        self.assertEqual(Store(self.path).load()["fullvpn_restore"], {"sid": 0, "vid": 5})

    def test_disconnect_restores_original_fullvpn_setting(self):
        self.client.conf.update(mudfishFullvpnSid=0, mudfishFullvpnVid=5)
        c = self.make()
        c.connect()
        st = c.disconnect()
        self.assertEqual((self.client.conf["mudfishFullvpnSid"], self.client.conf["mudfishFullvpnVid"]), (0, 5))
        self.assertEqual(self.client.conf["mudfishMtu"], 1350)
        self.assertIsNone(Store(self.path).load().get("fullvpn_restore"))
        self.assertFalse(st["restore_pending"])

    def test_restore_keeps_first_original_across_node_change(self):
        c = self.make()
        c.connect()                       # 0 -> 11
        self.client.need_restart = False
        c.set_node("9")                   # 11 -> 9 while on
        c.disconnect()
        self.assertEqual(self.client.conf["mudfishFullvpnSid"], 0)

    def test_no_restore_when_account_already_on_target_node(self):
        self.client.conf["mudfishFullvpnSid"] = 11
        c = self.make()
        c.connect()
        c.disconnect()
        self.assertEqual(self.client.saved, [])
        self.assertEqual(self.client.conf["mudfishFullvpnSid"], 11)

    def test_restore_failure_stays_pending_and_retries(self):
        c = self.make()
        c.connect()
        real_save = self.client.save_prog_conf

        def failing(jwt, api, conf):
            raise MudfishError("network down")

        self.client.save_prog_conf = failing
        st = c.disconnect()
        self.assertEqual(st["phase"], "off")
        self.assertTrue(st["restore_pending"])
        self.assertEqual(Store(self.path).load()["fullvpn_restore"], {"sid": 0, "vid": 0})
        self.client.save_prog_conf = real_save
        c.retry_restore()
        self.assertEqual(self.client.conf["mudfishFullvpnSid"], 0)
        self.assertFalse(c.state()["restore_pending"])

    def test_retry_restore_waits_while_tunnel_up(self):
        c = self.make()
        c.connect()
        saves = len(self.client.saved)
        c.retry_restore()
        self.assertEqual(len(self.client.saved), saves)
        self.assertEqual(self.client.conf["mudfishFullvpnSid"], 11)

    def test_connect_timeout_restores_original(self):
        self.client.ready_on_start = False
        self.make().connect()
        self.assertEqual(self.client.conf["mudfishFullvpnSid"], 0)

    def test_resume_restores_original(self):
        c = self.make()
        c.connect()
        c.check_resume(5.0)
        c.check_resume(100.0)
        self.assertEqual(self.client.conf["mudfishFullvpnSid"], 0)

    def test_shutdown_restores_original(self):
        c = self.make()
        c.connect()
        c.shutdown()
        self.assertEqual(self.client.conf["mudfishFullvpnSid"], 0)

    def test_uninstall_restores_before_removing_mudfish(self):
        c = self.make_with_installer()
        c.connect()
        order = []
        real_save = self.client.save_prog_conf
        self.client.save_prog_conf = lambda j, a, conf: order.append("restore") or real_save(j, a, conf)
        real_remove = self.installer.remove_all
        self.installer.remove_all = lambda root: order.append("remove") or real_remove(root)
        c.uninstall()
        self.assertEqual(order, ["restore", "remove"])
        self.assertEqual(self.client.conf["mudfishFullvpnSid"], 0)

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

    # ---- phone (QR) login --------------------------------------------------------------------

    def make_with_relay(self):
        self.relay = FakeRelay()
        return Controller(self.client, self.system, Store(self.path), clock=lambda: self.now,
                          sleep=lambda s: None, relay_factory=lambda: self.relay)

    def test_connect_signin_failure_flags_need_login(self):
        self.client.signin_error = SigninError("401")
        self.assertTrue(self.make().connect()["need_login"])

    def test_prepare_signin_failure_flags_need_login(self):
        self.client.signin_error = SigninError("401")
        c = self.make()
        c.prepare()
        st = c.state()
        self.assertTrue(st["need_login"])
        self.assertEqual(st["message"], MSG_RELOGIN)

    def test_prepare_network_failure_does_not_flag_need_login(self):
        self.client.signin_error = OSError("name resolution")
        c = self.make()
        c.prepare()
        self.assertFalse(c.state()["need_login"])

    def test_need_login_false_by_default(self):
        self.assertFalse(self.make().state()["need_login"])

    def test_start_login_exposes_qr_url(self):
        c = self.make_with_relay()
        st = c.start_login()
        self.assertEqual(st["login"], {"url": "http://192.168.1.50:40123/_mfd/tok", "expires_at": 1300.0})
        self.assertTrue(self.relay.started)
        self.assertEqual(self.client.start_calls, 0)

    def test_start_login_reuses_active_relay(self):
        c = self.make_with_relay()
        c.start_login()
        c.start_login()
        self.assertEqual(self.relay.start_calls, 1)

    def test_start_login_without_lan_ip_shows_message(self):
        self.system.lan = None
        st = self.make_with_relay().start_login()
        self.assertIsNone(st["login"])
        self.assertEqual(st["message"], MSG_NO_LAN)
        self.assertFalse(self.relay.started)

    def test_state_closes_relay_after_signin(self):
        self.client.signin_error = SigninError("401")
        self.client.st["isSignedIn"] = False
        c = self.make_with_relay()
        c.connect()
        c.start_login()
        self.client.st["isSignedIn"] = True  # user logged in from the phone
        st = c.state()
        self.assertFalse(self.relay.active)
        self.assertIsNone(st["login"])
        self.assertFalse(st["need_login"])
        self.assertEqual(st["phase"], "off")
        self.assertEqual(st["message"], MSG_LOGGED_IN)

    def test_stop_login_closes_relay(self):
        c = self.make_with_relay()
        c.start_login()
        self.assertIsNone(c.stop_login()["login"])
        self.assertFalse(self.relay.active)

    def test_expired_relay_drops_from_state(self):
        c = self.make_with_relay()
        c.start_login()
        self.relay.active = False
        self.assertIsNone(c.state()["login"])

    def test_shutdown_closes_relay(self):
        c = self.make_with_relay()
        c.start_login()
        c.shutdown()
        self.assertFalse(self.relay.active)

    # ---- install / update / uninstall --------------------------------------------------------

    def make_with_installer(self):
        self.installer = FakeInstaller(self.system)
        return Controller(self.client, self.system, Store(self.path), clock=lambda: self.now,
                          sleep=lambda s: None, installer=self.installer)

    def test_state_reports_versions(self):
        Store(self.path).save({"latest_version": "6.7.0"})
        st = self.make_with_installer().state()
        self.assertEqual(st["mudfish"], {"version": "6.6.0", "latest": "6.7.0"})

    def test_state_missing_reports_no_version(self):
        self.system.installed = False
        st = self.make_with_installer().state()
        self.assertEqual(st["phase"], "missing")
        self.assertIsNone(st["mudfish"]["version"])

    def test_install_downloads_latest_and_starts_daemon_without_connecting(self):
        self.system.installed = False
        st = self.make_with_installer().install()
        self.assertIn(("download", "6.7.0"), self.installer.calls)
        self.assertIn(("install", "/opt/mudfish"), self.installer.calls)
        self.assertEqual(self.system.daemon_bins[-1], "/opt/mudfish/6.7.0/bin/mudrun-headless")
        self.assertEqual(self.client.start_calls, 0)
        self.assertEqual(st["phase"], "off")
        self.assertEqual(st["message"], MSG_INSTALLED.format("6.7.0"))
        self.assertEqual(st["mudfish"]["version"], "6.7.0")

    def test_install_failure_shows_message(self):
        self.system.installed = False
        c = self.make_with_installer()
        self.installer.install_package = lambda data, root: (_ for _ in ()).throw(InstallError("checksum"))
        st = c.install()
        self.assertEqual(st["phase"], "missing")
        self.assertIn("checksum", st["message"])

    def test_update_refused_while_tunnel_up(self):
        c = self.make_with_installer()
        c.connect()
        st = c.update()
        self.assertEqual(st["message"], MSG_UPDATE_NEED_OFF)
        self.assertNotIn(("download", "6.7.0"), self.installer.calls)
        self.assertEqual(st["phase"], "on")

    def test_update_carries_login_restarts_daemon_and_prunes(self):
        c = self.make_with_installer()
        st = c.update()
        self.assertIn(("carry", "/opt/mudfish/6.6.0/var", "/opt/mudfish/6.7.0/var"), self.installer.calls)
        self.assertEqual(self.system.daemon_stops, 1)
        self.assertEqual(self.system.daemon_bins[-1], "/opt/mudfish/6.7.0/bin/mudrun-headless")
        self.assertIn(("prune", ["6.6.0", "6.7.0"]), self.installer.calls)
        self.assertEqual(self.client.start_calls, 0)
        self.assertEqual(st["message"], MSG_UPDATED.format("6.7.0"))

    def test_update_when_already_latest_does_nothing(self):
        self.make_with_installer()
        self.installer.latest = "6.6.0"
        st = Controller(self.client, self.system, Store(self.path), clock=lambda: self.now,
                        sleep=lambda s: None, installer=self.installer).update()
        self.assertEqual(st["message"], MSG_UP_TO_DATE)
        self.assertNotIn(("download", "6.6.0"), self.installer.calls)

    def test_refresh_latest_checks_at_most_daily(self):
        c = self.make_with_installer()
        c.refresh_latest()
        c.refresh_latest()
        self.assertEqual(self.installer.calls.count("latest"), 1)
        self.now += 86401
        c.refresh_latest()
        self.assertEqual(self.installer.calls.count("latest"), 2)
        self.assertEqual(Store(self.path).load()["latest_version"], "6.7.0")

    def test_uninstall_turns_off_and_removes_everything(self):
        c = self.make_with_installer()
        self.relay = FakeRelay()
        c.relay_factory = lambda: self.relay
        c.connect()
        c.start_login()
        st = c.uninstall()
        self.assertEqual(self.client.stop_calls, 1)
        self.assertFalse(self.relay.active)
        self.assertEqual(self.system.daemon_stops, 1)
        self.assertEqual(self.system.nm_removed, 1)
        self.assertIn(("remove_all", "/opt/mudfish"), self.installer.calls)
        self.assertEqual(Store(self.path).load(), {})
        self.assertEqual(st["phase"], "missing")
        self.assertEqual(st["message"], MSG_REMOVED)

    def test_uninstall_when_missing_still_cleans_up(self):
        self.system.installed = False
        c = self.make_with_installer()
        c.uninstall()
        self.assertIn(("remove_all", "/opt/mudfish"), self.installer.calls)
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
