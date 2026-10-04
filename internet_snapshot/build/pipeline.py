"""End-to-end build: seed + sources → catalogue → frozen layout → LOD files."""

from __future__ import annotations

import logging
import time

from ..seed import load_seed
from .catalog import BuildOptions, build_catalog
from .export import assign_lods, write_snapshot
from .layout import layout

log = logging.getLogger(__name__)


def run_build(resolve_dns: bool = False, use_caida: bool = False, crux_max_rank: int = 10_000,
              longtail_networks: int = 1500, iters: int = 160) -> str:
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
    sid = write_snapshot(cat, seed.taxonomy, meta)
    print(f"snapshot {sid} written ({time.time()-t0:.1f}s total)")
    return sid
