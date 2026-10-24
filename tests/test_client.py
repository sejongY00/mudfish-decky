import json
import unittest

from mudfish_decky.client import MudfishClient, MudfishError, SigninError

BASE = "http://127.0.0.1:8282"
SIGNED_OUT = {"status": 200, "isSignedIn": False, "username": "u", "token_v3": "123",
              "item_conf_mode": "simple", "version": "6.6.0", "api_server": "api.mudfish.net", "jwt": ""}
SIGNIN_OK = {"status": 200, "token_v3": "456", "jwt": "JWT", "expert_mode": 0, "lang": "ko_KR", "alias_enable": 0}


class FakeTransport:
    def __init__(self, routes):
        self.routes = routes  # (method, url) -> list of response dicts/bytes, consumed in order
        self.calls = []

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, body, headers))
        queue = self.routes[(method, url)]
        resp = queue.pop(0) if len(queue) > 1 else queue[0]
        return 200, resp if isinstance(resp, bytes) else json.dumps(resp).encode()

    def calls_to(self, method, url):
        return [c for c in self.calls if c[0] == method and c[1] == url]


class ClientTest(unittest.TestCase):
    def test_ensure_signed_in_noop_when_signed(self):
        t = FakeTransport({("GET", BASE + "/do/mudrun/status"): [dict(SIGNED_OUT, isSignedIn=True)]})
        MudfishClient(BASE, t).ensure_signed_in()
        self.assertEqual(t.calls_to("POST", "https://api.mudfish.net/signin_ng_v3"), [])

    def test_ensure_signed_in_replays_autologin(self):
        t = FakeTransport({
            ("GET", BASE + "/do/mudrun/status"): [SIGNED_OUT, dict(SIGNED_OUT, isSignedIn=True, jwt="JWT")],
            ("POST", "https://api.mudfish.net/signin_ng_v3"): [SIGNIN_OK],
            ("POST", BASE + "/do/auth"): [{"status": 200, "msg": "OK"}],
        })
        st = MudfishClient(BASE, t).ensure_signed_in()
        self.assertTrue(st["isSignedIn"])
        (_, _, body, headers), = t.calls_to("POST", "https://api.mudfish.net/signin_ng_v3")
        self.assertIn("multipart/form-data; boundary=", headers["Content-Type"])
        text = body.decode()
        self.assertIn('name="autologin"\r\n\r\nON\r\n', text)
        self.assertIn('name="password"\r\n\r\n123\r\n', text)
        (_, _, auth_body, _), = t.calls_to("POST", BASE + "/do/auth")
        auth = json.loads(auth_body)
        self.assertEqual(auth["password"], "123")
        self.assertIs(auth["remember_me"], True)
        self.assertEqual(auth["jwt"], "JWT")
        self.assertEqual(auth["token_v3"], "456")

    def test_ensure_signed_in_raises_on_401(self):
        t = FakeTransport({
            ("GET", BASE + "/do/mudrun/status"): [SIGNED_OUT],
            ("POST", "https://api.mudfish.net/signin_ng_v3"): [{"status": 401}],
        })
        with self.assertRaises(SigninError):
            MudfishClient(BASE, t).ensure_signed_in()

    def test_start_accepts_201(self):
        t = FakeTransport({("POST", BASE + "/do/mudfish/start"): [{"status": 201}]})
        MudfishClient(BASE, t).start()

    def test_start_raises_on_500(self):
        t = FakeTransport({("POST", BASE + "/do/mudfish/start"): [{"status": 500}]})
        with self.assertRaises(MudfishError):
            MudfishClient(BASE, t).start()

    def test_rtts_while_measuring_is_empty(self):
        t = FakeTransport({("GET", BASE + "/do/rtt/staticnodes"): [{"status": 300, "n_checked": 3}]})
        self.assertEqual(MudfishClient(BASE, t).rtts(), {})

    def test_save_prog_conf_sends_authorization_header(self):
        t = FakeTransport({("POST", "https://api.mudfish.net/prog"): [{"status": 200, "need_restart": False}]})
        resp = MudfishClient(BASE, t).save_prog_conf("JWT", "api.mudfish.net", {"mudfishFullvpnSid": 11})
        self.assertFalse(resp["need_restart"])
        (_, _, body, headers), = t.calls
        self.assertEqual(headers["Authorization"], "JWT")
        self.assertEqual(json.loads(body), {"mudfishFullvpnSid": 11})

    def test_prog_conf_reads_graphql(self):
        conf = {"mudfishFullvpnSid": 0, "mudfishFullvpnExceptions": ""}
        t = FakeTransport({("POST", "https://api.mudfish.net/graphql"):
                           [{"data": {"user": {"progConf": conf}}}]})
        self.assertEqual(MudfishClient(BASE, t).prog_conf("JWT", "api.mudfish.net"), conf)
        self.assertIn("mudfishFullvpnExceptions", json.loads(t.calls[0][2])["query"])

    def test_fullvpn_refresh_posts_form_and_accepts_empty_body(self):
        t = FakeTransport({("POST", BASE + "/do/fullvpn/refresh"): [b""]})
        MudfishClient(BASE, t).fullvpn_refresh(504, "")
        (_, _, body, headers), = t.calls
        self.assertEqual(headers["Content-Type"], "application/x-www-form-urlencoded")
        self.assertEqual(body, b"sid=504&exceptions=")


if __name__ == "__main__":
    unittest.main()
