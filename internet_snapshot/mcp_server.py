"""MCP server (stdio) exposing the Internet Snapshot to AI agents (docs/snapshot-format.md §15).

It reads a local snapshots directory or any static base URL (GitHub Pages by default), so each
agent can run it next to itself with no hosted server. Tool results use the contract's node ids,
so the Primitive environment can place an agent's findings and activity in the 3D map.

    pip install 'internet-snapshot[mcp] @ git+https://github.com/PRIMITIVE-IO/the-internet-snapshot'
    SNAPSHOT_BASE_URL=https://documentation.primitive.io/the-internet-snapshot python -m internet_snapshot mcp
"""

from __future__ import annotations

import os
from pathlib import Path

from . import query as Q
from .build.pages import PAGES_BASE
from .config import SNAPSHOTS_DIR
from .server.store import SnapshotStore
from .sites.ondemand import graph_from_urls

INSTRUCTIONS = """The Internet Snapshot: a map of the internet's services, networks and per-site endpoints.
- search(query): find services, orgs and networks.
- locate(url): before calling an unfamiliar URL or API, find which service, site section and API operation it is,
  with a documentation link.
- list_endpoints(target, query): enumerate a service's API operations and hosts (target: domain or node id).
- site_graph(target, depth): the hierarchy of a site (surfaces → products → hosts/APIs → operations).
- route(to, asn|ip): the estimated network path from a home network to a service.
- code_universe(ecosystem, query): the top open-source repositories by package ecosystem.
- activity_overlay(events): turn a list of {agent, ts, kind, method, url, status} into positions for visualisation.
Node ids are stable: svc:<domain>, org:<slug>, as:<asn>, site:<id>/...
"""


def _make_server(name: str):
    try:
        from mcp.server.mcpserver import MCPServer  # mcp >= 2
        return MCPServer(name=name, instructions=INSTRUCTIONS)
    except ImportError:
        from mcp.server.fastmcp import FastMCP  # mcp 1.x
        return FastMCP(name, instructions=INSTRUCTIONS)


def build_server(base: str | None = None):
    base = base or os.environ.get("SNAPSHOT_BASE_URL")
    if base is None:
        base = str(SNAPSHOTS_DIR) if (SNAPSHOTS_DIR / "latest.json").exists() else PAGES_BASE
    remote = base.startswith(("http://", "https://"))
    if remote:
        store = SnapshotStore(base.rstrip("/").removesuffix("/snapshots"))
    else:
        p = Path(base)
        store = SnapshotStore(p if (p / "latest.json").exists() else p / "snapshots")
    lookups = Q.HomeLookup(base if remote else None)
    server = _make_server("internet-snapshot")

    def snap():
        return store.current()

    def safe(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Q.QueryError as e:
            return {"error": str(e), "status": e.status}

    @server.tool()
    def search(query: str, limit: int = 20) -> dict:
        """Find services, orgs, categories and networks by name or domain."""
        s = snap()
        return {"snapshot_id": s.id, "results": [
            {"id": n["id"], "label": n["label"], "kind": n["kind"], "domain": n.get("domain"),
             "category": n.get("category"), "site_graph": n.get("portal")} for n in s.search(query, limit)]}

    @server.tool()
    def describe(node_id: str) -> dict:
        """Details of a node (id, domain or URL): position, hierarchy, edges and whether a site graph exists."""
        return safe(Q.describe, snap(), node_id, 100)

    @server.tool()
    def locate(url: str, method: str | None = None) -> dict:
        """Map a URL (and optional HTTP method) to its service, site-graph node and API operation."""
        return snap().locator.locate(url, method)

    @server.tool()
    def route(to: str, asn: int | None = None, ip: str | None = None) -> dict:
        """Estimated AS-level route from a home network (asn or public ip) to a service, org or network."""
        return safe(Q.route, snap(), lookups, to, ip, asn)

    @server.tool()
    def whereami(ip: str) -> dict:
        """Map a public IPv4 address to its network (AS) and position on the backbone shell."""
        return safe(Q.home, snap(), lookups, ip, None)

    @server.tool()
    def site_graph(target: str, depth: int = 2) -> dict:
        """Hierarchy of a site's endpoints (target: site id, node id or domain), down to the given depth."""
        return safe(Q.site_summary, snap(), target, depth)

    @server.tool()
    def list_endpoints(target: str, query: str | None = None, limit: int = 50) -> dict:
        """API operations, hosts and sections of a service (e.g. target='github.com', query='issues')."""
        return safe(Q.list_endpoints, snap(), target, query, limit)

    @server.tool()
    def code_universe(ecosystem: str | None = None, query: str | None = None, limit: int = 30) -> dict:
        """Top open-source repositories on GitHub grouped by package ecosystem (.NET, Maven, npm, PyPI, ...)."""
        return safe(Q.code_universe, snap(), ecosystem, query, limit)

    @server.tool()
    def activity_overlay(events: list[dict]) -> dict:
        """Turn agent activity events [{agent, ts, kind, method, url, status}] into an overlay with positions."""
        return Q.activity(snap(), events)

    @server.tool()
    def visited_site_graph(urls: list[str], label: str | None = None) -> dict:
        """Lay out a site graph from a list of visited URLs (for sites without a precomputed graph)."""
        try:
            return graph_from_urls(urls, label)
        except ValueError as e:
            return {"error": str(e)}

    server._snapshot_store = store
    return server


def main(base: str | None = None) -> int:
    build_server(base).run("stdio")
    return 0
