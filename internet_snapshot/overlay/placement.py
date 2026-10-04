"""Deterministic placement of personal-overlay nodes. Implements docs/snapshot-format.md §8.4."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..geo import normalize, offset_dir, placement

GOLDEN_ANGLE = 137.50776
ACCOUNT_RING_DEG = 1.2
GROUP_RING_DEG = 0.6
PRODUCT_RING_DEG = 0.8
ASSET_DISC_DEG = 0.5
WHITE = "#FFFFFF"


@dataclass
class Asset:
    id: str
    label: str
    meta: dict = field(default_factory=dict)
    size: float = 0.25


@dataclass
class Group:
    key: str
    label: str
    assets: list[Asset]
    product_anchor: str | None = None  # snapshot node id, e.g. svc:gmail.com
    meta: dict = field(default_factory=dict)


def _node(id, kind, label, parent, anchor, v, r, size, meta) -> dict:
    n = {"id": id, "kind": kind, "label": label, "parent": parent, "anchor": anchor, "size": size, "color": WHITE,
         "meta": meta}
    n.update(placement(v, r))
    return n


def _edge(source: dict, target_id: str, target_pos, kind: str) -> dict:
    return {"source": source["id"], "target": target_id, "kind": kind, "a": source["pos"], "b": list(target_pos)}


def place_overlay(*, provider: str, account_id: str, account_label: str, account_meta: dict, anchor_id: str,
                  anchor_pos, groups: list[Group], node_pos: dict[str, list[float]], account_index: int = 0,
                  account_count: int = 1) -> tuple[list[dict], list[dict]]:
    """Return (nodes, edges) for one account's overlay.

    node_pos maps snapshot node ids to positions. It is used for product sub-anchors.
    """
    P = np.asarray(anchor_pos, dtype=float)
    rA = float(np.linalg.norm(P))
    u = normalize(P)
    N, i = max(1, account_count), account_index
    if N == 1:
        ua = u
    else:
        ang = 2 * math.pi * i / N
        ua = offset_dir(u, ACCOUNT_RING_DEG * math.cos(ang), ACCOUNT_RING_DEG * math.sin(ang))
    acc_r = rA - 25
    acc = _node(account_id, "account", account_label, anchor_id, anchor_id, ua, acc_r, 0.5, account_meta)
    nodes, edges = [acc], [_edge(acc, anchor_id, P, "attached")]

    G = max(1, len(groups))
    for g_i, g in enumerate(groups):
        gid = f"{account_id}:group:{g.key}"
        prod = node_pos.get(g.product_anchor) if g.product_anchor else None
        if prod is not None:
            Pp = np.asarray(prod, dtype=float)
            up = normalize(Pp)
            if N == 1:
                ug = up
            else:
                ang = 2 * math.pi * i / N
                ug = offset_dir(up, PRODUCT_RING_DEG * math.cos(ang), PRODUCT_RING_DEG * math.sin(ang))
            g_r = float(np.linalg.norm(Pp)) - 25
        else:
            ang = 2 * math.pi * g_i / G + math.pi / 4
            ug = offset_dir(ua, GROUP_RING_DEG * math.cos(ang), GROUP_RING_DEG * math.sin(ang))
            g_r = rA - 28
        gnode = _node(gid, "group", g.label, account_id, g.product_anchor or anchor_id, ug, g_r, 0.35,
                      {"type": g.key.split(":", 1)[0], "key": g.key, "count": len(g.assets), **g.meta})
        nodes.append(gnode)
        edges.append(_edge(gnode, account_id, acc["pos"], "contains"))
        if prod is not None:
            edges.append(_edge(gnode, g.product_anchor, prod, "attached"))
        M = max(1, len(g.assets))
        for j, a in enumerate(g.assets):
            rho = ASSET_DISC_DEG * math.sqrt((j + 0.5) / M)
            th = math.radians(j * GOLDEN_ANGLE)
            ux = offset_dir(ug, rho * math.cos(th), rho * math.sin(th))
            an = _node(f"{gid}:{a.id}", "asset", a.label, gid, g.product_anchor or anchor_id, ux, g_r - 3,
                       a.size, a.meta)
            nodes.append(an)
            edges.append(_edge(an, gid, gnode["pos"], "contains"))
    return nodes, edges
