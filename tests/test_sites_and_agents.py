"""Site graphs, code universe, locate, activity overlays, ip2asn shards, MCP (snapshot-format.md §10–§15)."""

import asyncio
import json
import math

import numpy as np
import pytest

from internet_snapshot.config import SNAPSHOTS_DIR
from internet_snapshot.locate import agent_color, path_score
from internet_snapshot.sites.model import SITE_NODE_KEYS, host_matches
from internet_snapshot.sites.ondemand import graph_from_urls

LATEST = SNAPSHOTS_DIR / "latest.json"
needs_snapshot = pytest.mark.skipif(not LATEST.exists(), reason="no published snapshot")


def test_host_and_path_matching():
    assert host_matches("*.githubusercontent.com", "raw.githubusercontent.com")
    assert host_matches("*-aiplatform.googleapis.com", "us-central1-aiplatform.googleapis.com")
    assert not host_matches("*.github.io", "github.com")
    assert path_score("/repos/{owner}/{repo}/issues", "/repos/a/b/issues") == (1, 2, 4)
    assert path_score("/repos/{owner}/{repo}/issues", "/repos/a/b/issues/7") == (0, 2, 4)
    assert path_score("/repos/{owner}/{repo}/pulls", "/repos/a/b/issues") is None
    assert path_score("/orgs/{org}", "/orgs/acme")[1] > path_score("/{owner}/{repo}", "/orgs/acme")[1]


def test_graph_from_urls_collapses_ids_and_lays_out():
    doc = graph_from_urls(["https://shop.example.com/items/12345/reviews", "https://shop.example.com/items/999",
                           "https://shop.example.com/cart", "https://cdn.example.com/img/a.png"])
    ids = {n["id"] for n in doc["nodes"]}
    assert any(i.endswith("/items/{id}") for i in ids)
    for n in doc["nodes"]:
        assert tuple(n.keys()) == SITE_NODE_KEYS
        assert abs(n["r"] - doc["shells"][n["depth"]]) < 0.05


def test_agent_color_is_deterministic():
    assert agent_color("planner-1") == agent_color("planner-1")
    assert agent_color("planner-1").startswith("#") and len(agent_color("x")) == 7


def test_ip2asn_shards_split_on_octet_boundaries(tmp_path, monkeypatch):
    from internet_snapshot.build import pages
    from internet_snapshot.sources import parsers as P

    table = P.OriginAsnTable(np.array([16777216, 33554176], dtype=np.int64), np.array([16777471, 33554687], dtype=np.int64),
                             np.array([13335, 64500], dtype=np.int64), {})
    monkeypatch.setattr(P.OriginAsnTable, "load", classmethod(lambda cls, path: table))
    n = pages.build_ip2asn(tmp_path)
    assert n == 2
    two = json.loads((tmp_path / "2.json").read_text())["ranges"]
    assert two == [[33554432, 33554687, 64500]]          # 2.0.0.0 - 2.0.1.255
    one = json.loads((tmp_path / "1.json").read_text())["ranges"]
    assert [16777216, 16777471, 13335] in one and [33554176, 33554431, 64500] in one


@pytest.fixture(scope="module")
def snap():
    from internet_snapshot.server.store import SnapshotStore
    return SnapshotStore().current()


@needs_snapshot
def test_site_graph_files_follow_contract(snap):
    index = snap.sites_index
    assert {"site:github", "site:google", "site:code-universe"} <= {s["id"] for s in index}
    for meta in index[:40] + [s for s in index if s["id"] in ("site:github", "site:google", "site:code-universe")]:
        doc = snap.json(meta["file"])
        assert doc["id"] == meta["id"] and len(doc["nodes"]) == meta["nodes"]
        ids = {n["id"] for n in doc["nodes"]}
        for n in doc["nodes"]:
            assert tuple(n.keys()) == SITE_NODE_KEYS
            assert n["parent"] is None or n["parent"] in ids
            assert 0 <= n["size"] <= 1
            assert abs(math.dist(n["pos"], [0, 0, 0]) - doc["shells"][n["depth"]]) < 0.1
        for e in doc["edges"]:
            assert e["source"] in ids and e["target"] in ids


@needs_snapshot
def test_portals_link_global_nodes_to_sites(snap):
    sites = {s["id"] for s in snap.sites_index}
    portals = [n for n in snap.nodes.values() if n.get("portal")]
    assert portals and all(n["portal"] in sites for n in portals)
    assert snap.nodes["svc:github.com"]["portal"] == "site:github"
    assert snap.nodes["org:google"]["portal"] == "site:google"
    assert snap.nodes["svc:gmail.com"]["portal"] == "site:google"


@needs_snapshot
def test_github_site_and_code_universe(snap):
    gh = snap.site("site:github")
    ops = [n for n in gh["nodes"] if n["kind"] == "operation"]
    assert len(ops) > 500 and all(n["method"] and n["path"] and n["host"] == "api.github.com" for n in ops)
    opensource = next(n for n in gh["nodes"] if n["id"] == "site:github/opensource")
    assert opensource["portal"] == "site:code-universe"
    cu = snap.site("site:code-universe")
    ecos = {n["label"] for n in cu["nodes"] if n["kind"] == "ecosystem"}
    for want in (".NET (NuGet)", "JVM (Maven)", "JavaScript (npm)", "Python (PyPI)", "Ruby (RubyGems)", "PHP (Packagist)"):
        assert want in ecos
    repos = [n for n in cu["nodes"] if n["kind"] == "repo"]
    assert len(repos) > 1000 and all(n["meta"]["stars"] > 0 for n in repos)


@needs_snapshot
def test_locate(snap):
    loc = snap.locator.locate
    r = loc("https://api.github.com/repos/octo/hello/issues", "GET")
    assert r["match"] == "operation" and r["operation"]["path"] == "/repos/{owner}/{repo}/issues"
    assert r["site"]["path"][0] == "site:github"
    r = loc("https://github.com/microsoft/vscode/pulls")
    assert r["site"]["node"] == "site:github/web/pulls" and r["match"] == "path"
    assert r["also"]["node"].startswith("site:code-universe/")
    r = loc("https://mail.google.com/mail/u/0/#inbox")
    assert r["global"]["node"] == "svc:gmail.com" and r["site"]["id"] == "site:google"
    assert loc("https://definitely-not-in-the-map.invalid/")["match"] == "none"


@needs_snapshot
def test_activity_overlay(snap):
    from internet_snapshot import query as Q
    ov = Q.activity(snap, [
        {"agent": "a1", "ts": "2026-10-04T00:00:01Z", "kind": "http", "method": "GET",
         "url": "https://api.github.com/repos/o/r/issues"},
        {"agent": "a1", "ts": "2026-10-04T00:00:02Z", "kind": "browse", "url": "https://mail.google.com/"},
        {"agent": "a2", "ts": "2026-10-04T00:00:03Z", "kind": "http", "url": "https://api.github.com/user"},
    ])
    agents = {a["id"]: a for a in ov["agents"]}
    assert set(agents) == {"ag:a1", "ag:a2"}
    assert agents["ag:a1"]["at"]["node"] == "svc:gmail.com" and len(agents["ag:a1"]["trail"]) == 2
    heat = {(h["space"], h["node"]): h["count"] for h in ov["heat"]}
    assert heat[("global", "svc:github.com")] == 2


@needs_snapshot
def test_query_endpoints_and_code_universe(snap):
    from internet_snapshot import query as Q
    eps = Q.list_endpoints(snap, "github.com", "issues", 5)
    assert eps["site"] == "site:github" and eps["endpoints"]
    summ = Q.site_summary(snap, "google.com", 1)
    assert summ["id"] == "site:google" and all(n["depth"] <= 1 for n in summ["nodes"])
    cu = Q.code_universe(snap, "maven", None, 5)
    assert cu["repos"] and all(r["ecosystem"] == "JVM (Maven)" for r in cu["repos"])


@needs_snapshot
def test_server_v02_endpoints():
    from fastapi.testclient import TestClient
    from internet_snapshot.server.app import app
    c = TestClient(app)
    assert c.get("/v1/locate", params={"url": "https://api.github.com/user", "method": "GET"}).json()["match"] == "operation"
    assert any(s["id"] == "site:github" for s in c.get("/v1/sites").json()["sites"])
    assert c.get("/v1/sites/site:github/summary").json()["id"] == "site:github"
    assert c.get("/v1/sites/site:github/endpoints", params={"q": "pulls"}).json()["endpoints"]
    assert c.get("/v1/sites/site:github").json()["kind"] == "site"
    assert c.get("/v1/code-universe").json()["ecosystems"]
    r = c.post("/v1/site-graph", json={"urls": ["https://x.example/a/b", "https://x.example/a/c"]})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    r = c.post("/v1/activity", json={"events": [{"agent": "z", "url": "https://github.com/a/b"}]})
    assert r.json()["agents"][0]["id"] == "ag:z"


@needs_snapshot
def test_mcp_server_tools():
    pytest.importorskip("mcp")
    from internet_snapshot.mcp_server import build_server
    server = build_server(str(SNAPSHOTS_DIR))
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"search", "describe", "locate", "route", "site_graph", "list_endpoints", "code_universe",
            "activity_overlay", "visited_site_graph", "whereami"} <= names
