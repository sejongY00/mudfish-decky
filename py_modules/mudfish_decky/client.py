"""HTTP calls to the local Mudfish launcher API and the Mudfish cloud API."""
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Callable, Dict, Optional, Tuple

from .nodes import rtts_from_response

Transport = Callable[[str, str, Optional[bytes], Dict[str, str]], Tuple[int, bytes]]

PROG_CONF_FIELDS = [
    "mudfishCreditSavingMode", "mudfishFullvpnSid", "mudfishFullvpnVid", "mudfishFullvpnXp",
    "mudfishFullvpnExceptions", "mudfishMtu", "mudfishPreferWfp", "mudfishProtomethod",
    "mudfishReBrokerMaxconns", "mudflowCompatv1", "mudflowRttmethod",
]


class MudfishError(Exception):
    pass


class SigninError(MudfishError):
    pass


class AuthError(MudfishError):
    """The cloud API rejected our jwt (expired session); a forced re-signin may fix it."""


# Decky's bundled Python ships without a CA store, so point it at SteamOS's system bundle.
SYSTEM_CA_BUNDLES = ["/etc/ssl/certs/ca-certificates.crt", "/etc/ca-certificates/extracted/tls-ca-bundle.pem"]


def ssl_context(cafiles=SYSTEM_CA_BUNDLES, factory=ssl.create_default_context):
    ctx = factory()
    for path in cafiles:
        if os.path.isfile(path):
            ctx.load_verify_locations(cafile=path)
            break
    return ctx


_SSL = ssl_context()


def urllib_transport(method, url, body, headers):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10, context=_SSL) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _multipart(fields: dict) -> Tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                    for k, v in fields.items())
    return (parts + f"--{boundary}--\r\n").encode(), "multipart/form-data; boundary=" + boundary


class MudfishClient:
    def __init__(self, base_url: str, transport: Transport = urllib_transport):
        self.base_url = base_url
        self.transport = transport

    def _call(self, method, url, body=None, headers=None) -> bytes:
        code, data = self.transport(method, url, body, headers or {})
        if not 200 <= code < 300:
            raise MudfishError(f"HTTP {code} from {url}")
        return data

    def _json(self, method, url, body=None, headers=None) -> dict:
        data = self._call(method, url, body, headers)
        try:
            return json.loads(data)
        except ValueError:
            raise MudfishError(f"invalid response from {url}")

    def _post_json(self, url, payload, headers=None) -> dict:
        return self._json("POST", url, json.dumps(payload).encode(),
                          {"Content-Type": "application/json", **(headers or {})})

    def status(self) -> dict:
        return self._json("GET", self.base_url + "/do/mudrun/status")

    def ensure_signed_in(self, force: bool = False) -> dict:
        """Replay the launcher's remember-me autologin when the daemon has no session (or force=True)."""
        st = self.status()
        if st.get("isSignedIn") and not force:
            return st
        if not st.get("token_v3") or not st.get("username"):
            raise SigninError("no saved login")
        body, ctype = _multipart({
            "autologin": "ON", "username": st["username"], "password": st["token_v3"],
            "item_conf_mode": st.get("item_conf_mode", ""), "version": st.get("version", ""),
        })
        url = f"https://{st['api_server']}/signin_ng_v3"
        code, data = self.transport("POST", url, body, {"Content-Type": ctype})
        if code in (401, 403):
            raise SigninError(f"signin HTTP {code}")
        if not 200 <= code < 300:
            raise MudfishError(f"HTTP {code} from {url}")
        try:
            signin = json.loads(data)
        except ValueError:
            raise MudfishError(f"invalid response from {url}")
        if signin.get("status") != 200:
            raise SigninError(f"signin status {signin.get('status')}")
        auth = self._post_json(self.base_url + "/do/auth", {
            "username": st["username"], "password": st["token_v3"], "remember_me": True,
            "token_v3": signin["token_v3"], "jwt": signin["jwt"], "expert_mode": signin.get("expert_mode"),
            "lang": signin.get("lang"), "alias_enable": signin.get("alias_enable"),
        })
        if auth.get("status") != 200:
            raise SigninError(f"auth status {auth.get('status')}")
        return self.status()

    def start(self) -> None:
        resp = self._json("POST", self.base_url + "/do/mudfish/start", b"")
        if resp.get("status") not in (200, 201):
            raise MudfishError(f"start status {resp.get('status')}")

    def stop(self) -> None:
        resp = self._json("POST", self.base_url + "/do/mudfish/stop", b"")
        if resp.get("status") != 200:
            raise MudfishError(f"stop status {resp.get('status')}")

    def rtts(self) -> dict:
        return rtts_from_response(self._json("GET", self.base_url + "/do/rtt/staticnodes"))

    def _cloud(self, jwt, url, payload) -> dict:
        code, data = self.transport("POST", url, json.dumps(payload).encode(),
                                    {"Content-Type": "application/json", "Authorization": jwt})
        if code in (401, 403):
            raise AuthError(f"HTTP {code} from {url}")
        if not 200 <= code < 300:
            raise MudfishError(f"HTTP {code} from {url}")
        try:
            return json.loads(data)
        except ValueError:
            raise MudfishError(f"invalid response from {url}")

    def _graphql_user(self, jwt, api, fields) -> dict:
        resp = self._cloud(jwt, f"https://{api}/graphql", {"query": "{ user { %s } }" % fields})
        user = (resp.get("data") or {}).get("user") if isinstance(resp, dict) else None
        if not user:
            raise AuthError("graphql returned no user")
        return user

    def static_nodes(self, jwt, api) -> list:
        return self._graphql_user(jwt, api, "staticNodes { sid location }")["staticNodes"]

    def prog_conf(self, jwt, api) -> dict:
        return self._graphql_user(jwt, api, "progConf { %s }" % " ".join(PROG_CONF_FIELDS))["progConf"]

    def save_prog_conf(self, jwt, api, conf: dict) -> dict:
        resp = self._cloud(jwt, f"https://{api}/prog", conf)
        if resp.get("status") != 200:
            raise MudfishError(resp.get("msg") or f"prog status {resp.get('status')}")
        return resp

    def fullvpn_refresh(self, sid: int, exceptions: str) -> None:
        body = urllib.parse.urlencode({"sid": sid, "exceptions": exceptions}).encode()
        self._call("POST", self.base_url + "/do/fullvpn/refresh", body,
                   {"Content-Type": "application/x-www-form-urlencoded"})
