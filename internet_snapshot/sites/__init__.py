"""Site graphs ("microcosms") and the GitHub code universe. See docs/DESIGN.md §12–13."""

from __future__ import annotations

import json

from ..build.catalog import Catalog
from ..glyphs import FALLBACK
from .builders import (SiteContext, build_code_universe, build_curated, build_org_auto, build_service_auto,
                       load_context, load_curated_specs)
from .layout import layout_site
from .model import SITE_NODE_KEYS, SiteGraph, host_matches

__all__ = ["SiteGraph", "build_all_sites", "site_documents", "SITE_NODE_KEYS", "host_matches"]


def build_all_sites(cat: Catalog, categories: dict, valid_glyphs: set[str] | None = None,
                    valid_icons: set[str] | None = None, log=print) -> tuple[list[SiteGraph], SiteContext]:
    ctx = load_context(cat, categories)
    graphs: list[SiteGraph] = []
    covered_roots: set[str] = set()
    for spec in load_curated_specs():
        g = build_curated(spec, ctx)
        graphs.append(g)
        covered_roots.add(spec["root_node"])
        for n in g.nodes.values():
            if n["meta"].get("global"):
                covered_roots.add(n["meta"]["global"])
    for org in sorted(cat.of_kind("org"), key=lambda o: o["id"]):
        if org["id"] in covered_roots:
            continue
        g = build_org_auto(org, ctx)
        if g:
            graphs.append(g)
            covered_roots.add(org["id"])
            covered_roots.update(org.get("_services", []))
    for svc in sorted(cat.of_kind("service"), key=lambda s: (s["rank"] or 10**7, s["id"])):
        if svc["id"] in covered_roots or svc.get("org") in covered_roots:
            continue
        g = build_service_auto(svc, ctx)
        if g:
            graphs.append(g)
    cu = build_code_universe(ctx)
    if cu:
        graphs.append(cu)
    for g in graphs:
        for n in g.nodes.values():
            if valid_glyphs is not None and n.get("glyph") and n["glyph"] not in valid_glyphs:
                n["glyph"] = FALLBACK
            if valid_icons is not None and n.get("icon") and n["icon"] not in valid_icons:
                n["icon"] = None
        g.prune_empty()
        g.compute_sizes()
        layout_site(g)
    log(f"site graphs: {len(graphs)} ({sum(len(g.nodes) for g in graphs)} nodes)")
    return graphs, ctx


def site_slug(site_id: str) -> str:
    return site_id.split(":", 1)[1].replace("/", "_")


def site_documents(graphs: list[SiteGraph], snapshot_id: str, ctx: SiteContext) -> tuple[dict[str, bytes], dict]:
    """Serialise graphs to sites/<slug>.json files plus sites/index.json."""
    files: dict[str, bytes] = {}
    index = []
    for g in graphs:
        nodes = []
        pos = {}
        for n in sorted(g.nodes.values(), key=lambda n: (n["depth"], n["id"])):
            out = {k: n.get(k) for k in SITE_NODE_KEYS}
            nodes.append(out)
            pos[n["id"]] = n["pos"]
        edges = [{**e, "a": pos[e["source"]], "b": pos[e["target"]]} for e in g.edges
                 if e["source"] in pos and e["target"] in pos]
        used = {sid: ctx.sources_used[sid] for sid in ctx.sources_used}
        doc = {"graph_version": "0.2", "snapshot_id": snapshot_id, "id": g.id, "kind": g.kind, "label": g.label,
               "root_node": g.root_node, "radius": 1000.0, "max_depth": g.max_depth(), "shells": g.shells,
               "nodes": nodes, "edges": edges,
               "sources": [{k: v for k, v in s.items() if k != "attribution"} for s in used.values()],
               "attribution": "; ".join(s["attribution"] for s in used.values())}
        name = f"sites/{site_slug(g.id)}.json"
        data = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode()
        files[name] = data
        hosts = sorted({n["host"].lstrip("*.") for n in g.nodes.values() if n.get("host")})
        index.append({"id": g.id, "kind": g.kind, "label": g.label, "root_node": g.root_node, "file": name,
                      "nodes": len(nodes), "edges": len(edges), "bytes": len(data), "max_depth": g.max_depth(),
                      "icon": g.icon, "hosts": hosts[:200]})
    return files, {"snapshot_id": snapshot_id, "sites": index}
