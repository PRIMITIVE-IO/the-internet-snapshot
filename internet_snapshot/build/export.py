"""LOD assignment, edge aggregation, tiling and snapshot publishing.

Implements docs/snapshot-format.md: an immutable ``public/snapshots/<id>/`` directory plus a
``latest.json`` pointer.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import healpy as hp
import numpy as np

from .. import FORMAT_VERSION
from ..config import GEO_EL_SCALE, SHELLS, SNAPSHOTS_DIR, TILE_ORDER
from ..geo import to_healpix_angles
from .catalog import NODE_KEYS, Catalog

LOD1_NETWORK_ROLES = ("tier1", "cloud", "cdn")


def assign_lods(cat: Catalog, lod2_networks: int = 800) -> None:
    nodes = cat.nodes
    for n in nodes.values():
        k = n["kind"]
        if k in ("realm", "region"):
            n["lod"] = 0
        elif k == "category":
            n["lod"] = 1
        elif k in ("org", "ixp"):
            n["lod"] = 2
        elif k == "service":
            n["lod"] = 2 if (n["_seed"] or (n["rank"] is not None and n["rank"] <= 1000)) else 3
    nets = [n for n in nodes.values() if n["kind"] == "network"]
    for n in nets:
        major_content = n["role"] == "content" and n["_seed"] and (n["size"] or 0) >= 0.6
        n["lod"] = 1 if (n["role"] in LOD1_NETWORK_ROLES and n["_seed"]) or major_content else None
    rest = sorted((n for n in nets if n["lod"] is None), key=lambda n: (not n["_seed"], -(n["size"] or 0), n["asn"]))
    for i, n in enumerate(rest):
        n["lod"] = 2 if i < lod2_networks else 3

    for e in cat.edges:
        e["lod"] = max(nodes[e["source"]]["lod"], nodes[e["target"]]["lod"])


def aggregate_edges(cat: Catalog, per_category: int = 6) -> list[dict]:
    """Coarse-LOD roll-ups of hosted_by edges: realm→region (LOD 0) and category→network (LOD 1)."""
    nodes = cat.nodes
    realm_region = Counter()
    cat_net = Counter()
    for e in cat.edges:
        if e["kind"] != "hosted_by":
            continue
        s, t = nodes[e["source"]], nodes[e["target"]]
        realm_region[(s["realm"], t["region"])] += 1
        if t["lod"] <= 1:
            cat_net[(s["category"], t["id"])] += 1
    out = []
    if realm_region:
        mx = max(realm_region.values())
        by_realm = defaultdict(list)
        for (r, g), c in realm_region.items():
            by_realm[r].append((c, g))
        for r, lst in by_realm.items():
            for c, g in sorted(lst, reverse=True)[:3]:
                out.append({"source": r, "target": g, "kind": "aggregate", "lod": 0,
                            "weight": round(0.25 + 0.75 * c / mx, 3), "count": c})
    if cat_net:
        mx = max(cat_net.values())
        by_cat = defaultdict(list)
        for (c_, t), c in cat_net.items():
            by_cat[c_].append((c, t))
        for c_, lst in by_cat.items():
            for c, t in sorted(lst, reverse=True)[:per_category]:
                out.append({"source": c_, "target": t, "kind": "aggregate", "lod": 1,
                            "weight": round(0.2 + 0.8 * c / mx, 3), "count": c})
    return out


def public_node(n: dict) -> dict:
    return {k: n.get(k) for k in NODE_KEYS}


def public_edge(e: dict, nodes: dict) -> dict:
    return {"source": e["source"], "target": e["target"], "kind": e["kind"], "lod": e["lod"],
            "weight": e["weight"], "count": e.get("count"),
            "a": nodes[e["source"]]["pos"], "b": nodes[e["target"]]["pos"]}


def tile_of(pos: list[float]) -> int:
    theta, phi = to_healpix_angles(np.array(pos, dtype=float))
    return int(hp.ang2pix(2 ** TILE_ORDER, theta, phi, nest=True))


def _dump(obj) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def write_snapshot(cat: Catalog, seed_taxonomy: dict, layout_meta: dict, out_root: Path = SNAPSHOTS_DIR,
                   created_at: dt.datetime | None = None, keep: int = 3) -> str:
    nodes = cat.nodes
    created_at = created_at or dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    edges = [e for e in cat.edges if e["source"] in nodes and e["target"] in nodes]
    edges += aggregate_edges(cat)
    edges.sort(key=lambda e: (e["lod"], e["kind"], e["source"], e["target"]))

    files: dict[str, bytes] = {}
    lods_meta = []
    by_lod_nodes = defaultdict(list)
    for n in sorted(nodes.values(), key=lambda n: (n["lod"], n["kind"], n["id"])):
        by_lod_nodes[n["lod"]].append(public_node(n))
    by_lod_edges = defaultdict(list)
    for e in edges:
        by_lod_edges[e["lod"]].append(public_edge(e, nodes))

    snapshot_placeholder = "__SNAPSHOT_ID__"
    for level in (0, 1, 2):
        doc = {"snapshot_id": snapshot_placeholder, "level": level, "tile": None,
               "nodes": by_lod_nodes[level], "edges": by_lod_edges[level]}
        files[f"lod{level}.json"] = _dump(doc)
        lods_meta.append({"level": level, "file": f"lod{level}.json", "nodes": len(doc["nodes"]),
                          "edges": len(doc["edges"])})

    tile_nodes = defaultdict(list)
    for n in by_lod_nodes[3]:
        tile_nodes[tile_of(n["pos"])].append(n)
    tile_edges = defaultdict(list)
    for e in by_lod_edges[3]:
        tile_edges[tile_of(e["a"])].append(e)
    tiles = []
    for ipix in range(hp.nside2npix(2 ** TILE_ORDER)):
        if not tile_nodes[ipix] and not tile_edges[ipix]:
            continue
        doc = {"snapshot_id": snapshot_placeholder, "level": 3, "tile": {"order": TILE_ORDER, "ipix": ipix},
               "nodes": tile_nodes[ipix], "edges": tile_edges[ipix]}
        name = f"lod3/{TILE_ORDER}-{ipix}.json"
        files[name] = _dump(doc)
        tiles.append({"ipix": ipix, "nodes": len(doc["nodes"]), "edges": len(doc["edges"])})
    lods_meta.append({"level": 3, "tiling": {"scheme": "healpix-nested", "order": TILE_ORDER,
                                             "path": "lod3/{order}-{ipix}.json"},
                      "tiles": tiles, "nodes": len(by_lod_nodes[3]), "edges": len(by_lod_edges[3])})

    # auxiliary files
    anchors = {
        "google": {"anchor": "org:google", "products": {"gmail": "svc:gmail.com", "drive": "svc:drive.google.com",
                                                         "calendar": "svc:calendar.google.com"}},
        "github": {"anchor": "svc:github.com", "products": {}},
        "microsoft": {"anchor": "org:microsoft", "products": {"outlook": "svc:outlook.com",
                                                               "onedrive": "svc:onedrive.live.com",
                                                               "teams": "svc:teams.microsoft.com"}},
        "slack": {"anchor": "svc:slack.com", "products": {}},
        "notion": {"anchor": "svc:notion.so", "products": {}},
        "dropbox": {"anchor": "svc:dropbox.com", "products": {}},
        "aws": {"anchor": "svc:aws.amazon.com", "products": {}},
    }
    anchors = {k: v for k, v in anchors.items() if v["anchor"] in nodes}
    for v in anchors.values():
        v["products"] = {p: nid for p, nid in v["products"].items() if nid in nodes}
    files["anchors.json"] = _dump(anchors)

    asgraph = {
        "relationship_source": cat.relationship_source,
        "nodes": {str(n["asn"]): {"id": n["id"], "label": n["label"], "pos": n["pos"], "role": n["role"],
                                  "country": n["country"], "lod": n["lod"]}
                  for n in nodes.values() if n["kind"] == "network"},
        "rels": [[a, b, r] for a, b, r in cat.rels],
        "tier1": sorted(cat.tier1),
        "hosting": {n["id"]: [f"as:{a}" for a in n["_hosted"] if f"as:{a}" in nodes]
                    for n in nodes.values() if n["kind"] == "service" and n.get("_hosted")},
        "org_networks": {n["id"]: [f"as:{a}" for a in n.get("_asns", []) if f"as:{a}" in nodes]
                         for n in nodes.values() if n["kind"] == "org" and n.get("_asns")},
    }
    files["asgraph.json"] = _dump(asgraph)
    search = sorted(([n["id"], n["label"], n["domain"], n["lod"]] for n in nodes.values()), key=lambda r: r[0])
    files["search.json"] = _dump(search)

    # content hash -> snapshot id
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode())
        h.update(files[name])
    snapshot_id = f"{created_at:%Y%m%d}-{h.hexdigest()[:8]}"
    for name in files:
        files[name] = files[name].replace(snapshot_placeholder.encode(), snapshot_id.encode())
    tile_bytes = {f"lod3/{TILE_ORDER}-{t['ipix']}.json": t for t in tiles}
    for name, t in tile_bytes.items():
        t["bytes"] = len(files[name])
    for lm in lods_meta:
        if "file" in lm:
            lm["bytes"] = len(files[lm["file"]])

    taxonomy_realms = []
    taxonomy_cats = []
    for realm in seed_taxonomy["realms"]:
        taxonomy_realms.append({"id": f"realm:{realm['slug']}", "label": realm["label"], "color": realm["color"],
                                "categories": [f"cat:{c['slug']}" for c in realm["categories"]]})
        for c in realm["categories"]:
            taxonomy_cats.append({"id": f"cat:{c['slug']}", "label": c["label"], "realm": f"realm:{realm['slug']}",
                                  "color": realm["color"]})
    kinds = Counter(n["kind"] for n in nodes.values())
    manifest = {
        "format": "internet-snapshot",
        "format_version": FORMAT_VERSION,
        "snapshot_id": snapshot_id,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "coordinate_system": {"handedness": "left", "up": "+Y", "forward": "+Z", "right": "+X", "units": "m",
                              "azimuth": "degrees from +Z toward +X", "elevation": "degrees above XZ plane",
                              "geo_mapping": {"az": "longitude", "el": f"latitude*{GEO_EL_SCALE}"}},
        "shells": SHELLS,
        "lods": lods_meta,
        "realms": taxonomy_realms,
        "categories": taxonomy_cats,
        "network_roles": seed_taxonomy["network_roles"],
        "files": {"anchors": "anchors.json", "asgraph": "asgraph.json", "search": "search.json"},
        "stats": {"nodes": len(nodes), "edges": len(edges), **{f"{k}s": v for k, v in sorted(kinds.items())},
                  "relationship_source": cat.relationship_source},
        "sources": cat.sources,
        "notes": cat.notes,
        "attribution": "; ".join(s["attribution"] for s in cat.sources if s.get("attribution")),
    }
    files["manifest.json"] = json.dumps(manifest, indent=1, ensure_ascii=False).encode("utf-8")

    out_dir = out_root / snapshot_id
    tmp = out_root / f".{snapshot_id}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    for name, data in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tmp.rename(out_dir)
    (out_root / "latest.json").write_text(json.dumps({
        "snapshot_id": snapshot_id, "created_at": manifest["created_at"], "format_version": FORMAT_VERSION,
        "manifest": f"{snapshot_id}/manifest.json"}, indent=1) + "\n")
    # prune old snapshots
    olds = sorted((p for p in out_root.iterdir() if p.is_dir() and not p.name.startswith(".")), key=lambda p: p.name)
    for p in olds[:-keep] if keep else []:
        if p.name != snapshot_id:
            shutil.rmtree(p)
    return snapshot_id
