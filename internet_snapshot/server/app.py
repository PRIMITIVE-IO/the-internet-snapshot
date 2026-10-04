"""Internet Snapshot API server. Implements docs/snapshot-format.md.

Run with ``python -m internet_snapshot serve``.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
from pathlib import Path

import httpx
from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import FORMAT_VERSION, __version__
from ..config import ROOT, SHELLS, SNAPSHOTS_DIR
from ..geo import geo_dir, placement, region_for_country
from ..overlay import CONNECTORS, ProviderAuthError, ProviderError, connector_specs
from ..overlay.placement import place_overlay
from ..sources import SOURCES
from ..sources import parsers as P
from .store import SnapshotStore

log = logging.getLogger("internet_snapshot.server")

app = FastAPI(title="The Internet Snapshot", version=__version__,
              description="Frozen 3D snapshot of the internet for Primitive environment clients. "
                          "See docs/snapshot-format.md.")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST", "OPTIONS"],
                   allow_headers=["*"])

if (ROOT / "viewer").is_dir():
    app.mount("/viewer", StaticFiles(directory=ROOT / "viewer", html=True), name="viewer")


@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/viewer/")


store = SnapshotStore(Path(os.environ.get("SNAPSHOT_DIR", SNAPSHOTS_DIR)))


class _Lookup:
    """Optional IP->ASN and ASN metadata used by /whereami and /route; loaded lazily if downloaded."""

    def __init__(self):
        self.loaded = False
        self.ip_table = None
        self.asninfo: dict = {}
        self.countries: dict = {}

    def ensure(self):
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
            self.ip_table = P.OriginAsnTable.load(SOURCES["originasn"].path)
        if SOURCES["asninfo"].available():
            self.asninfo = P.load_asninfo(SOURCES["asninfo"].path)
        if SOURCES["countries"].available():
            self.countries = P.load_countries(SOURCES["countries"].path)


lookups = _Lookup()


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _home(snap, ip: str | None, asn: int | None) -> dict:
    lookups.ensure()
    out = {"ip": ip, "asn": asn, "node": None, "label": None, "in_snapshot": False, "pos": None,
           "country": None, "region": None}
    if asn is None and ip:
        try:
            if ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_loopback:
                out["note"] = "private or loopback address; pass ?asn= or ?ip= with a public address"
        except ValueError:
            raise HTTPException(400, f"invalid ip {ip!r}")
        if lookups.ip_table is not None:
            asn = lookups.ip_table.lookup(ip)
        out["asn"] = asn
    if asn is None:
        return out
    node = snap.nodes.get(f"as:{asn}")
    info = lookups.asninfo.get(asn, {})
    if node:
        out.update(node=node["id"], label=node["label"], in_snapshot=True, pos=node["pos"],
                   country=node.get("country"), region=node.get("region"))
        return out
    cc = info.get("country")
    out.update(node=f"as:{asn}", label=info.get("name") or f"AS{asn}", country=cc,
               region=f"region:{region_for_country(cc)}")
    if cc and cc in lookups.countries:
        c = lookups.countries[cc]
        out["pos"] = placement(geo_dir(c["lat"], c["lon"]), SHELLS["backbone"])["pos"]
    else:
        rnode = snap.nodes.get(out["region"])
        out["pos"] = rnode["pos"] if rnode else [0.0, 0.0, SHELLS["backbone"]]
    return out


# ------------------------------------------------------------------------------------------
# snapshot files

@app.get("/healthz")
def healthz():
    snap = store.current()
    return {"ok": True, "snapshot_id": snap.id, "format_version": FORMAT_VERSION, "version": __version__}


@app.get("/v1/snapshots/latest")
@app.get("/v1/snapshots/latest.json")
def latest():
    return FileResponse(store.latest_path, media_type="application/json",
                        headers={"Cache-Control": "public, max-age=60"})


@app.get("/v1/snapshots/{snapshot_id}/{path:path}")
def snapshot_file(snapshot_id: str, path: str):
    root = store.root.resolve()
    target = (root / snapshot_id / path).resolve()
    if root not in target.parents or not target.is_file() or snapshot_id.startswith("."):
        raise HTTPException(404, "not found")
    return FileResponse(target, media_type="application/json",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ------------------------------------------------------------------------------------------
# queries

@app.get("/v1/whereami")
def whereami(request: Request, ip: str | None = None, asn: int | None = None):
    snap = store.current()
    return _home(snap, ip or (None if asn else _client_ip(request)), asn)


@app.get("/v1/route")
def route(request: Request, to: str = Query(..., description="node id, domain, hostname or URL"),
          ip: str | None = None, asn: int | None = None):
    snap = store.current()
    dest = snap.find_node(to)
    if dest is None:
        raise HTTPException(404, f"no node matches {to!r}")
    home = _home(snap, ip or (None if asn else _client_ip(request)), asn)
    if home["asn"] is None:
        raise HTTPException(422, "could not determine the home network; pass ?asn= or ?ip=")
    g = snap.asgraph
    if dest["kind"] == "network":
        dst_nodes = [dest["id"]]
    elif dest["kind"] == "service":
        dst_nodes = g.hosting.get(dest["id"]) or g.org_networks.get(dest.get("org") or "", [])
    elif dest["kind"] == "org":
        dst_nodes = g.org_networks.get(dest["id"], [])
    else:
        raise HTTPException(400, f"cannot route to a {dest['kind']}; pick a service, org or network")
    dst_asns = [int(n.split(":", 1)[1]) for n in dst_nodes]
    src = int(home["asn"])
    region = (home.get("region") or "").removeprefix("region:") or None
    if dst_asns:
        r = g.route(src, dst_asns, region)
    else:
        r = {"as_path": [src], "method": "fallback", "confidence": "low"}

    hops = [{"seq": 0, "node": "home", "kind": "home", "label": "Home network", "pos": [0.0, 0.0, 0.0], "rel": None}]
    path = r["as_path"]
    for i, a in enumerate(path):
        nid = f"as:{a}"
        n = snap.nodes.get(nid)
        if n is None and a == src:
            pos, label = home["pos"], home["label"]
        elif n is None:
            pos, label = None, f"AS{a}"
        else:
            pos, label = n["pos"], n["label"]
        rel = "origin" if i == 0 else g.rel(path[i - 1], a)
        if i > 0 and rel == "sibling" and not g.known(path[i - 1]):
            rel = "up"  # synthetic attachment of an unknown home AS to its fallback upstream
        hops.append({"seq": len(hops), "node": nid, "kind": "network", "asn": a, "label": label, "pos": pos, "rel": rel})
    if dest["kind"] in ("service", "org"):
        hops.append({"seq": len(hops), "node": dest["id"], "kind": dest["kind"], "label": dest["label"],
                     "pos": dest["pos"], "rel": "served"})
    return {
        "snapshot_id": snap.id,
        "from": home,
        "to": {"query": to, "node": dest["id"], "label": dest["label"], "kind": dest["kind"],
               "network": f"as:{path[-1]}" if dst_asns else None, "pos": dest["pos"]},
        "method": r["method"], "confidence": r["confidence"], "relationship_source": g.relationship_source,
        "as_path": path, "hops": hops,
    }


@app.get("/v1/search")
def search(q: str, limit: int = Query(20, ge=1, le=200)):
    snap = store.current()
    return [{"id": n["id"], "label": n["label"], "kind": n["kind"], "domain": n.get("domain"), "lod": n["lod"],
             "pos": n["pos"]} for n in snap.search(q, limit)]


@app.get("/v1/node/{node_id:path}")
def node(node_id: str):
    snap = store.current()
    n = snap.nodes.get(node_id) or snap.find_node(node_id)
    if n is None:
        raise HTTPException(404, f"no node {node_id!r}")
    return {"node": n, "edges": snap.edges_by_node.get(n["id"], [])[:500],
            "children": snap.children.get(n["id"], [])}


# ------------------------------------------------------------------------------------------
# personal overlays (stateless proxy)

@app.get("/v1/connectors")
def connectors():
    snap = store.current()
    specs = connector_specs()
    for s in specs:
        s["anchor_present"] = s["anchor"] in snap.nodes
        s["products"] = snap.anchors.get(s["provider"], {}).get("products", {})
    return specs


@app.post("/v1/overlay/{provider}")
async def overlay(provider: str, authorization: str | None = Header(None), body: dict | None = Body(None)):
    conn = CONNECTORS.get(provider)
    if conn is None:
        raise HTTPException(404, f"unknown provider {provider!r}; see /v1/connectors")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "send the provider access token as 'Authorization: Bearer <token>'")
    token = authorization.split(" ", 1)[1].strip()
    body = body or {}
    max_assets = max(1, min(int(body.get("max_assets", 60)), 200))
    account_index = int(body.get("account_index", 0))
    account_count = max(1, int(body.get("account_count", 1)))
    snap = store.current()
    anchor_id = snap.anchors.get(provider, {}).get("anchor") or conn.anchor
    anchor = snap.nodes.get(anchor_id)
    if anchor is None:
        raise HTTPException(500, f"anchor {anchor_id} missing from snapshot {snap.id}")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            acct = await conn.fetch(client, token, max_assets)
    except ProviderAuthError as e:
        raise HTTPException(401, str(e))
    except (ProviderError, httpx.HTTPError) as e:
        raise HTTPException(502, f"{provider}: {e}")
    finally:
        del token
    node_pos = {nid: n["pos"] for nid, n in snap.nodes.items() if nid.startswith("svc:") or nid.startswith("org:")}
    nodes, edges = place_overlay(provider=provider, account_id=acct.id, account_label=acct.label,
                                 account_meta=acct.meta, anchor_id=anchor_id, anchor_pos=anchor["pos"],
                                 groups=acct.groups, node_pos=node_pos, account_index=account_index,
                                 account_count=account_count)
    doc = {"overlay_version": FORMAT_VERSION, "snapshot_id": snap.id, "provider": provider,
           "account": {"id": acct.id, "label": acct.label}, "warnings": acct.warnings,
           "nodes": nodes, "edges": edges}
    return JSONResponse(doc, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
