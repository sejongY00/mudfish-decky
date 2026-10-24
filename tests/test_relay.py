import socket
import threading
import unittest

from mudfish_decky.relay import Gate, LoginRelay, parse_request_path


def http_get(port, path):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(f"GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n".encode())
        chunks = []
        while True:
            data = s.recv(4096)
            if not data:
                break
            chunks.append(data)
    return b"".join(chunks).decode()


class FakeTarget:
    """Minimal HTTP server standing in for the Mudfish launcher."""

    def __init__(self):
        self.srv = socket.create_server(("127.0.0.1", 0))
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            with conn:
                conn.recv(4096)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello")

    def close(self):
        self.srv.close()


class GateTest(unittest.TestCase):
    def test_denies_until_token_seen(self):
        g = Gate("tok")
        self.assertEqual(g.decide("10.0.0.2", "/"), "deny")
        self.assertEqual(g.decide("10.0.0.2", "/_mfd/wrong"), "deny")

    def test_first_token_holder_is_the_only_client(self):
        g = Gate("tok")
        self.assertEqual(g.decide("10.0.0.2", "/_mfd/tok"), "authorize")
        self.assertEqual(g.decide("10.0.0.2", "/do/mudrun/status"), "pipe")
        self.assertEqual(g.decide("10.0.0.3", "/_mfd/tok"), "deny")
        self.assertEqual(g.decide("10.0.0.3", "/"), "deny")

    def test_query_string_on_token_path(self):
        self.assertEqual(Gate("tok").decide("10.0.0.2", "/_mfd/tok?x=1"), "authorize")


class ParseTest(unittest.TestCase):
    def test_parse_request_path(self):
        self.assertEqual(parse_request_path(b"GET /_mfd/tok HTTP/1.1\r\nHost: x\r\n\r\n"), "/_mfd/tok")

    def test_parse_partial_or_garbage(self):
        self.assertIsNone(parse_request_path(b"GET /incomplete"))
        self.assertIsNone(parse_request_path(b"\x16\x03\x01binary"))


class LoginRelayTest(unittest.TestCase):
    def setUp(self):
        self.target = FakeTarget()
        self.relay = LoginRelay(target=("127.0.0.1", self.target.port), ttl=60)
        self.port = self.relay.start(host="127.0.0.1")

    def tearDown(self):
        self.relay.stop()
        self.target.close()

    def test_token_is_random_and_url_safe(self):
        other = LoginRelay(target=("127.0.0.1", 1))
        self.assertNotEqual(self.relay.token, other.token)
        self.assertGreaterEqual(len(self.relay.token), 16)
        self.assertRegex(self.relay.token, r"^[A-Za-z0-9_-]+$")

    def test_forbidden_before_token(self):
        self.assertIn("403", http_get(self.port, "/").splitlines()[0])

    def test_token_redirects_then_proxies(self):
        first = http_get(self.port, f"/_mfd/{self.relay.token}")
        self.assertIn("302", first.splitlines()[0])
        self.assertIn("Location: /", first)
        self.assertTrue(http_get(self.port, "/").endswith("hello"))

    def test_stop_closes_port(self):
        self.relay.stop()
        self.assertFalse(self.relay.active)
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", self.port), timeout=2).close()

    def test_expires_after_ttl(self):
        now = [1000.0]
        relay = LoginRelay(target=("127.0.0.1", self.target.port), ttl=300, clock=lambda: now[0])
        relay.start(host="127.0.0.1")
        self.assertEqual(relay.expires_at, 1300.0)
        self.assertTrue(relay.active)
        now[0] = 1301.0
        self.assertFalse(relay.active)
        relay.stop()


if __name__ == "__main__":
    unittest.main()
