"""Site graph data model (docs/snapshot-format.md §11)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fnmatch import fnmatch

SITE_NODE_KEYS = ("id", "kind", "label", "parent", "depth", "r", "az", "el", "pos", "size", "color", "icon", "glyph",
                  "url", "host", "path", "method", "portal", "meta")


def host_matches(pattern: str, host: str) -> bool:
    pattern, host = pattern.lower(), host.lower()
    if pattern == host:
        return True
    if pattern.startswith("*."):
        return host.endswith(pattern[1:]) or host == pattern[2:]
    if "*" in pattern:
        return fnmatch(host, pattern)
    return False


@dataclass
class SiteGraph:
    id: str
    kind: str          # site | code
    label: str
    root_node: str | None
    icon: str | None = None
    nodes: dict[str, dict] = field(default_factory=dict)
    edges: list[dict] = field(default_factory=list)
    sources: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self):
        root = {k: None for k in SITE_NODE_KEYS}
        root.update(id=self.id, kind="universe" if self.kind == "code" else "site", label=self.label, depth=0,
                    icon=self.icon, glyph="orbit", meta={"root_node": self.root_node}, _w=1.0)
        self.nodes[self.id] = root

    @property
    def root(self) -> dict:
        return self.nodes[self.id]

    def add(self, parent: str, key: str, kind: str, label: str, weight: float = 0.5, **kw) -> dict:
        p = self.nodes[parent]
        nid = f"{parent}/{key}"
        if nid in self.nodes:
            return self.nodes[nid]
        n = {k: None for k in SITE_NODE_KEYS}
        n.update(id=nid, kind=kind, label=label, parent=parent, depth=p["depth"] + 1, meta={}, _w=weight)
        for k, v in kw.items():
            if k == "meta":
                n["meta"].update(v or {})
            else:
                n[k] = v
        self.nodes[nid] = n
        return n

    def edge(self, source: str, target: str, kind: str, weight: float = 0.4) -> None:
        self.edges.append({"source": source, "target": target, "kind": kind, "weight": weight})

    def children(self) -> dict[str, list[str]]:
        ch: dict[str, list[str]] = {}
        for n in self.nodes.values():
            if n["parent"]:
                ch.setdefault(n["parent"], []).append(n["id"])
        return ch

    def max_depth(self) -> int:
        return max(n["depth"] for n in self.nodes.values())

    def prune_empty(self, keep_kinds=("operation", "host", "repo", "api", "section", "product", "owner")) -> None:
        """Drop structural nodes that ended up with no children and no own content."""
        changed = True
        while changed:
            changed = False
            ch = self.children()
            for nid, n in list(self.nodes.items()):
                if nid == self.id or nid in ch:
                    continue
                if n["kind"] in keep_kinds or n.get("host") or n.get("portal") or n["meta"].get("global"):
                    continue
                del self.nodes[nid]
                changed = True

    def compute_sizes(self) -> None:
        """size = blend of the node's own weight and its (log) subtree weight, normalised per graph."""
        ch = self.children()
        sub: dict[str, float] = {}

        def total(nid: str) -> float:
            if nid in sub:
                return sub[nid]
            t = self.nodes[nid]["_w"] + 0.6 * sum(total(c) for c in ch.get(nid, []))
            sub[nid] = t
            return t

        total(self.id)
        mx = max(sub.values()) or 1.0
        for nid, n in self.nodes.items():
            s = 0.55 * min(1.0, n["_w"]) + 0.45 * math.log1p(sub[nid]) / math.log1p(mx)
            n["size"] = round(min(1.0, max(0.05, s)), 3)
            n["_sub"] = sub[nid]
        self.root["size"] = 1.0

    def stats(self) -> dict:
        return {"nodes": len(self.nodes), "edges": len(self.edges), "max_depth": self.max_depth()}
