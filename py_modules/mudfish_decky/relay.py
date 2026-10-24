"""Short-lived LAN relay to the Mudfish launcher UI so a phone can log in by scanning a QR code.

The launcher only listens on 127.0.0.1. While a login is pending we open a random LAN port that
forwards raw TCP to it, guarded by a one-time token: the first client to request /_mfd/<token> becomes
the only client allowed through; everyone else gets 403. The relay closes itself after `ttl` seconds.
"""
import logging
import secrets
import socket
import threading
import time
from typing import Optional

TOKEN_PREFIX = "/_mfd/"
PEEK_TIMEOUT = 10

log = logging.getLogger("mudfish_decky")

_REDIRECT = b"HTTP/1.1 302 Found\r\nLocation: /\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
_FORBIDDEN = b"HTTP/1.1 403 Forbidden\r\nContent-Length: 9\r\nConnection: close\r\n\r\nForbidden"


def parse_request_path(data: bytes) -> Optional[str]:
    """Path from an HTTP request line, or None if the first line is incomplete or not HTTP."""
    line, sep, _ = data.partition(b"\r\n")
    if not sep:
        return None
    parts = line.split(b" ")
    if len(parts) != 3 or not parts[2].startswith(b"HTTP/"):
        return None
    try:
        return parts[1].decode("ascii")
    except UnicodeDecodeError:
        return None


class Gate:
    def __init__(self, token: str):
        self.token = token
        self.client: Optional[str] = None
        self._lock = threading.Lock()

    def decide(self, ip: str, path: Optional[str]) -> str:
        is_token = path is not None and path.split("?", 1)[0] == TOKEN_PREFIX + self.token
        with self._lock:
            if self.client is None and is_token:
                self.client = ip
            if ip != self.client:
                return "deny"
            return "authorize" if is_token else "pipe"


def _pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class LoginRelay:
    def __init__(self, target=("127.0.0.1", 8282), ttl: int = 300, clock=time.time):
        self.target = target
        self.ttl = ttl
        self.clock = clock
        self.token = secrets.token_urlsafe(16)
        self.gate = Gate(self.token)
        self.expires_at = 0.0
        self._srv: Optional[socket.socket] = None
        self._stopped = threading.Event()
        self._conns = set()
        self._conns_lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._srv is not None and not self._stopped.is_set() and self.clock() < self.expires_at

    def start(self, host: str = "0.0.0.0") -> int:
        self._srv = socket.create_server((host, 0))
        self._srv.settimeout(1)
        self.expires_at = self.clock() + self.ttl
        threading.Thread(target=self._serve, daemon=True).start()
        return self._srv.getsockname()[1]

    def stop(self) -> None:
        self._stopped.set()
        if self._srv is not None:
            # shutdown() first: close() alone does not stop a listener another thread is blocked on.
            for op in (lambda: self._srv.shutdown(socket.SHUT_RDWR), self._srv.close):
                try:
                    op()
                except OSError:
                    pass
        with self._conns_lock:
            conns, self._conns = self._conns, set()
        for c in conns:
            try:
                c.close()
            except OSError:
                pass

    def _track(self, sock):
        with self._conns_lock:
            self._conns.add(sock)

    def _serve(self):
        while self.active:
            try:
                conn, addr = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._track(conn)
            threading.Thread(target=self._handle, args=(conn, addr[0]), daemon=True).start()
        self.stop()
        log.info("login relay closed")

    def _handle(self, conn, ip):
        try:
            conn.settimeout(PEEK_TIMEOUT)
            path = parse_request_path(conn.recv(4096, socket.MSG_PEEK))
            decision = self.gate.decide(ip, path)
            if decision in ("authorize", "deny"):
                conn.recv(4096)  # consume the request; closing with unread data would send RST
                conn.sendall(_REDIRECT if decision == "authorize" else _FORBIDDEN)
                conn.shutdown(socket.SHUT_WR)
                conn.close()
                if decision == "authorize":
                    log.info("login relay: phone %s authorized", ip)
                return
            conn.settimeout(None)
            upstream = socket.create_connection(self.target, timeout=5)
            upstream.settimeout(None)
            self._track(upstream)
            threading.Thread(target=_pipe, args=(conn, upstream), daemon=True).start()
            _pipe(upstream, conn)
        except OSError:
            try:
                conn.close()
            except OSError:
                pass
