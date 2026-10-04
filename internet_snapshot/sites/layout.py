"""Radial-sector layout for site graphs (docs/DESIGN.md §12.6).

- The root sits at the origin, and depth d sits on shell r_d = radius · d / max_depth.
- Depth-1 subtrees get equal-area HEALPix sectors proportional to their subtree weight, and
  depth-2 subtrees get sub-sectors inside them.
- Deeper nodes are relaxed with the spherical spring embedder, kept inside their sector and
  pulled toward their parent's direction.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.spatial import cKDTree

from ..build.layout import NPIX, cell_vectors, grow_regions, region_centroid, relax
from ..geo import dir_from_azel, jitter_dir, normalize, placement, stable_unit, tangent_frame
from .model import SiteGraph

_CELL_VEC = None


def _cells():
    global _CELL_VEC
    if _CELL_VEC is None:
        _CELL_VEC = cell_vectors()
    return _CELL_VEC


def fibonacci_dirs(n: int) -> np.ndarray:
    """n well-spread directions; index 0 is straight ahead (+Z), then spiralling outward."""
    if n == 1:
        return np.array([[0.0, 0.0, 1.0]])
    i = np.arange(n) + 0.5
    polar = np.arccos(1 - 2 * i / n)          # angle from +Z
    phi = np.pi * (1 + 5 ** 0.5) * i
    v = np.stack([np.sin(polar) * np.sin(phi), np.sin(polar) * np.cos(phi), np.cos(polar)], axis=1)
    return normalize(v)


def layout_site(g: SiteGraph, radius: float = 1000.0, sector_depth: int = 2, iters: int | None = None) -> None:
    if iters is None:
        iters = 40 if len(g.nodes) < 80 else 80 if len(g.nodes) < 600 else 120
    cell_vec = _cells()
    nodes = g.nodes
    ch = g.children()
    D = max(1, g.max_depth())
    shell = {d: radius * d / D for d in range(D + 1)}
    sub = {nid: n.get("_sub", 1.0) for nid, n in nodes.items()}

    # ---- sectors ----
    region: dict[str, np.ndarray] = {g.id: np.arange(NPIX)}
    for d in range(1, min(sector_depth, D) + 1):
        for parent in [n for n in nodes.values() if n["depth"] == d - 1]:
            kids = sorted(ch.get(parent["id"], []), key=lambda k: (-sub[k], k))
            if not kids:
                continue
            cells = region[parent["id"]]
            if len(cells) < 2 * len(kids):
                for k in kids:
                    region[k] = cells
                continue
            weights = {k: math.sqrt(sub[k]) + 0.2 for k in kids}
            if d == 1:
                seeds = dict(zip(kids, fibonacci_dirs(len(kids))))
            else:
                centre = region_centroid(cells, cell_vec)
                e, nv = tangent_frame(centre)
                ang = math.sqrt(len(cells) / NPIX * 4) * 0.55
                tot = sum(weights.values())
                acc, seeds = 0.0, {}
                for k in kids:
                    mid = (acc + weights[k] / 2) / tot * 2 * math.pi
                    acc += weights[k]
                    seeds[k] = normalize(centre + math.tan(ang) * (math.cos(mid) * e + math.sin(mid) * nv))
            region.update(grow_regions(cells, seeds, weights, cell_vec))

    def region_of(nid: str) -> np.ndarray:
        cur = nid
        while cur not in region:
            cur = nodes[cur]["parent"]
        return region[cur]

    # ---- positions ----
    dirs: dict[str, np.ndarray] = {g.id: np.array([0.0, 0.0, 1.0])}
    nodes[g.id].update(placement(dirs[g.id], 0.0))
    for d in range(1, D + 1):
        level = sorted((n for n in nodes.values() if n["depth"] == d), key=lambda n: n["id"])
        if not level:
            continue
        fixed_by_sector = [n for n in level if n["id"] in region and region[n["id"]] is not region[n["parent"]]]
        for n in fixed_by_sector:
            dirs[n["id"]] = region_centroid(region[n["id"]], cell_vec)
        movers = [n for n in level if n["id"] not in dirs]
        if movers:
            # group movers by the cell set they must stay in
            keyed: dict[int, list[dict]] = {}
            reg_list: list[np.ndarray] = []
            reg_ids: dict[int, int] = {}
            for n in movers:
                cells = region_of(n["id"])
                rid = reg_ids.setdefault(id(cells), len(reg_list))
                if rid == len(reg_list):
                    reg_list.append(cells)
                keyed.setdefault(rid, []).append(n)
            X = np.zeros((len(movers), 3))
            anchors = np.zeros((len(movers), 3))
            node_region = np.zeros(len(movers), dtype=int)
            order = []
            for rid, group in keyed.items():
                for n in group:
                    i = len(order)
                    order.append(n)
                    pdir = dirs[n["parent"]]
                    anchors[i] = pdir
                    X[i] = jitter_dir(pdir, n["id"], 2.0 + 3.0 * stable_unit(n["id"]))
                    node_region[i] = rid
            trees = {rid: cKDTree(cell_vec[cells]) for rid, cells in enumerate(reg_list)}
            rvec = {rid: (cell_vec[cells], cells) for rid, cells in enumerate(reg_list)}
            sizes = np.array([n["size"] or 0.3 for n in order])
            X = relax(X, iters=iters, springs=[], sizes=sizes, anchors=anchors, anchor_k=np.full(len(order), 0.06),
                      containment=(node_region, trees, rvec), repulse=1.0)
            for i, n in enumerate(order):
                dirs[n["id"]] = X[i]
        for n in level:
            n.update(placement(dirs[n["id"]], shell[d]))

    # colours inherit from the depth-1 branch
    palette = ["#4FC3F7", "#F06292", "#FFB74D", "#AED581", "#B39DDB", "#64FFDA", "#7986CB", "#FF8A65", "#FFF176",
               "#4DB6AC", "#BA68C8", "#90CAF9", "#E57373", "#81C784", "#FFD54F", "#A1887F"]
    branch_color = {}
    for i, k in enumerate(sorted(ch.get(g.id, []), key=lambda k: (-sub[k], k))):
        branch_color[k] = palette[i % len(palette)]
    nodes[g.id]["color"] = "#FFFFFF"
    for n in nodes.values():
        if n["depth"] == 0:
            continue
        cur = n["id"]
        while nodes[cur]["depth"] > 1:
            cur = nodes[cur]["parent"]
        n["color"] = branch_color.get(cur, "#90A4AE")
    g.shells = [round(shell[d], 2) for d in range(D + 1)]
