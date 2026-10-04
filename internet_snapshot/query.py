"""Query functions shared by the API server and the MCP server."""

from __future__ import annotations

import ipaddress
import json
import logging
import os
from bisect import bisect_right

from .config import SHELLS
from .geo import geo_dir, placement, region_for_country
from .locate import activity_overlay
from .server.store import Snapshot
from .sources import SOURCES
from .sources import parsers as P

log = logging.getLogger(__name__)


class QueryError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class HomeLookup:
    """IP → ASN. Uses the local origin-asn table if downloaded, otherwise the Pages ip2asn shards."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url
        self.loaded = False
        self.table = None
        self.asninfo: dict = {}
        self.countries: dict = {}
        self._shards: dict[int, list] = {}

    def ensure(self) -> None:
        if self.loaded:
            return
        self.loaded = True
        if os.environ.get("SNAPSHOT_FETCH_LOOKUPS") == "1":
            for sid in ("originasn", "asninfo", "countries"):
                try:
                    SOURCES[sid].fetch()
                except Exception as e:  # serve without it
                    log.warning("could not fetch %s: %s", sid, e)
        if SOURCES["originasn"].available():
            self.table = P.OriginAsnTable.load(SOURCES["originasn"].path)
        if SOURCES["asninfo"].available():
            self.asninfo = P.load_asninfo(SOURCES["asninfo"].path)
        if SOURCES["countries"].available():
            self.countries = P.load_countries(SOURCES["countries"].path)

    def asn_for(self, ip: str) -> int | None:
        self.ensure()
        if self.table is not None:
            return self.table.lookup(ip)
        if not self.base_url:
            return None
        addr = ipaddress.ip_address(ip)
        if addr.version != 4:
            return None
        x = int(addr)
        octet = x >> 24
        if octet not in self._shards:
            import httpx
            r = httpx.get(f"{self.base_url.rstrip('/')}/ip2asn/v4/{octet}.json", timeout=30)
            self._shards[octet] = r.json()["ranges"] if r.status_code == 200 else []
        ranges = self._shards[octet]
        i = bisect_right([rg[0] for rg in ranges], x) - 1
        if i >= 0 and ranges[i][0] <= x <= ranges[i][1]:
            return int(ranges[i][2])
        return None


def home(snap: Snapshot, lookup: HomeLookup, ip: str | None, asn: int | None) -> dict:
    out = {"ip": ip, "asn": asn, "node": None, "label": None, "in_snapshot": False, "pos": None,
           "country": None, "region": None}
    if asn is None and ip:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            raise QueryError(400, f"invalid ip {ip!r}")
        if addr.is_private or addr.is_loopback:
            out["note"] = "private or loopback address; pass asn or a public ip"
        else:
            asn = lookup.asn_for(ip)
        out["asn"] = asn
    if asn is None:
        return out
    node = snap.nodes.get(f"as:{asn}")
    if node:
        out.update(node=node["id"], label=node["label"], in_snapshot=True, pos=node["pos"],
                   country=node.get("country"), region=node.get("region"))
        return out
    lookup.ensure()
    info = lookup.asninfo.get(asn, {})
    cc = info.get("country")
    out.update(node=f"as:{asn}", label=info.get("name") or f"AS{asn}", country=cc,
               region=f"region:{region_for_country(cc)}")
    if cc and cc in lookup.countries:
        c = lookup.countries[cc]
        out["pos"] = placement(geo_dir(c["lat"], c["lon"]), SHELLS["backbone"])["pos"]
    else:
        rnode = snap.nodes.get(out["region"])
        out["pos"] = rnode["pos"] if rnode else [0.0, 0.0, SHELLS["backbone"]]
    return out


def route(snap: Snapshot, lookup: HomeLookup, to: str, ip: str | None = None, asn: int | None = None) -> dict:
    dest = snap.find_node(to)
    if dest is None:
        raise QueryError(404, f"no node matches {to!r}")
    h = home(snap, lookup, ip, asn)
    if h["asn"] is None:
        raise QueryError(422, "could not determine the home network; pass asn or ip")
    g = snap.asgraph
    if dest["kind"] == "network":
        dst_nodes = [dest["id"]]
    elif dest["kind"] == "service":
        dst_nodes = g.hosting.get(dest["id"]) or g.org_networks.get(dest.get("org") or "", [])
    elif dest["kind"] == "org":
        dst_nodes = g.org_networks.get(dest["id"], [])
    else:
        raise QueryError(400, f"cannot route to a {dest['kind']}; pick a service, org or network")
    dst_asns = [int(n.split(":", 1)[1]) for n in dst_nodes]
    src = int(h["asn"])
    region = (h.get("region") or "").removeprefix("region:") or None
    r = g.route(src, dst_asns, region) if dst_asns else {"as_path": [src], "method": "fallback", "confidence": "low"}
    hops = [{"seq": 0, "node": "home", "kind": "home", "label": "Home network", "pos": [0.0, 0.0, 0.0], "rel": None}]
    path = r["as_path"]
    for i, a in enumerate(path):
        nid = f"as:{a}"
        n = snap.nodes.get(nid)
        if n is None and a == src:
            pos, label = h["pos"], h["label"]
        elif n is None:
            pos, label = None, f"AS{a}"
        else:
            pos, label = n["pos"], n["label"]
        rel = "origin" if i == 0 else g.rel(path[i - 1], a)
        if i > 0 and rel == "sibling" and not g.known(path[i - 1]):
            rel = "up"
        hops.append({"seq": len(hops), "node": nid, "kind": "network", "asn": a, "label": label, "pos": pos, "rel": rel})
    if dest["kind"] in ("service", "org"):
        hops.append({"seq": len(hops), "node": dest["id"], "kind": dest["kind"], "label": dest["label"],
                     "pos": dest["pos"], "rel": "served"})
    return {"snapshot_id": snap.id, "from": h,
            "to": {"query": to, "node": dest["id"], "label": dest["label"], "kind": dest["kind"],
                   "network": f"as:{path[-1]}" if dst_asns else None, "pos": dest["pos"]},
            "method": r["method"], "confidence": r["confidence"], "relationship_source": g.relationship_source,
            "as_path": path, "hops": hops}


def describe(snap: Snapshot, node_id: str, max_edges: int = 200) -> dict:
    n = snap.nodes.get(node_id) or snap.find_node(node_id)
    if n is None:
        raise QueryError(404, f"no node {node_id!r}")
    return {"node": n, "edges": snap.edges_by_node.get(n["id"], [])[:max_edges],
            "children": snap.children.get(n["id"], []),
            "site_graph": n.get("portal")}


def _site_for(snap: Snapshot, target: str) -> dict:
    if target in snap.locator.site_index:
        return snap.site(target)
    n = snap.find_node(target)
    if n is None:
        raise QueryError(404, f"no node or site {target!r}")
    sid = n.get("portal") or (snap.nodes.get(n.get("org") or "") or {}).get("portal")
    if not sid:
        raise QueryError(404, f"{n['id']} has no site graph")
    return snap.site(sid)


def site_summary(snap: Snapshot, target: str, depth: int = 2) -> dict:
    doc = _site_for(snap, target)
    counts: dict[str, int] = {}
    for x in doc["nodes"]:
        if x["parent"]:
            counts[x["parent"]] = counts.get(x["parent"], 0) + 1
    keep = [{"id": x["id"], "kind": x["kind"], "label": x["label"], "depth": x["depth"], "parent": x["parent"],
             "size": x["size"], "children": counts.get(x["id"], 0), "url": x["url"], "glyph": x["glyph"],
             "portal": x.get("portal")}
            for x in doc["nodes"] if x["depth"] <= depth]
    return {"id": doc["id"], "label": doc["label"], "kind": doc["kind"], "root_node": doc["root_node"],
            "total_nodes": len(doc["nodes"]), "max_depth": doc["max_depth"], "nodes": keep}


def list_endpoints(snap: Snapshot, target: str, query: str | None = None, limit: int = 50) -> dict:
    doc = _site_for(snap, target)
    q = (query or "").lower()
    out = []
    for x in doc["nodes"]:
        if x["kind"] not in ("operation", "api", "host", "section", "endpoint"):
            continue
        blob = " ".join(str(v) for v in (x["label"], x.get("path"), x.get("host"), x["id"]) if v).lower()
        if q and not all(t in blob for t in q.split()):
            continue
        out.append({"id": x["id"], "kind": x["kind"], "label": x["label"], "method": x.get("method"),
                    "host": x.get("host"), "path": x.get("path"), "doc_url": x.get("url"), "size": x["size"]})
    out.sort(key=lambda e: (-e["size"], e["id"]))
    return {"site": doc["id"], "total": len(out), "endpoints": out[:limit]}


def code_universe(snap: Snapshot, ecosystem: str | None = None, query: str | None = None, limit: int = 30) -> dict:
    doc = snap.site("site:code-universe")
    if doc is None:
        raise QueryError(404, "this snapshot has no code universe")
    by_id = {x["id"]: x for x in doc["nodes"]}
    ecos = [x for x in doc["nodes"] if x["kind"] == "ecosystem"]
    if not ecosystem and not query:
        return {"ecosystems": [{"id": e["id"], "label": e["label"], "registry": e["meta"].get("registry"),
                                "size": e["size"]} for e in sorted(ecos, key=lambda e: -e["size"])]}
    eco_ids = {e["id"] for e in ecos if not ecosystem or ecosystem.lower() in (e["id"] + " " + e["label"]).lower()}
    q = (query or "").lower()
    repos = []
    for x in doc["nodes"]:
        if x["kind"] != "repo":
            continue
        cur = x
        while cur["depth"] > 1:
            cur = by_id[cur["parent"]]
        if cur["id"] not in eco_ids:
            continue
        m = x["meta"]
        if q and q not in (m.get("full_name", "") + " " + (m.get("description") or "")).lower():
            continue
        repos.append({"id": x["id"], "full_name": m.get("full_name"), "stars": m.get("stars"),
                      "language": m.get("language"), "ecosystem": cur["label"],
                      "cluster": by_id[x["parent"]]["label"], "description": m.get("description"), "url": x["url"]})
    repos.sort(key=lambda r: -(r["stars"] or 0))
    return {"total": len(repos), "repos": repos[:limit]}


def activity(snap: Snapshot, events: list[dict]) -> dict:
    return activity_overlay(events, snap.locator, snap.id)


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
