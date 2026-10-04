"""Frozen spherical layout. See docs/DESIGN.md §5.

The service shell is divided into equal-area HEALPix sectors (realm → category), grown from
each realm's anchor direction. Orgs and services are placed inside their category's sector
with a spherical spring embedder (forces in the tangent plane, renormalised onto the sphere;
Kobourov & Wampler 2005), plus a containment force.

Network shells:

- The backbone shell is geographic (az = longitude, el = latitude·0.85). It is relaxed with
  relationship springs and short-range repulsion.
- On the edge shell, each cloud, CDN, content or hosting network sits in the direction of
  the services it hosts.

Everything is deterministic: a fixed seed and a fixed number of iterations.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict

import healpy as hp
import numpy as np
from scipy.spatial import cKDTree

from ..config import SERVICE_RADIUS, SHELLS
from ..geo import (dir_from_azel, from_healpix_angles, geo_dir, jitter_dir, normalize, placement, stable_unit,
                   to_healpix_angles)
from .catalog import Catalog

LAYOUT_ORDER = 5  # 12288 equal-area cells (~1.8° each) for sector allocation
NSIDE = 2 ** LAYOUT_ORDER
NPIX = hp.nside2npix(NSIDE)


def cell_vectors() -> np.ndarray:
    theta, phi = hp.pix2ang(NSIDE, np.arange(NPIX), nest=True)
    return from_healpix_angles(theta, phi)


def vec2cell(v: np.ndarray) -> np.ndarray:
    theta, phi = to_healpix_angles(v)
    return hp.ang2pix(NSIDE, theta, phi, nest=True)


def grow_regions(cells: np.ndarray, seeds: dict[str, np.ndarray], targets: dict[str, float],
                 cell_vec: np.ndarray) -> dict[str, np.ndarray]:
    """Partition ``cells`` into contiguous regions, each grown from its seed direction.

    Each region grows toward the cell count in ``targets``. Growth is balanced: the region
    furthest below its target claims next, and it always takes its frontier cell nearest the
    seed, so regions stay compact.
    """
    cellset = set(cells.tolist())
    owner: dict[int, str] = {}
    total = sum(targets.values())
    quota = {k: max(1.0, targets[k] / total * len(cells)) for k in targets}
    frontier: dict[str, list] = {k: [] for k in seeds}
    count = {k: 0 for k in seeds}
    for k, s in seeds.items():
        start = int(vec2cell(s[None, :])[0])
        if start not in cellset or start in owner:  # snap to the nearest free cell of this domain
            free = [c for c in cells.tolist() if c not in owner]
            start = free[int(np.argmax(cell_vec[free] @ s))]
        heapq.heappush(frontier[k], (0.0, start))
    while len(owner) < len(cellset):
        active = [k for k in seeds if frontier[k]]
        if not active:
            break
        k = min(active, key=lambda r: (count[r] / quota[r], r))
        while frontier[k]:
            _, c = heapq.heappop(frontier[k])
            if c in owner:
                continue
            owner[c] = k
            count[k] += 1
            for nb in hp.get_all_neighbours(NSIDE, c, nest=True):
                nb = int(nb)
                if nb >= 0 and nb in cellset and nb not in owner:
                    d = 1.0 - float(cell_vec[nb] @ seeds[k])
                    heapq.heappush(frontier[k], (d, nb))
            break
    # any unreachable leftovers: nearest seed
    for c in cellset - set(owner):
        owner[c] = max(seeds, key=lambda k: float(cell_vec[c] @ seeds[k]))
    out = defaultdict(list)
    for c, k in owner.items():
        out[k].append(c)
    return {k: np.array(sorted(v)) for k, v in out.items()}


def region_centroid(cells: np.ndarray, cell_vec: np.ndarray) -> np.ndarray:
    c = normalize(cell_vec[cells].mean(axis=0))
    # snap to the region if the centroid falls outside (non-convex shapes)
    best = cells[int(np.argmax(cell_vec[cells] @ c))]
    return c if (cell_vec[best] @ c) > 0.9995 else cell_vec[best]


def _tangent(F: np.ndarray, X: np.ndarray) -> np.ndarray:
    return F - (F * X).sum(axis=1, keepdims=True) * X


def relax(X: np.ndarray, *, iters: int, springs: list[tuple[int, int, float]], sizes: np.ndarray,
          anchors: np.ndarray | None = None, anchor_k: np.ndarray | None = None,
          containment: tuple[np.ndarray, dict[int, cKDTree], dict[int, np.ndarray]] | None = None,
          groups: np.ndarray | None = None, group_k: float = 0.0, fixed: np.ndarray | None = None,
          repulse: float = 1.0, step0: float = 0.6) -> np.ndarray:
    """Spherical spring embedder on the unit sphere. Returns the new unit vectors."""
    X = normalize(X.copy())
    n = len(X)
    if n == 0:
        return X
    spacing = math.sqrt(4 * math.pi / max(n, 1))
    if containment is not None:
        node_region, trees, region_cells_vec = containment
        # spacing should reflect local density inside each region
        counts = np.bincount(node_region, minlength=int(node_region.max()) + 1)
        area = np.array([len(region_cells_vec.get(i, [])) for i in range(len(counts))], dtype=float)
        local = np.sqrt(4 * math.pi * np.maximum(area, 1) / NPIX / np.maximum(counts, 1))
        node_spacing = local[node_region]
    else:
        node_spacing = np.full(n, spacing)
    radius = float(np.median(node_spacing)) * 2.2
    si = np.array([s[0] for s in springs], dtype=int)
    sj = np.array([s[1] for s in springs], dtype=int)
    sw = np.array([s[2] for s in springs], dtype=float)
    fixed = fixed if fixed is not None else np.zeros(n, dtype=bool)
    for it in range(iters):
        t = 1.0 - it / iters
        step = step0 * (0.15 + 0.85 * t)
        F = np.zeros_like(X)
        # short-range repulsion between near neighbours
        tree = cKDTree(X)
        pairs = tree.query_pairs(radius, output_type="ndarray")
        if len(pairs):
            a, b = pairs[:, 0], pairs[:, 1]
            d = X[a] - X[b]
            dist = np.linalg.norm(d, axis=1, keepdims=True) + 1e-9
            want = 0.5 * (node_spacing[a] + node_spacing[b])[:, None] * (0.6 + 0.4 * (sizes[a] + sizes[b])[:, None])
            mag = repulse * np.clip(want - dist, 0, None) / want
            f = d / dist * mag * want
            np.add.at(F, a, f)
            np.add.at(F, b, -f)
        # springs
        if len(sw):
            d = X[sj] - X[si]
            f = d * sw[:, None] * 0.5
            np.add.at(F, si, f)
            np.add.at(F, sj, -f)
        # group cohesion
        if groups is not None and group_k > 0:
            gid = groups
            valid = gid >= 0
            if valid.any():
                ng = int(gid[valid].max()) + 1
                cent = np.zeros((ng, 3))
                np.add.at(cent, gid[valid], X[valid])
                cent = normalize(cent)
                F[valid] += group_k * (cent[gid[valid]] - X[valid])
        # anchors
        if anchors is not None:
            F += anchor_k[:, None] * (anchors - X)
        disp = _tangent(F, X) * step
        norms = np.linalg.norm(disp, axis=1, keepdims=True) + 1e-12
        disp *= np.minimum(1.0, 2.0 * node_spacing[:, None] / norms)
        Xn = normalize(X + disp)
        # containment: nodes that left their region are pulled back to the nearest region cell
        if containment is not None and (it % 3 == 0 or it == iters - 1):
            cells = vec2cell(Xn)
            for rid, tree_r in trees.items():
                idx = np.where(node_region == rid)[0]
                if not len(idx):
                    continue
                allowed = region_cells_vec[rid]
                outside = idx[~np.isin(cells[idx], allowed[1])]
                if len(outside):
                    _, nearest = tree_r.query(Xn[outside])
                    target = allowed[0][nearest]
                    Xn[outside] = normalize(0.3 * Xn[outside] + 0.7 * target)
        Xn[fixed] = X[fixed]
        X = Xn
    return X


def layout(cat: Catalog, taxonomy: dict, iters: int = 160, rng_seed: int = 20261004) -> dict:
    """Assign r/az/el/pos to every node. Returns layout metadata (sector cells per realm/category)."""
    cell_vec = cell_vectors()
    nodes = cat.nodes

    # ---------------- service shell: sectors ----------------
    services = [n for n in nodes.values() if n["kind"] == "service"]
    cat_weight = defaultdict(float)
    for s in services:
        cat_weight[s["category"]] += s["size"]
    realm_of_cat = {}
    realm_weight = defaultdict(float)
    for realm in taxonomy["realms"]:
        rid = f"realm:{realm['slug']}"
        for c in realm["categories"]:
            cid = f"cat:{c['slug']}"
            realm_of_cat[cid] = rid
            # damped weights so the long tail doesn't swamp curated realms; a floor keeps empty categories visible
            cat_weight[cid] = math.sqrt(cat_weight[cid] + 1.0) + 1.0
            realm_weight[rid] += cat_weight[cid]
    realm_seeds = {}
    for i, realm in enumerate(taxonomy["realms"]):
        az, el = realm.get("anchor") or (360.0 * i / len(taxonomy["realms"]), 0.0)
        realm_seeds[f"realm:{realm['slug']}"] = dir_from_azel(az, el)
    realm_cells = grow_regions(np.arange(NPIX), realm_seeds, dict(realm_weight), cell_vec)

    cat_cells: dict[str, np.ndarray] = {}
    for realm in taxonomy["realms"]:
        rid = f"realm:{realm['slug']}"
        cells = realm_cells[rid]
        centre = region_centroid(cells, cell_vec)
        cids = [f"cat:{c['slug']}" for c in realm["categories"]]
        if len(cids) == 1:
            cat_cells[cids[0]] = cells
            continue
        # seeds on a ring around the realm centre, one per category, at angles by cumulative weight
        from ..geo import tangent_frame
        e, nvec = tangent_frame(centre)
        ang_radius = math.sqrt(len(cells) / NPIX * 4 * math.pi / math.pi) * 0.55
        tot = sum(cat_weight[c] for c in cids)
        acc, seeds = 0.0, {}
        for cid in cids:
            mid = (acc + cat_weight[cid] / 2) / tot * 2 * math.pi
            acc += cat_weight[cid]
            seeds[cid] = normalize(centre + math.tan(ang_radius) * (math.cos(mid) * e + math.sin(mid) * nvec))
        cat_cells.update(grow_regions(cells, seeds, {c: cat_weight[c] for c in cids}, cell_vec))

    for rid, cells in realm_cells.items():
        nodes[rid].update(placement(region_centroid(cells, cell_vec), SERVICE_RADIUS["realm"]))
    for cid, cells in cat_cells.items():
        nodes[cid].update(placement(region_centroid(cells, cell_vec), SERVICE_RADIUS["category"]))

    # ---------------- service shell: orgs + services ----------------
    movers = [n for n in nodes.values() if n["kind"] in ("org", "service")]
    index = {n["id"]: i for i, n in enumerate(movers)}
    cat_ids = sorted(cat_cells)
    cat_index = {c: i for i, c in enumerate(cat_ids)}
    node_region = np.array([cat_index[n["category"]] for n in movers])
    X = np.zeros((len(movers), 3))
    for i, n in enumerate(movers):
        cells = cat_cells[n["category"]]
        if n["kind"] == "service" and n["parent"] and n["parent"].startswith("org:"):
            continue  # placed next to the org below
        c = cells[int(stable_unit(n["id"]) * len(cells)) % len(cells)]
        X[i] = jitter_dir(cell_vec[c], n["id"], 1.0)
    for i, n in enumerate(movers):
        if n["kind"] == "service" and n["parent"] and n["parent"].startswith("org:"):
            X[i] = jitter_dir(X[index[n["parent"]]], n["id"], 2.0)

    springs = []
    for e in cat.edges:
        if e["kind"] == "owns" and e["source"] in index and e["target"] in index:
            same = nodes[e["source"]]["category"] == nodes[e["target"]]["category"]
            springs.append((index[e["source"]], index[e["target"]], 0.35 if same else 0.08))
    # cohesion groups: long-tail services cluster by (category, country), hosted services by (category, host)
    gkeys: dict[tuple, int] = {}
    groups = np.full(len(movers), -1)
    for i, n in enumerate(movers):
        if n["kind"] != "service" or n["org"]:
            continue
        key = (n["category"], n["country"] or (n["_hosted"][0] if n["_hosted"] else None))
        if key[1] is None:
            continue
        groups[i] = gkeys.setdefault(key, len(gkeys))
    trees, region_vec = {}, {}
    for cid, i in cat_index.items():
        cells = cat_cells[cid]
        trees[i] = cKDTree(cell_vec[cells])
        region_vec[i] = (cell_vec[cells], cells)
    sizes = np.array([n["size"] or 0.3 for n in movers])
    X = relax(X, iters=iters, springs=springs, sizes=sizes, containment=(node_region, trees, region_vec),
              groups=groups, group_k=0.04, repulse=1.0)
    for i, n in enumerate(movers):
        n.update(placement(X[i], SERVICE_RADIUS[n["kind"]]))
        n["_dir"] = X[i]

    # ---------------- backbone shell ----------------
    backbone = [n for n in nodes.values() if n["shell"] == "backbone"]
    bidx = {n["id"]: i for i, n in enumerate(backbone)}
    anchors = np.zeros((len(backbone), 3))
    anchor_k = np.zeros(len(backbone))
    fixed = np.zeros(len(backbone), dtype=bool)
    for i, n in enumerate(backbone):
        lat, lon = n["_geo"]
        base = geo_dir(lat, lon)
        if n["kind"] == "region":
            anchors[i] = base
            fixed[i] = True
        elif n["kind"] == "ixp":
            anchors[i] = base
            anchor_k[i] = 0.6
        else:
            anchors[i] = jitter_dir(base, n["id"], 4.0 if n["role"] != "tier1" else 10.0)
            anchor_k[i] = 0.08 if n["role"] == "tier1" else 0.35
    bsprings = []
    for e in cat.edges:
        if e["kind"] in ("transit", "peer", "member") and e["source"] in bidx and e["target"] in bidx:
            w = 0.02 if e["kind"] == "peer" else 0.05
            bsprings.append((bidx[e["source"]], bidx[e["target"]], w))
    bsizes = np.array([n["size"] or 0.3 for n in backbone])
    XB = relax(anchors.copy(), iters=iters, springs=bsprings, sizes=bsizes, anchors=anchors, anchor_k=anchor_k,
               fixed=fixed, repulse=0.8)
    for i, n in enumerate(backbone):
        n.update(placement(XB[i], SHELLS["backbone"]))
        n["_dir"] = XB[i]

    # ---------------- edge shell ----------------
    edge = [n for n in nodes.values() if n["shell"] == "edge"]
    hosted_dirs = defaultdict(list)
    for e in cat.edges:
        if e["kind"] in ("hosted_by", "operates") and e["target"] in nodes and "_dir" in nodes[e["source"]]:
            src = nodes[e["source"]]
            hosted_dirs[e["target"]].append(src["_dir"] * (src["size"] or 0.3))
    EA = np.zeros((len(edge), 3))
    for i, n in enumerate(edge):
        v = np.sum(hosted_dirs[n["id"]], axis=0) if hosted_dirs[n["id"]] else np.zeros(3)
        strength = np.linalg.norm(v) / max(1e-9, sum(np.linalg.norm(x) for x in hosted_dirs[n["id"]]) or 1)
        if np.linalg.norm(v) > 0 and strength > 0.15:
            EA[i] = normalize(v)
        else:
            lat, lon = n["_geo"]
            EA[i] = jitter_dir(geo_dir(lat, lon), n["id"], 5.0)
    esizes = np.array([n["size"] or 0.3 for n in edge])
    XE = relax(EA.copy(), iters=iters, springs=[], sizes=esizes, anchors=EA, anchor_k=np.full(len(edge), 0.25),
               repulse=1.0)
    for i, n in enumerate(edge):
        n.update(placement(XE[i], SHELLS["edge"]))
        n["_dir"] = XE[i]

    return {"realm_cells": {k: v.tolist() for k, v in realm_cells.items()},
            "category_cells": {k: v.tolist() for k, v in cat_cells.items()}}
