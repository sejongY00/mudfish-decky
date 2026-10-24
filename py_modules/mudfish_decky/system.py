"""Steam Deck side effects: locating Mudfish, running its daemon, reading routes and the public IP."""
import json
import os
import subprocess
import time
import urllib.request
from typing import Callable, Optional, Tuple

from .routes import delete_routes  # noqa: F401  (re-exported for the controller)

MUDFISH_ROOT = "/opt/mudfish"
DAEMON_UNIT = "mudfish-decky"
DEFAULT_API = "http://127.0.0.1:8282"


def _version_key(name: str):
    try:
        return tuple(int(p) for p in name.split("."))
    except ValueError:
        return None


def find_mudfish(root: str = MUDFISH_ROOT) -> Optional[Tuple[str, str]]:
    """(daemon binary, var dir) of the highest installed Mudfish version."""
    if not os.path.isdir(root):
        return None
    versions = []
    for name in os.listdir(root):
        key = _version_key(name)
        binary = os.path.join(root, name, "bin", "mudrun-headless")
        if key is not None and os.path.isfile(binary):
            versions.append((key, name))
    if not versions:
        return None
    name = max(versions)[1]
    return os.path.join(root, name, "bin", "mudrun-headless"), os.path.join(root, name, "var")


def api_base(var_dir: str) -> str:
    try:
        with open(os.path.join(var_dir, ".ipport")) as f:
            ipport = f.read().strip()
    except OSError:
        return DEFAULT_API
    return f"http://{ipport}" if ipport else DEFAULT_API


def ensure_daemon(bin_path: str, is_up: Callable[[], bool], run=subprocess.run, sleep=time.sleep) -> None:
    """Start the launcher as a transient systemd unit so it outlives desktop/game mode switches."""
    if is_up():
        return
    run(["systemd-run", f"--unit={DAEMON_UNIT}", "--collect", bin_path, "-B"], capture_output=True, timeout=10)
    for _ in range(20):
        sleep(0.5)
        if is_up():
            return


def tap_up() -> bool:
    return os.path.exists("/sys/class/net/tap0")


def route_text(run=subprocess.run) -> str:
    return run(["ip", "-4", "route"], capture_output=True, text=True, timeout=5).stdout


def public_ip() -> Optional[dict]:
    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=8) as resp:
            data = json.load(resp)
        return {"ip": data.get("ip"), "country": data.get("country")}
    except Exception:
        return None
