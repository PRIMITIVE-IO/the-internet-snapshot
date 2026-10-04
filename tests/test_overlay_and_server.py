import json
import math

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from internet_snapshot.config import SNAPSHOTS_DIR
from internet_snapshot.geo import angle_between, dir_from_azel, placement
from internet_snapshot.overlay import CONNECTORS
from internet_snapshot.overlay.base import ProviderAuthError
from internet_snapshot.overlay.placement import Asset, Group, place_overlay


def github_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == "Bearer good-token"
    path = request.url.path
    if path == "/user":
        return httpx.Response(200, json={"id": 42, "login": "octocat", "name": "Mona", "html_url": "https://github.com/octocat"})
    if path == "/user/repos":
        repos = [{"name": f"r{i}", "full_name": f"{'octocat' if i < 3 else 'acme'}/r{i}", "private": i == 1,
                  "stargazers_count": i * 10, "language": "Python", "html_url": "https://github.com/x",
                  "owner": {"login": "octocat" if i < 3 else "acme"}} for i in range(5)]
        return httpx.Response(200, json=repos)
    if path == "/user/orgs":
        return httpx.Response(200, json=[{"login": "acme"}, {"login": "emptyorg"}])
    return httpx.Response(404)


def google_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "userinfo" in url:
        return httpx.Response(200, json={"sub": "777", "email": "a@example.com", "name": "A"})
    if url.endswith("/labels"):
        return httpx.Response(200, json={"labels": [{"id": "INBOX", "name": "INBOX", "type": "system"},
                                                    {"id": "Label_1", "name": "Receipts", "type": "user"},
                                                    {"id": "CHAT", "name": "CHAT", "type": "system"}]})
    if "/labels/" in url:
        lid = url.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"id": lid, "name": "INBOX" if lid == "INBOX" else "Receipts",
                                         "type": "system" if lid == "INBOX" else "user", "messagesTotal": 120})
    if "drive/v3/files" in url:
        return httpx.Response(200, json={"files": [
            {"id": "f1", "name": "Projects", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "f2", "name": "notes.txt", "mimeType": "text/plain"}]})
    if "calendarList" in url:
        return httpx.Response(403, json={"error": "insufficient scope"})
    return httpx.Response(404)


@pytest.mark.anyio
async def test_github_connector_groups_by_owner():
    async with httpx.AsyncClient(transport=httpx.MockTransport(github_handler)) as c:
        acct = await CONNECTORS["github"].fetch(c, "good-token", 60)
    assert acct.id == "ov:github:42" and acct.label == "octocat"
    labels = [g.label for g in acct.groups]
    assert labels[0] == "Your repositories" and "acme" in labels and "emptyorg" in labels
    assert len(acct.groups[0].assets) == 3


@pytest.mark.anyio
async def test_github_connector_rejects_bad_token():
    transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "Bad credentials"}))
    async with httpx.AsyncClient(transport=transport) as c:
        with pytest.raises(ProviderAuthError):
            await CONNECTORS["github"].fetch(c, "nope", 10)


@pytest.mark.anyio
async def test_google_connector_products_and_warnings():
    async with httpx.AsyncClient(transport=httpx.MockTransport(google_handler)) as c:
        acct = await CONNECTORS["google"].fetch(c, "t", 60)
    keys = {g.key: g for g in acct.groups}
    assert set(keys) == {"gmail", "drive"}
    assert keys["gmail"].product_anchor == "svc:gmail.com"
    assert [a.label for a in keys["gmail"].assets] == ["Inbox", "Receipts"]   # CHAT filtered out
    assert any("calendar" in w for w in acct.warnings)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_placement_spec():
    anchor = placement(dir_from_azel(30, 10), 1000)["pos"]
    gmail = placement(dir_from_azel(36, 12), 985)["pos"]
    groups = [Group("gmail", "Gmail", [Asset(f"a{i}", f"a{i}") for i in range(10)], product_anchor="svc:gmail.com"),
              Group("other", "Other", [Asset("b", "b")])]
    nodes, edges = place_overlay(provider="google", account_id="ov:google:1", account_label="x", account_meta={},
                                 anchor_id="org:google", anchor_pos=anchor, groups=groups,
                                 node_pos={"svc:gmail.com": gmail}, account_index=1, account_count=3)
    by = {n["id"]: n for n in nodes}
    acc = by["ov:google:1"]
    assert acc["r"] == pytest.approx(975)
    assert angle_between(acc["pos"], anchor) == pytest.approx(1.2, abs=0.02)
    g = by["ov:google:1:group:gmail"]
    assert angle_between(g["pos"], gmail) == pytest.approx(0.8, abs=0.02)
    assert g["r"] == pytest.approx(960)
    for n in nodes:
        if n["kind"] == "asset" and n["parent"] == g["id"]:
            assert angle_between(n["pos"], g["pos"]) <= 0.5 + 1e-6
            assert n["r"] == pytest.approx(957)
    assert {e["kind"] for e in edges} == {"attached", "contains"}
    # deterministic
    again, _ = place_overlay(provider="google", account_id="ov:google:1", account_label="x", account_meta={},
                             anchor_id="org:google", anchor_pos=anchor, groups=groups,
                             node_pos={"svc:gmail.com": gmail}, account_index=1, account_count=3)
    assert again == nodes


needs_snapshot = pytest.mark.skipif(not (SNAPSHOTS_DIR / "latest.json").exists(), reason="no published snapshot")


@pytest.fixture(scope="module")
def client():
    from internet_snapshot.server.app import app
    return TestClient(app)


@needs_snapshot
def test_server_basics(client):
    h = client.get("/healthz").json()
    assert h["ok"]
    latest = client.get("/v1/snapshots/latest.json").json()
    assert latest["snapshot_id"] == h["snapshot_id"]
    r = client.get(f"/v1/snapshots/{latest['manifest']}")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    assert client.get("/v1/snapshots/%2E%2E/README.md").status_code == 404
    assert client.get(f"/v1/snapshots/{latest['snapshot_id']}/%2E%2E/%2E%2E/README.md").status_code == 404
    assert client.get("/v1/search", params={"q": "github"}).json()[0]["id"] == "svc:github.com"
    node = client.get("/v1/node/org:google").json()
    assert node["node"]["label"] == "Google" and node["children"]


@needs_snapshot
def test_route_from_known_and_unknown_home(client):
    r = client.get("/v1/route", params={"to": "https://mail.google.com/mail", "asn": 7922}).json()
    assert r["to"]["node"] == "svc:gmail.com"
    assert r["hops"][0]["node"] == "home" and r["hops"][1]["node"] == "as:7922"
    assert r["hops"][-1]["node"] == "svc:gmail.com" and r["hops"][-1]["rel"] == "served"
    assert r["method"] in ("valley-free", "observed", "fallback")
    r2 = client.get("/v1/route", params={"to": "github.com", "asn": 64512}).json()
    assert r2["from"]["in_snapshot"] is False and r2["method"] == "fallback"
    assert client.get("/v1/route", params={"to": "cat:email", "asn": 7922}).status_code == 400
    assert client.get("/v1/route", params={"to": "no-such-domain.invalid", "asn": 7922}).status_code == 404


@needs_snapshot
def test_overlay_proxy(client, monkeypatch):
    import internet_snapshot.server.app as appmod

    real = httpx.AsyncClient
    monkeypatch.setattr(appmod.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(github_handler), **kw))
    assert client.post("/v1/overlay/github").status_code == 401
    assert client.post("/v1/overlay/nope", headers={"Authorization": "Bearer x"}).status_code == 404
    r = client.post("/v1/overlay/github", headers={"Authorization": "Bearer good-token"},
                    json={"account_index": 0, "account_count": 2})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    doc = r.json()
    assert doc["account"]["id"] == "ov:github:42"
    assert all(n["id"].startswith("ov:") for n in doc["nodes"])
    assert doc["edges"][0]["target"] == "svc:github.com"
    specs = client.get("/v1/connectors").json()
    assert {s["provider"] for s in specs} >= {"github", "google"}
