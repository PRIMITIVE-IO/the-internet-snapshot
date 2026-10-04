"""On-demand site graphs built from the URLs a user or agent actually visited (docs/DESIGN.md §12.4).

The hierarchy is host → path segments. Segments that look like identifiers are collapsed to
"{id}". The graph is laid out with the same radial-sector layout as precomputed graphs. It is
stateless: nothing is stored.
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

from ..glyphs import glyph_for_text
from .layout import layout_site
from .model import SITE_NODE_KEYS, SiteGraph

_ID_LIKE = re.compile(r"^(\d+|[0-9a-f]{8,}|[0-9a-f-]{20,}|[A-Za-z0-9_-]{24,})$", re.I)


def _norm_segment(seg: str) -> str:
    return "{id}" if _ID_LIKE.match(seg) else seg


def graph_from_urls(urls: list[str], label: str | None = None, max_depth: int = 4, max_nodes: int = 1500) -> dict:
    parsed = []
    for u in urls:
        if "://" not in u:
            u = "https://" + u
        p = urlparse(u)
        if p.hostname:
            parsed.append((p.hostname.lower(), [_norm_segment(s) for s in p.path.split("/") if s][: max_depth - 1]))
    if not parsed:
        raise ValueError("no valid URLs")
    hosts = Counter(h for h, _ in parsed)
    root_label = label or hosts.most_common(1)[0][0]
    g = SiteGraph(id=f"site:visited:{root_label}", kind="site", label=root_label, root_node=None)
    hits: Counter = Counter()
    for host, segs in parsed:
        parent = g.add(g.id, host, "host", host, weight=0.6, host=host, url=f"https://{host}",
                       glyph=glyph_for_text(host.split(".")[0], default="globe"))
        hits[parent["id"]] += 1
        path = ""
        for seg in segs:
            if len(g.nodes) >= max_nodes:
                break
            path += "/" + seg
            node = g.add(parent["id"], seg.replace("/", "_"), "section", seg, weight=0.3, host=host, path=path,
                         url=None if "{" in path else f"https://{host}{path}",
                         glyph=glyph_for_text(seg, default="file"))
            hits[node["id"]] += 1
            parent = node
    mx = max(hits.values())
    for nid, c in hits.items():
        g.nodes[nid]["_w"] = 0.2 + 0.8 * c / mx
        g.nodes[nid]["meta"]["visits"] = c
    g.compute_sizes()
    layout_site(g)
    pos = {n["id"]: n["pos"] for n in g.nodes.values()}
    nodes = [{k: n.get(k) for k in SITE_NODE_KEYS} for n in sorted(g.nodes.values(), key=lambda n: (n["depth"], n["id"]))]
    return {"graph_version": "0.2", "id": g.id, "kind": "site", "label": g.label, "root_node": None,
            "radius": 1000.0, "max_depth": g.max_depth(), "shells": g.shells, "nodes": nodes,
            "edges": [{**e, "a": pos[e["source"]], "b": pos[e["target"]]} for e in g.edges]}
