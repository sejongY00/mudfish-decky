"""Install, update and remove Mudfish Cloud VPN for Linux without running its installer script.

The official package is a Makeself archive: a shell header of `skip` lines followed by a bzip2 tar
whose MD5 is in the header. On SteamOS the bundled setup script only copies files into
/opt/mudfish/<version>/, so we verify the payload, unpack it ourselves and lay out the same tree.
"""
import hashlib
import io
import os
import re
import shutil
import tarfile
import urllib.request

from .client import ssl_context

MUDFISH_ROOT = "/opt/mudfish"
DOWNLOAD_PAGE = "https://mudfish.net/download"
RELEASE_URL = "https://mudfish.net/releases/mudfish-{version}-linux-x86_64.sh"
VERSION_RE = re.compile(r"^\d+(\.\d+)+$")
RELEASE_RE = re.compile(r"mudfish-(\d+(?:\.\d+)+)-linux-x86_64\.sh")
HEADER_LIMIT = 256 * 1024
LOGIN_FILES = (".conf", ".conf.db")
SKIPPED_FILES = {"pkg_linux_setup.sh"}
LAYOUT = {"bin": 0o755, "sbin": 0o755, "etc": 0o644, "share": 0o644}


class InstallError(Exception):
    pass


def _version_key(v: str):
    return tuple(int(p) for p in v.split("."))


def _fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=20, context=ssl_context()) as resp:
        return resp.read().decode("utf-8", "replace")


def _fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120, context=ssl_context()) as resp:
        return resp.read()


def latest_version(fetch=_fetch_text):
    versions = set(RELEASE_RE.findall(fetch(DOWNLOAD_PAGE)))
    return max(versions, key=_version_key) if versions else None


def download(version: str, fetch=_fetch_bytes) -> bytes:
    if not VERSION_RE.match(version):
        raise InstallError(f"bad version {version!r}")
    return fetch(RELEASE_URL.format(version=version))


def parse_makeself(data: bytes):
    """(header fields, payload bytes) of a Makeself archive."""
    head = data[:HEADER_LIMIT]
    if not head.startswith(b"#!") or b"Makeself" not in head:
        raise InstallError("not a Mudfish package")
    fields = dict(re.findall(rb'^(\w+)="([^"\n]*)"$', head, re.M))
    header = {k.decode(): v.decode() for k, v in fields.items()}
    try:
        skip = int(header["skip"])
    except (KeyError, ValueError):
        raise InstallError("package header has no skip")
    offset = 0
    for _ in range(skip):
        offset = data.index(b"\n", offset) + 1
    size = header.get("filesizes", "").split()
    payload = data[offset:offset + int(size[0])] if size else data[offset:]
    return header, payload


def _safe_members(tar: tarfile.TarFile) -> list:
    members = []
    for m in tar.getmembers():
        parts = os.path.normpath(m.name).split(os.sep)
        if os.path.isabs(m.name) or ".." in parts:
            raise InstallError(f"unsafe path in package: {m.name}")
        if not (m.isfile() or m.isdir()):
            raise InstallError(f"unexpected entry type in package: {m.name}")
        members.append(m)
    return members


def _lay_out(staging: str, dest: str) -> None:
    os.makedirs(dest)
    for sub, mode in LAYOUT.items():
        src = os.path.join(staging, sub)
        os.makedirs(os.path.join(dest, sub), mode=0o755)
        if not os.path.isdir(src):
            continue
        for name in os.listdir(src):
            path = os.path.join(src, name)
            if name in SKIPPED_FILES or not os.path.isfile(path):
                continue
            target = os.path.join(dest, sub, name)
            shutil.copyfile(path, target)
            os.chmod(target, mode)
    os.makedirs(os.path.join(dest, "var"), mode=0o755)


def install_package(data: bytes, root: str = MUDFISH_ROOT) -> str:
    """Verify and install a Mudfish package under root/<version>; returns the version."""
    header, payload = parse_makeself(data)
    version = header.get("targetdir", "")
    if not VERSION_RE.match(version):
        raise InstallError(f"bad version in package: {version!r}")
    if hashlib.md5(payload).hexdigest() != header.get("MD5", "").lower():
        raise InstallError("package checksum mismatch")
    os.makedirs(root, exist_ok=True)
    staging, fresh = os.path.join(root, f".{version}.unpack"), os.path.join(root, f".{version}.new")
    final = os.path.join(root, version)
    for d in (staging, fresh):
        shutil.rmtree(d, ignore_errors=True)
    try:
        try:
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:bz2") as tar:
                tar.extractall(staging, members=_safe_members(tar), filter="data")
        except (tarfile.TarError, EOFError, OSError) as e:
            raise InstallError(f"cannot unpack package: {e}")
        if not os.path.isfile(os.path.join(staging, "bin", "mudrun-headless")):
            raise InstallError("package has no mudrun-headless")
        _lay_out(staging, fresh)
        if os.path.isdir(final):  # reinstall: keep login/state
            shutil.rmtree(os.path.join(fresh, "var"))
            shutil.move(os.path.join(final, "var"), os.path.join(fresh, "var"))
            shutil.rmtree(final)
        os.rename(fresh, final)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(fresh, ignore_errors=True)
    return version


def carry_login(old_var: str, new_var: str) -> None:
    """Copy the launcher's saved login/settings into a newly installed version."""
    for name in LOGIN_FILES:
        src = os.path.join(old_var, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(new_var, name))


def prune_versions(root: str, keep: list) -> None:
    if not os.path.isdir(root):
        return
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if os.path.isdir(path) and name not in keep and (VERSION_RE.match(name) or name.startswith(".")):
            shutil.rmtree(path, ignore_errors=True)


def remove_all(root: str = MUDFISH_ROOT) -> None:
    if os.path.isdir(root):
        shutil.rmtree(root)
