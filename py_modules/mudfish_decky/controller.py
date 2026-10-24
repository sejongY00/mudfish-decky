"""Connect/disconnect orchestration and the state contract the panel renders.

The core tunnel is only ever started from connect() (or re-applied by set_node() while already on);
state(), prepare(), resume handling and shutdown must never start it, because Full VPN traffic is
billed per GB. Every path that may leave a tunnel behind goes through _teardown().
"""
import dataclasses
import logging
import threading
import time
from typing import Optional

from .client import AuthError, SigninError
from .nodes import Node, japan_nodes, pick_auto
from .routes import host_routes, leftover_routes

MSG_RELOGIN = "데스크탑 모드에서 미꾸라지(127.0.0.1:8282)에 '로그인 기억하기'로 다시 로그인하세요"
MSG_RTT = "노드 핑을 측정하는 중이에요. 잠시 후 다시 켜 주세요"
MSG_TIMEOUT = "30초 안에 연결되지 않아 연결을 취소했어요"
MSG_MISSING = "데스크탑 모드에서 미꾸라지를 설치하세요 (docs.mudfish.net Steam Deck 가이드)"
MSG_STILL_UP = "터널이 아직 남아 있어요. 끄기를 다시 눌러 주세요"
MSG_NO_RESPONSE = "미꾸라지가 응답하지 않아요. 터널이 남아 있을 수 있으니 끄기를 눌러 주세요"
MSG_SLEEP = "절전에서 깨어나 VPN을 껐어요. 필요하면 다시 켜 주세요"
MSG_LOGGED_IN = "로그인됐어요. 이제 켤 수 있어요"
MSG_NO_LAN = "와이파이 주소를 찾지 못해 휴대폰 로그인을 열 수 없어요"

CONNECT_TIMEOUT = 30
DISCONNECT_TIMEOUT = 10
PUBLIC_IP_TTL = 30
RTT_TTL = 600          # cached pings older than this are ignored for the auto pick
RESUME_JUMP = 3.0      # seconds of suspended time that count as a sleep/resume

log = logging.getLogger("mudfish_decky")


class Controller:
    def __init__(self, client, system, store, clock=time.time, sleep=time.sleep, relay_factory=None):
        self.client = client
        self.system = system
        self.store = store
        self.clock = clock
        self.sleep = sleep
        self.relay_factory = relay_factory
        self._lock = threading.Lock()
        self._error: Optional[str] = None
        self._notice: Optional[str] = None
        self._need_login = False
        self._failed_jwt: Optional[str] = None
        self._relay = None
        self._relay_url: Optional[str] = None
        self._static: Optional[list] = None
        self._ip_cache = (0.0, None)
        self._sleep_offset: Optional[float] = None

    # ---- public API -------------------------------------------------------------------------

    def state(self) -> dict:
        with self._lock:
            return self._state()

    def prepare(self) -> None:
        """Plugin load: bring up the idle launcher and sign in so the node list is ready. Never connects."""
        with self._lock:
            installed = self.system.find_mudfish()
            if not installed:
                return
            try:
                st = self._signed_in(installed)
                self._static_nodes(st)
            except SigninError as e:
                log.warning("prepare: saved login rejected: %s", e)
                self._error = MSG_RELOGIN
                self._mark_need_login()
            except Exception as e:
                log.warning("prepare: %s", e)

    def nodes(self) -> list:
        with self._lock:
            self._refresh_rtts()
            return [dataclasses.asdict(n) for n in self._jp_nodes()]

    def connect(self) -> dict:
        with self._lock:
            self._error = self._notice = None
            installed = self.system.find_mudfish()
            if not installed:
                return self._state()
            started = False
            try:
                st = self._signed_in(installed)
                self._need_login = False
                if self._is_on(st):
                    return self._state()
                self._refresh_rtts()
                node = self._target_node()
                if node is None:
                    return self._fail(MSG_RTT)
                self._with_auth_retry(st, lambda s: self._apply_sid(s, node.sid))
                self.store.update(routes_before=sorted(host_routes(self.system.route_text())), active_sid=node.sid)
                started = True
                self.client.start()
                if not self._wait(lambda: self._is_on(self.client.status()), CONNECT_TIMEOUT):
                    return self._fail(MSG_TIMEOUT if self._teardown() else MSG_STILL_UP)
                self.store.update(connected_since=self.clock())
            except SigninError:
                return self._abort(started, MSG_RELOGIN)
            except Exception as e:
                log.exception("connect failed")
                return self._abort(started, f"연결 실패: {e}")
            return self._state()

    def disconnect(self) -> dict:
        with self._lock:
            self._error = self._notice = None
            if not self._teardown():
                return self._fail(MSG_STILL_UP)
            return self._state()

    def set_node(self, choice: str) -> dict:
        with self._lock:
            self._error = self._notice = None
            try:
                if choice == "auto":
                    self.store.update(node_mode="auto", manual_sid=None)
                else:
                    self.store.update(node_mode="manual", manual_sid=int(choice))
                st = self.client.status()
                if self._is_on(st):
                    self._reapply(st)
            except SigninError:
                self._mark_need_login()
                return self._fail(MSG_RELOGIN)
            except Exception as e:
                log.exception("node change failed")
                return self._fail(f"노드 변경 실패: {e}")
            return self._state()

    def check_resume(self, offset: float) -> bool:
        """Feed boottime-minus-monotonic; a jump means the Deck slept. Then any tunnel is torn down,
        because NetworkManager drops Mudfish's relay route on wake and the tunnel black-holes traffic."""
        with self._lock:
            prev, self._sleep_offset = self._sleep_offset, offset
            if prev is None or offset - prev <= RESUME_JUMP:
                return False
            if self._tunnel_present():
                log.info("resume detected; turning VPN off")
                self._error = None
                self._notice = MSG_SLEEP if self._teardown() else None
                if self._notice is None:
                    self._error = MSG_STILL_UP
            return True

    def start_login(self) -> dict:
        """Open the short-lived LAN relay to the launcher UI; the panel shows its URL as a QR code."""
        with self._lock:
            if self._relay is not None and self._relay.active:
                return self._state()
            ip = self.system.lan_ip()
            if not ip or self.relay_factory is None:
                self._notice = MSG_NO_LAN
                return self._state()
            relay = self.relay_factory()
            port = relay.start()
            self._relay = relay
            self._relay_url = f"http://{ip}:{port}/_mfd/{relay.token}"
            log.info("login relay open on %s:%d for %ss", ip, port, int(relay.expires_at - self.clock()))
            return self._state()

    def stop_login(self) -> dict:
        with self._lock:
            self._close_relay()
            return self._state()

    def shutdown(self) -> None:
        """Plugin unload (Deck shutdown/restart, Decky restart): never leave a tunnel or relay behind."""
        with self._lock:
            self._close_relay()
            if self._tunnel_present():
                log.info("unload; turning VPN off")
                self._teardown()

    # ---- internals ----------------------------------------------------------------------------

    def _fail(self, message: str) -> dict:
        self._error = message
        return self._state()

    def _mark_need_login(self) -> None:
        """Remember which session failed so state() can tell when a new login (e.g. from the phone) lands."""
        self._need_login = True
        try:
            st = self.client.status()
            self._failed_jwt = st.get("jwt") if st.get("isSignedIn") else None
        except Exception:
            self._failed_jwt = None

    def _abort(self, started: bool, message: str) -> dict:
        if message == MSG_RELOGIN:
            self._mark_need_login()
        if started and not self._teardown():
            message = MSG_STILL_UP
        return self._fail(message)

    def _track_login(self, st: Optional[dict]) -> None:
        """Drop an expired relay; once a new session appears after a failed login, close the relay."""
        if self._relay is not None and not self._relay.active:
            self._close_relay()
        if not (self._need_login and st and st.get("isSignedIn") and st.get("jwt")):
            return
        if st["jwt"] == self._failed_jwt:
            return
        self._need_login = False
        self._failed_jwt = None
        if self._error == MSG_RELOGIN:
            self._error = None
        self._close_relay()
        self._notice = MSG_LOGGED_IN

    def _close_relay(self) -> None:
        if self._relay is not None:
            self._relay.stop()
        self._relay = self._relay_url = None

    def _wait(self, cond, seconds) -> bool:
        for _ in range(seconds):
            if cond():
                return True
            self.sleep(1)
        return cond()

    def _teardown(self) -> bool:
        """Stop the core, confirm tap0 is gone, remove the node routes Mudfish left, clear session state.
        Returns False (keeping the route snapshot for a retry) when the tunnel is still up."""
        try:
            self.client.stop()
        except Exception as e:
            log.warning("stop failed: %s", e)
        if not self._wait(lambda: not self.system.tap_up(), DISCONNECT_TIMEOUT):
            return False
        before = self.store.load().get("routes_before")
        try:
            lines = leftover_routes(set(before) if before is not None else None, self.system.route_text())
            if lines:
                log.info("removing %d leftover node routes", self.system.delete_routes(lines))
        except Exception as e:
            log.warning("route cleanup failed: %s", e)
        self.store.update(routes_before=None, connected_since=None, active_sid=None)
        self._ip_cache = (0.0, None)
        return True

    def _is_on(self, st: dict) -> bool:
        return bool(st.get("core_running") and st.get("client_ready") and self.system.tap_up())

    def _tunnel_present(self) -> bool:
        if self.system.tap_up():
            return True
        try:
            return bool(self.client.status().get("core_running"))
        except Exception:
            return False

    def _signed_in(self, installed) -> dict:
        self.system.ensure_daemon(installed[0], self.daemon_up)
        return self.client.ensure_signed_in()

    def daemon_up(self) -> bool:
        try:
            self.client.status()
            return True
        except Exception:
            return False

    def _with_auth_retry(self, st: dict, fn):
        """Run a cloud call; if the daemon's jwt was rejected, force a fresh signin once and retry."""
        try:
            return fn(st)
        except AuthError:
            return fn(self.client.ensure_signed_in(force=True))

    def _refresh_rtts(self) -> None:
        try:
            rtts = self.client.rtts()
        except Exception:
            rtts = {}
        if rtts:
            self.store.update(rtts={str(k): v for k, v in rtts.items()}, rtts_at=self.clock())

    def _cached_rtts(self) -> dict:
        data = self.store.load()
        if not data.get("rtts") or self.clock() - (data.get("rtts_at") or 0) > RTT_TTL:
            return {}
        return {int(k): v for k, v in data["rtts"].items()}

    def _static_nodes(self, st: Optional[dict] = None) -> list:
        if self._static is None:
            saved = self.store.load().get("static_nodes")
            if saved:
                self._static = saved
            elif st and st.get("isSignedIn") and st.get("jwt"):
                self._static = self._with_auth_retry(st, lambda s: self.client.static_nodes(s["jwt"], s["api_server"]))
                self.store.update(static_nodes=self._static)
        return self._static or []

    def _jp_nodes(self, st: Optional[dict] = None) -> list:
        if st is None:
            try:
                st = self.client.status()
            except Exception:
                st = None
        return japan_nodes(self._static_nodes(st), self._cached_rtts())

    def _find(self, sid: int, nodes: list) -> Node:
        return next((n for n in nodes if n.sid == sid), Node(sid, f"#{sid}", None))

    def _target_node(self) -> Optional[Node]:
        data = self.store.load()
        nodes = self._jp_nodes()
        if data.get("node_mode") == "manual" and data.get("manual_sid"):
            return self._find(int(data["manual_sid"]), nodes)
        return pick_auto(nodes)

    def _apply_sid(self, st: dict, sid: int) -> dict:
        """Point the account's Full VPN node at sid (the cloud value, not status, is authoritative)."""
        conf = self.client.prog_conf(st["jwt"], st["api_server"])
        if conf.get("mudfishFullvpnSid") == sid and not conf.get("mudfishFullvpnVid"):
            return {"need_restart": False, "conf": conf, "changed": False}
        conf.update(mudfishFullvpnSid=sid, mudfishFullvpnVid=0)
        resp = self.client.save_prog_conf(st["jwt"], st["api_server"], conf)
        return {"need_restart": bool(resp.get("need_restart")), "conf": conf, "changed": True}

    def _reapply(self, st: dict) -> None:
        node = self._target_node()
        if node is None:
            return
        st = self.client.ensure_signed_in()
        result = self._with_auth_retry(st, lambda s: self._apply_sid(s, node.sid))
        self.store.update(active_sid=node.sid)
        if not result["changed"]:
            return
        if result["need_restart"]:
            self.client.stop()
            self._wait(lambda: not self.system.tap_up(), DISCONNECT_TIMEOUT)
            self.client.start()
            if not self._wait(lambda: self._is_on(self.client.status()), CONNECT_TIMEOUT):
                raise RuntimeError(MSG_TIMEOUT if self._teardown() else MSG_STILL_UP)
        else:
            self.client.fullvpn_refresh(node.sid, result["conf"].get("mudfishFullvpnExceptions") or "")
        self._ip_cache = (0.0, None)

    def _public_ip(self) -> Optional[dict]:
        at, value = self._ip_cache
        if value is None or self.clock() - at > PUBLIC_IP_TTL:
            value = self.system.public_ip()
            self._ip_cache = (self.clock(), value)
        return value

    def _state(self) -> dict:
        data = self.store.load()
        out = {"phase": "off", "message": None, "node_mode": data.get("node_mode") or "auto", "node": None,
               "ip": None, "country": None, "connected_since": None, "tunnel": False,
               "need_login": False, "login": None}
        if not self.system.find_mudfish():
            out.update(phase="missing", message=MSG_MISSING)
            return out
        try:
            st = self.client.status()
        except Exception:
            st = None
        self._track_login(st)
        out["need_login"] = self._need_login
        if self._relay is not None:
            out["login"] = {"url": self._relay_url, "expires_at": self._relay.expires_at}
        tap = self.system.tap_up()
        on = bool(st) and self._is_on(st)
        out["tunnel"] = tap or bool(st and st.get("core_running"))
        if st:
            self._refresh_rtts()
        if on:
            since = data.get("connected_since")
            if since is None:
                since = self.clock()
                self.store.update(connected_since=since)
            ip = self._public_ip() or {}
            out.update(phase="on", connected_since=since, ip=ip.get("ip"), country=ip.get("country"))
        elif st is None and tap:
            out.update(phase="error", message=MSG_NO_RESPONSE, connected_since=data.get("connected_since"))
        elif st and st.get("core_running"):
            out["phase"] = "connecting"
        elif not out["tunnel"]:
            if data.get("connected_since") is not None:
                self.store.update(connected_since=None)
            self._ip_cache = (0.0, None)
        if out["tunnel"] and not on and data.get("connected_since") is not None:
            out["connected_since"] = data["connected_since"]
        if self._error and not on:
            out.update(phase="error", message=self._error)
        elif self._notice and out["message"] is None:
            out["message"] = self._notice

        nodes = self._jp_nodes(st)
        active = self.store.load().get("active_sid")
        if on and active:
            node = self._find(int(active), nodes)
        elif out["node_mode"] == "manual" and data.get("manual_sid"):
            node = self._find(int(data["manual_sid"]), nodes)
        else:
            node = pick_auto(nodes)
        out["node"] = dataclasses.asdict(node) if node else None
        return out
