"""End-to-end build: seed + sources → catalogue → frozen layout → LOD files."""

from __future__ import annotations

import logging
import time

from ..seed import load_seed
from .catalog import BuildOptions, build_catalog
from .export import assign_lods, write_snapshot
from .layout import layout
from ..sources import SOURCES
from ..sources.parsers import load_simpleicons

log = logging.getLogger(__name__)


def run_build(resolve_dns: bool = False, use_caida: bool = False, crux_max_rank: int = 10_000,
              longtail_networks: int = 1500, iters: int = 160, sites: bool = True) -> str:
    t0 = time.time()
    seed = load_seed()
    errors = seed.validate()
    if errors:
        raise ValueError("seed catalogue is invalid:\n  " + "\n  ".join(errors))
    cat = build_catalog(seed, BuildOptions(crux_max_rank=crux_max_rank, longtail_networks=longtail_networks,
                                           resolve_dns=resolve_dns, use_caida=use_caida))
    print(f"catalogue: {len(cat.nodes)} nodes, {len(cat.edges)} edges ({time.time()-t0:.1f}s)")
    t1 = time.time()
    meta = layout(cat, seed.taxonomy, iters=iters)
    print(f"layout: {time.time()-t1:.1f}s")
    assign_lods(cat)
    site_bundle = None
    if sites:
        from ..sites import build_all_sites
        from .icons import available_glyphs
        t2 = time.time()
        icons = set(load_simpleicons(SOURCES["simpleicons"].path))
        graphs, ctx = build_all_sites(cat, seed.categories, available_glyphs() or None, icons)
        for g in graphs:
            if g.root_node in cat.nodes and g.kind == "site":
                cat.nodes[g.root_node]["portal"] = g.id
            for n in g.nodes.values():
                gid = n["meta"].get("global")
                if gid in cat.nodes and not cat.nodes[gid].get("portal"):
                    cat.nodes[gid]["portal"] = g.id
        site_bundle = (graphs, ctx)
        print(f"site graphs: {time.time()-t2:.1f}s")
    sid = write_snapshot(cat, seed.taxonomy, meta, sites=site_bundle)
    print(f"snapshot {sid} written ({time.time()-t0:.1f}s total)")
    return sid
