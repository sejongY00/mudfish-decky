"""Detect and remove the per-node host routes Mudfish leaves behind after it stops."""
import subprocess
from typing import Optional


def host_routes(route_text: str) -> set:
    """Host routes (no prefix length, no proto, with a gateway) from `ip -4 route` output."""
    routes = set()
    for line in route_text.splitlines():
        parts = line.split()
        if not parts or "/" in parts[0] or parts[0] == "default":
            continue
        if "proto" in parts or "via" not in parts:
            continue
        routes.add(" ".join(parts))
    return routes


def leftover_routes(before: Optional[set], after_text: str) -> list:
    """Host routes added since `before`, excluding tunnel routes. No snapshot means delete nothing."""
    if before is None:
        return []
    added = host_routes(after_text) - set(before)
    return sorted(r for r in added if " dev tap" not in f" {r}")


def delete_routes(lines: list, run=subprocess.run) -> int:
    deleted = 0
    for line in lines:
        try:
            result = run(["ip", "route", "del", *line.split()], capture_output=True, timeout=5)
        except Exception:
            continue
        if result.returncode == 0:
            deleted += 1
    return deleted
