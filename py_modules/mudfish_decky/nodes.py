"""Japan node filtering and ping ranking."""
from dataclasses import dataclass
from typing import Optional

JAPAN_PREFIX = "JP "


@dataclass(frozen=True)
class Node:
    sid: int
    label: str
    rtt: Optional[float]


def rtts_from_response(resp: dict) -> dict:
    """Map sid -> average RTT (ms) from /do/rtt/staticnodes, skipping failed probes.

    While Mudfish is mid-round the endpoint answers {"status": 300} without "rtts".
    """
    return {r["sid"]: float(r["rttavg"]) for r in resp.get("rtts", []) if r.get("success", 0) > 0}


def _label(location: str) -> str:
    start, end = location.find("("), location.rfind(")")
    if start == -1 or end <= start:
        return location
    return location[start + 1:end]


def japan_nodes(static_nodes: list, rtts: dict) -> list:
    """Japan nodes sorted by ping; unmeasured nodes go last, by label."""
    nodes = [Node(n["sid"], _label(n["location"]), rtts.get(n["sid"]))
             for n in static_nodes if n["location"].startswith(JAPAN_PREFIX)]
    measured = sorted((n for n in nodes if n.rtt is not None), key=lambda n: n.rtt)
    unmeasured = sorted((n for n in nodes if n.rtt is None), key=lambda n: n.label)
    return measured + unmeasured


def pick_auto(nodes: list) -> Optional[Node]:
    return next((n for n in nodes if n.rtt is not None), None)
