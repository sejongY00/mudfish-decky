"""Publish the packaged zip as a Gitea release v<version>, once per version.

Usage: python scripts/gitea_release.py OUT_DIR
Env: GITEA_URL, GITEA_REPO (owner/name), GITEA_TOKEN (write access to releases), GIT_COMMIT.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from package import PLUGIN_DIR, read_version  # noqa: E402

NOTES = """Decky Loader plugin for Mudfish Cloud VPN (Full VPN toggle, Japan node picker, QR phone login,
Mudfish install/update/remove).

Install: Decky settings → Developer mode → Install Plugin from URL, and paste this zip's download URL.
"""


class ReleaseError(Exception):
    pass


def _multipart(filename: str, data: bytes):
    boundary = uuid.uuid4().hex
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"attachment\"; filename=\"{filename}\"\r\n"
            "Content-Type: application/zip\r\n\r\n").encode()
    return head + data + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def publish(api, repo: str, version: str, commit: str, zip_path: str):
    """Create release v<version> with the zip attached; None if that release already exists."""
    tag = f"v{version}"
    base = f"/api/v1/repos/{repo}/releases"
    status, _ = api("GET", f"{base}/tags/{tag}")
    if status == 200:
        print(f"release {tag} already exists; nothing to publish")
        return None
    if status != 404:
        raise ReleaseError(f"checking {tag}: HTTP {status}")
    status, release = api("POST", base, {"tag_name": tag, "target_commitish": commit,
                                         "name": f"Mudfish VPN {tag}", "body": NOTES})
    if status not in (200, 201):
        raise ReleaseError(f"creating {tag}: HTTP {status} {release.get('message', '')}")
    name = os.path.basename(zip_path)
    with open(zip_path, "rb") as f:
        body, ctype = _multipart(name, f.read())
    status, asset = api("POST", f"{base}/{release['id']}/assets?name={urllib.parse.quote(name)}",
                        body, {"Content-Type": ctype})
    if status not in (200, 201):
        raise ReleaseError(f"uploading {name}: HTTP {status} {asset.get('message', '')}")
    return asset.get("browser_download_url")


def http_api(base_url: str, token: str):
    def call(method, path, body=None, headers=None):
        headers = dict(headers or {}, Authorization=f"token {token}", Accept="application/json")
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(base_url.rstrip("/") + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        try:
            return status, json.loads(raw) if raw else {}
        except ValueError:
            return status, {}
    return call


def main(out_dir: str) -> None:
    version = read_version(".")
    zip_path = os.path.join(out_dir, f"{PLUGIN_DIR}-{version}.zip")
    if not os.path.isfile(zip_path):
        sys.exit(f"release: {zip_path} not found (run scripts/package.py first)")
    api = http_api(os.environ["GITEA_URL"], os.environ["GITEA_TOKEN"])
    url = publish(api, os.environ["GITEA_REPO"], version, os.environ.get("GIT_COMMIT", "main"), zip_path)
    if url:
        print(f"published {url}")


if __name__ == "__main__":
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else "out")
    except ReleaseError as e:
        sys.exit(f"release: {e}")
