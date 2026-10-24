"""Where to get this plugin's newest build: the latest Gitea release's zip (for Decky's Install from URL)."""
import json
import logging
import urllib.request
from typing import Optional

from .client import ssl_context

LATEST_RELEASE_API = "https://git.sejong.dev/api/v1/repos/ysj7705/mudfish-decky/releases/latest"

log = logging.getLogger("mudfish_decky")


def _fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10, context=ssl_context()) as resp:
        return resp.read().decode()


def latest_plugin_release(fetch=_fetch) -> Optional[dict]:
    """{'version': '0.1.2', 'url': <zip download URL>} or None when offline or no zip is attached."""
    try:
        release = json.loads(fetch(LATEST_RELEASE_API))
    except Exception as e:
        log.warning("plugin release lookup failed: %s", e)
        return None
    zips = [a for a in release.get("assets", []) if a.get("name", "").endswith(".zip")]
    if not zips:
        return None
    return {"version": release.get("tag_name", "").lstrip("v"), "url": zips[0]["browser_download_url"]}
