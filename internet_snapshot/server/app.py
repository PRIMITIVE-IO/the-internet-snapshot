"""Internet Snapshot API server. Implements docs/snapshot-format.md.

Run with ``python -m internet_snapshot serve``. Everything here also works without a server: see
snapshot-format.md §10 and the MCP server (§15).
"""

from __future__ import annotations

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
from .. import query as Q
from ..config import PUBLIC_DIR, ROOT, SNAPSHOTS_DIR
from ..overlay import CONNECTORS, ProviderAuthError, ProviderError, connector_specs
from ..overlay.placement import place_overlay
from ..sites.ondemand import graph_from_urls
from .store import SnapshotStore

log = logging.getLogger("internet_snapshot.server")

app = FastAPI(title="The Internet Snapshot", version=__version__,
              description="Frozen 3D snapshot of the internet for Primitive environment clients and AI agents. "
                          "See docs/snapshot-format.md.")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST", "OPTIONS"],
                   allow_headers=["*"])

if (ROOT / "viewer").is_dir():
    app.mount("/viewer", StaticFiles(directory=ROOT / "viewer", html=True), name="viewer")
if (PUBLIC_DIR / "icons").is_dir():
    app.mount("/icons", StaticFiles(directory=PUBLIC_DIR / "icons"), name="icons")


@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/viewer/")


store = SnapshotStore(Path(os.environ.get("SNAPSHOT_DIR", SNAPSHOTS_DIR)))
lookups = Q.HomeLookup(os.environ.get("SNAPSHOT_BASE_URL"))


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _q(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except Q.QueryError as e:
        raise HTTPException(e.status, str(e))


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
    root = Path(store.root).resolve()
    target = (root / snapshot_id / path).resolve()
    if root not in target.parents or not target.is_file() or snapshot_id.startswith("."):
        raise HTTPException(404, "not found")
    return FileResponse(target, media_type="application/json",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ------------------------------------------------------------------------------------------
# queries

@app.get("/v1/whereami")
def whereami(request: Request, ip: str | None = None, asn: int | None = None):
    return _q(Q.home, store.current(), lookups, ip or (None if asn else _client_ip(request)), asn)


@app.get("/v1/route")
def route(request: Request, to: str = Query(..., description="node id, domain, hostname or URL"),
          ip: str | None = None, asn: int | None = None):
    return _q(Q.route, store.current(), lookups, to, ip or (None if asn else _client_ip(request)), asn)


@app.get("/v1/locate")
def locate(url: str, method: str | None = None):
    return store.current().locator.locate(url, method)


@app.get("/v1/search")
def search(q: str, limit: int = Query(20, ge=1, le=200)):
    return [{"id": n["id"], "label": n["label"], "kind": n["kind"], "domain": n.get("domain"), "lod": n["lod"],
             "pos": n["pos"], "portal": n.get("portal")} for n in store.current().search(q, limit)]


@app.get("/v1/node/{node_id:path}")
def node(node_id: str):
    return _q(Q.describe, store.current(), node_id, 500)


@app.get("/v1/sites")
def sites():
    snap = store.current()
    return {"snapshot_id": snap.id, "sites": snap.sites_index}


@app.get("/v1/sites/{site_id:path}/summary")
def site_summary(site_id: str, depth: int = Query(2, ge=1, le=6)):
    return _q(Q.site_summary, store.current(), site_id, depth)


@app.get("/v1/sites/{site_id:path}/endpoints")
def site_endpoints(site_id: str, q: str | None = None, limit: int = Query(50, ge=1, le=2000)):
    return _q(Q.list_endpoints, store.current(), site_id, q, limit)


@app.get("/v1/sites/{site_id:path}")
def site(site_id: str):
    doc = store.current().site(site_id)
    if doc is None:
        raise HTTPException(404, f"no site graph {site_id!r}; see /v1/sites")
    return doc


@app.get("/v1/code-universe")
def code_universe(ecosystem: str | None = None, q: str | None = None, limit: int = Query(30, ge=1, le=500)):
    return _q(Q.code_universe, store.current(), ecosystem, q, limit)


@app.post("/v1/site-graph")
def site_graph_from_urls(body: dict = Body(..., examples=[{"urls": ["https://example.com/a/b"], "label": None}])):
    urls = body.get("urls") or []
    if not isinstance(urls, list) or not urls or len(urls) > 20000:
        raise HTTPException(400, "send {'urls': [...]} with 1..20000 URLs")
    try:
        doc = graph_from_urls([str(u) for u in urls], body.get("label"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse(doc, headers={"Cache-Control": "no-store"})


@app.post("/v1/activity")
def activity(body: dict = Body(...)):
    events = body.get("events") or []
    if not isinstance(events, list) or len(events) > 50000:
        raise HTTPException(400, "send {'events': [...]} with at most 50000 events")
    return JSONResponse(Q.activity(store.current(), events), headers={"Cache-Control": "no-store"})


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
