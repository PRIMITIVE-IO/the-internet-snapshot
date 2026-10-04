"""URL → place in the map (docs/snapshot-format.md §13), and the agent activity overlay (§14)."""

from __future__ import annotations

import colorsys
import hashlib
from collections import Counter
from typing import Callable
from urllib.parse import urlparse

from .sites.model import host_matches


def _segments(path: str | None) -> list[str]:
    return [s for s in (path or "").split("/") if s]


def path_score(template: str, path: str) -> tuple[int, int, int] | None:
    """(exact, literal segments, template length) if the template matches the path (or a prefix of it)."""
    t, u = _segments(template), _segments(path)
    if len(t) > len(u):
        return None
    literal = 0
    for a, b in zip(t, u):
        if a.startswith("{") and a.endswith("}"):
            continue
        if a.lower() != b.lower():
            return None
        literal += 1
    return (1 if len(t) == len(u) else 0, literal, len(t))


class Locator:
    def __init__(self, nodes: dict[str, dict], by_domain: dict[str, str], site_index: list[dict],
                 load_site: Callable[[str], dict]):
        self.nodes = nodes
        self.by_domain = by_domain
        self.site_index = {s["id"]: s for s in site_index}
        self.load_site = load_site
        self._sites: dict[str, dict] = {}
        self._host_sites: dict[str, list[str]] = {}
        for s in site_index:
            for h in s.get("hosts", []):
                self._host_sites.setdefault(h, []).append(s["id"])

    def site(self, site_id: str) -> dict | None:
        if site_id not in self.site_index:
            return None
        if site_id not in self._sites:
            doc = self.load_site(self.site_index[site_id]["file"])
            doc["_by_id"] = {n["id"]: n for n in doc["nodes"]}
            self._sites[site_id] = doc
        return self._sites[site_id]

    def global_node(self, host: str) -> dict | None:
        labels = host.split(".")
        for i in range(len(labels) - 1):
            nid = self.by_domain.get(".".join(labels[i:]))
            if nid and nid in self.nodes:
                return self.nodes[nid]
        return None

    def _site_for(self, gnode: dict | None, host: str) -> str | None:
        if gnode:
            if gnode.get("portal") and gnode["portal"] in self.site_index:
                return gnode["portal"]
            org = self.nodes.get(gnode.get("org") or "")
            if org and org.get("portal") in self.site_index:
                return org["portal"]
        labels = host.split(".")
        for i in range(len(labels) - 1):
            cand = self._host_sites.get(".".join(labels[i:]))
            if cand:
                return next((c for c in cand if not c.endswith("code-universe")), cand[0])
        return None

    def match_in_site(self, doc: dict, host: str, path: str, method: str | None) -> tuple[dict | None, str]:
        cands = [n for n in doc["nodes"] if n.get("host") and host_matches(n["host"], host)]
        best, best_score = None, None
        for n in cands:
            if not n.get("path"):
                continue
            sc = path_score(n["path"], path)
            if sc is None:
                continue
            m = 1 if (method and n.get("method") == method.upper()) else (0 if not n.get("method") else -1)
            score = (sc[0], sc[1], sc[2], m)
            if best_score is None or score > best_score:
                best, best_score = n, score
        if best is not None:
            kind = "operation" if (best_score[0] and best.get("method") and best_score[3] >= 0) else "path"
            return best, kind
        hosted = [n for n in cands if not n.get("path")]
        if hosted:
            exact = [n for n in hosted if n["host"] == host] or hosted
            return min(exact, key=lambda n: (n["depth"], n["id"])), "host"
        return None, "domain"

    def locate(self, url: str, method: str | None = None) -> dict:
        if "://" not in url:
            url = "https://" + url
        u = urlparse(url)
        host = (u.hostname or "").lower()
        path = u.path or "/"
        gnode = self.global_node(host)
        out = {"url": url, "host": host, "global": None, "site": None, "operation": None, "match": "none"}
        if gnode:
            out["global"] = {"node": gnode["id"], "label": gnode["label"], "kind": gnode["kind"], "pos": gnode["pos"]}
            out["match"] = "domain"
        site_id = self._site_for(gnode, host)
        doc = self.site(site_id) if site_id else None
        if doc:
            node, kind = self.match_in_site(doc, host, path, method)
            if node is None and kind == "domain":
                node = doc["_by_id"][doc["id"]]
            chain, cur = [], node
            while cur is not None:
                chain.append(cur["id"])
                cur = doc["_by_id"].get(cur["parent"]) if cur.get("parent") else None
            out["site"] = {"id": doc["id"], "node": node["id"], "label": node["label"], "path": list(reversed(chain)),
                           "pos": node["pos"]}
            out["match"] = kind
            if kind == "operation":
                out["operation"] = {"method": node.get("method"), "path": node.get("path"), "doc_url": node.get("url"),
                                    "label": node["label"]}
            if host == "github.com" and "site:code-universe" in self.site_index:
                cu = self.site("site:code-universe")
                repo, rk = self.match_in_site(cu, host, path, method)
                if repo is not None and rk in ("path", "operation") and repo["kind"] in ("repo", "owner"):
                    out["also"] = {"id": cu["id"], "node": repo["id"], "label": repo["label"], "pos": repo["pos"]}
        return out


def agent_color(agent: str) -> str:
    h = int(hashlib.blake2b(agent.encode(), digest_size=4).hexdigest(), 16) % 360
    r, g, b = colorsys.hls_to_rgb(h / 360, 0.6, 0.85)
    return "#{:02X}{:02X}{:02X}".format(int(r * 255), int(g * 255), int(b * 255))


def activity_overlay(events: list[dict], locator: Locator, snapshot_id: str) -> dict:
    """Build the agent-activity overlay document (snapshot-format.md §14) from ActivityEvents."""
    agents: dict[str, dict] = {}
    heat: Counter = Counter()
    for ev in sorted(events, key=lambda e: (e.get("ts") or "")):
        agent = str(ev.get("agent") or "agent")
        url = ev.get("url")
        if not url:
            continue
        loc = locator.locate(url, ev.get("method"))
        a = agents.setdefault(agent, {"id": f"ag:{agent}", "label": agent, "color": agent_color(agent),
                                      "at": None, "at_site": None, "trail": []})
        if loc["global"]:
            step = {"ts": ev.get("ts"), "space": "global", "node": loc["global"]["node"], "pos": loc["global"]["pos"],
                    "match": loc["match"], "kind": ev.get("kind"), "method": ev.get("method"), "status": ev.get("status")}
            a["trail"].append(step)
            a["at"] = {"space": "global", "node": step["node"], "pos": step["pos"]}
            heat[("global", step["node"])] += 1
        if loc["site"]:
            a["at_site"] = {"space": loc["site"]["id"], "node": loc["site"]["node"], "pos": loc["site"]["pos"]}
            for nid in loc["site"]["path"][1:]:
                heat[(loc["site"]["id"], nid)] += 1
    return {"overlay_version": "0.2", "kind": "agent-activity", "snapshot_id": snapshot_id,
            "agents": list(agents.values()),
            "heat": [{"space": s, "node": n, "count": c} for (s, n), c in heat.most_common()]}
