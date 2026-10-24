"""Connect/disconnect orchestration and the state contract the panel renders.

The core tunnel is only ever started from connect() (or re-applied by set_node() while already on);
state() and plugin load must never start it, because Full VPN traffic is billed per GB.
"""
import dataclasses
import logging
import threading
import time
from typing import Optional

from .client import SigninError
from .nodes import Node, japan_nodes, pick_auto
from .routes import host_routes, leftover_routes

MSG_RELOGIN = "데스크탑 모드에서 미꾸라지(127.0.0.1:8282)에 '로그인 기억하기'로 다시 로그인하세요"
MSG_RTT = "노드 핑을 측정하는 중이에요. 잠시 후 다시 켜 주세요"
MSG_TIMEOUT = "30초 안에 연결되지 않아 연결을 취소했어요"
MSG_MISSING = "데스크탑 모드에서 미꾸라지를 설치하세요 (docs.mudfish.net Steam Deck 가이드)"

CONNECT_TIMEOUT = 30
DISCONNECT_TIMEOUT = 10
PUBLIC_IP_TTL = 30

log = logging.getLogger("mudfish_decky")


class Controller:
    def __init__(self, client, system, store, clock=time.time, sleep=time.sleep):
        self.client = client
        self.system = system
        self.store = store
        self.clock = clock
        self.sleep = sleep
        self._lock = threading.Lock()
        self._error: Optional[str] = None
        self._static: Optional[list] = None
        self._ip_cache = (0.0, None)

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
            except Exception as e:
                log.warning("prepare: %s", e)

    def nodes(self) -> list:
        with self._lock:
            self._refresh_rtts()
            return [dataclasses.asdict(n) for n in self._jp_nodes()]

    def connect(self) -> dict:
        with self._lock:
            self._error = None
            installed = self.system.find_mudfish()
            if not installed:
                return self._state()
            try:
                st = self._signed_in(installed)
                if self._is_on(st):
                    return self._state()
                self._refresh_rtts()
                node = self._target_node()
                if node is None:
                    return self._fail(MSG_RTT)
                self._apply_sid(st, node.sid)
                self.store.update(routes_before=sorted(host_routes(self.system.route_text())), active_sid=node.sid)
                self.client.start()
                if not self._wait(lambda: self._is_on(self.client.status()), CONNECT_TIMEOUT):
                    self.client.stop()
                    return self._fail(MSG_TIMEOUT)
                self.store.update(connected_since=self.clock())
            except SigninError:
                return self._fail(MSG_RELOGIN)
            except Exception as e:
                log.exception("connect failed")
                return self._fail(f"연결 실패: {e}")
            return self._state()

    def disconnect(self) -> dict:
        with self._lock:
            self._error = None
            try:
                self.client.stop()
                self._wait(lambda: not self.system.tap_up(), DISCONNECT_TIMEOUT)
            except Exception as e:
                log.exception("disconnect failed")
                return self._fail(f"해제 실패: {e}")
            before = self.store.load().get("routes_before")
            lines = leftover_routes(set(before) if before is not None else None, self.system.route_text())
            if lines:
                log.info("removing %d leftover node routes", self.system.delete_routes(lines))
            self.store.update(routes_before=None, connected_since=None, active_sid=None)
            return self._state()

    def set_node(self, choice: str) -> dict:
        with self._lock:
            self._error = None
            if choice == "auto":
                self.store.update(node_mode="auto", manual_sid=None)
            else:
                self.store.update(node_mode="manual", manual_sid=int(choice))
            try:
                st = self.client.status()
                if self._is_on(st):
                    self._reapply(st)
            except SigninError:
                return self._fail(MSG_RELOGIN)
            except Exception as e:
                log.exception("node change failed")
                return self._fail(f"노드 변경 실패: {e}")
            return self._state()

    # ---- internals ----------------------------------------------------------------------------

    def _fail(self, message: str) -> dict:
        self._error = message
        return self._state()

    def _wait(self, cond, seconds) -> bool:
        for _ in range(seconds):
            if cond():
                return True
            self.sleep(1)
        return cond()

    def _is_on(self, st: dict) -> bool:
        return bool(st.get("core_running") and st.get("client_ready") and self.system.tap_up())

    def _signed_in(self, installed) -> dict:
        self.system.ensure_daemon(installed[0], self.daemon_up)
        return self.client.ensure_signed_in()

    def daemon_up(self) -> bool:
        try:
            self.client.status()
            return True
        except Exception:
            return False

    def _refresh_rtts(self) -> dict:
        try:
            rtts = self.client.rtts()
        except Exception:
            rtts = {}
        if rtts:
            self.store.update(rtts={str(k): v for k, v in rtts.items()})
            return rtts
        return {int(k): v for k, v in (self.store.load().get("rtts") or {}).items()}

    def _cached_rtts(self) -> dict:
        return {int(k): v for k, v in (self.store.load().get("rtts") or {}).items()}

    def _static_nodes(self, st: Optional[dict] = None) -> list:
        if self._static is None:
            saved = self.store.load().get("static_nodes")
            if saved:
                self._static = saved
            elif st and st.get("isSignedIn") and st.get("jwt"):
                self._static = self.client.static_nodes(st["jwt"], st["api_server"])
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
        result = self._apply_sid(st, node.sid)
        self.store.update(active_sid=node.sid)
        if not result["changed"]:
            return
        if result["need_restart"]:
            self.client.stop()
            self._wait(lambda: not self.system.tap_up(), DISCONNECT_TIMEOUT)
            self.client.start()
            if not self._wait(lambda: self._is_on(self.client.status()), CONNECT_TIMEOUT):
                self.client.stop()
                raise RuntimeError(MSG_TIMEOUT)
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
               "ip": None, "country": None, "connected_since": None}
        if not self.system.find_mudfish():
            out.update(phase="missing", message=MSG_MISSING)
            return out
        try:
            st = self.client.status()
        except Exception:
            st = None
        if st:
            self._refresh_rtts()
        on = bool(st) and self._is_on(st)
        if on:
            since = data.get("connected_since")
            if since is None:
                since = self.clock()
                self.store.update(connected_since=since)
            ip = self._public_ip() or {}
            out.update(phase="on", connected_since=since, ip=ip.get("ip"), country=ip.get("country"))
        elif st and st.get("core_running"):
            out["phase"] = "connecting"
        else:
            if data.get("connected_since") is not None:
                self.store.update(connected_since=None)
            self._ip_cache = (0.0, None)
        if self._error and not on:
            out.update(phase="error", message=self._error)

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
