"""Route inference from a home AS to a destination: valley-free (Gao–Rexford) simulation.

See docs/DESIGN.md §7 and docs/snapshot-format.md §7.

This is BGPsim-style propagation from the destination. Customer routes flow upward first,
then they cross at most one peer hop, then provider routes flow down to customers. Each AS
picks a route by type (customer > peer > provider), then by length, then by lowest next-hop
ASN.
"""

from __future__ import annotations

import heapq
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

REGION_TIER1 = {
    "north-america": [3356, 174], "latin-america": [3356, 12956], "europe": [1299, 3320],
    "africa": [5511, 6453], "middle-east": [6453, 1299], "asia": [2914, 3491], "oceania": [2914, 3491],
}


class ASGraph:
    def __init__(self, nodes: dict[int, dict], rels: list[list[int]], tier1: list[int],
                 relationship_source: str = "unknown", hosting: dict | None = None,
                 org_networks: dict | None = None):
        self.nodes = nodes
        self.tier1 = tier1
        self.relationship_source = relationship_source
        self.hosting = hosting or {}
        self.org_networks = org_networks or {}
        self.providers: dict[int, set[int]] = defaultdict(set)
        self.customers: dict[int, set[int]] = defaultdict(set)
        self.peers: dict[int, set[int]] = defaultdict(set)
        for a, b, r in rels:
            if r == -1:
                self.customers[a].add(b)
                self.providers[b].add(a)
            else:
                self.peers[a].add(b)
                self.peers[b].add(a)
        self._routes = lru_cache(maxsize=512)(self._routes_to)

    @classmethod
    def load(cls, path: Path) -> "ASGraph":
        d = json.loads(Path(path).read_text())
        nodes = {int(k): v for k, v in d["nodes"].items()}
        return cls(nodes, d["rels"], d.get("tier1", []), d.get("relationship_source", "unknown"),
                   d.get("hosting"), d.get("org_networks"))

    # -- simulation --------------------------------------------------------------------------

    def _routes_to(self, dst: int, extra_providers: tuple[tuple[int, tuple[int, ...]], ...] = ()):
        providers = self.providers
        customers = self.customers
        if extra_providers:
            providers = defaultdict(set, {k: set(v) for k, v in self.providers.items()})
            customers = defaultdict(set, {k: set(v) for k, v in self.customers.items()})
            for asn, ups in extra_providers:
                for p in ups:
                    providers[asn].add(p)
                    customers[p].add(asn)
        best: dict[int, tuple[int, int, int | None]] = {dst: (0, 0, None)}  # type: 0 origin 1 cust 2 peer 3 prov
        frontier = [dst]
        while frontier:
            nxt = []
            for x in sorted(frontier):
                for p in sorted(providers.get(x, ())):
                    if p not in best:
                        best[p] = (1, best[x][1] + 1, x)
                        nxt.append(p)
            frontier = nxt
        cand = {}
        for x, (t, length, _) in list(best.items()):
            if t <= 1:
                for q in self.peers.get(x, ()):
                    if q not in best and (q not in cand or (length + 1, x) < (cand[q][1], cand[q][2])):
                        cand[q] = (2, length + 1, x)
        best.update(cand)
        heap = [(v[1], a) for a, v in best.items()]
        heapq.heapify(heap)
        while heap:
            length, a = heapq.heappop(heap)
            if best[a][1] != length:
                continue
            for c in sorted(customers.get(a, ())):
                cur = best.get(c)
                if cur is None or (cur[0] == 3 and (length + 1, a) < (cur[1], cur[2])):
                    best[c] = (3, length + 1, a)
                    heapq.heappush(heap, (length + 1, c))
        return best

    def as_path(self, src: int, dst: int, extra_providers: dict[int, list[int]] | None = None) -> list[int] | None:
        extra = tuple(sorted((k, tuple(sorted(v))) for k, v in (extra_providers or {}).items()))
        best = self._routes(dst, extra)
        if src not in best:
            return None
        path, cur, seen = [src], src, {src}
        while cur != dst:
            cur = best[cur][2]
            if cur is None or cur in seen:
                return None
            seen.add(cur)
            path.append(cur)
        return path

    def rel(self, a: int, b: int) -> str:
        if b in self.providers.get(a, ()):
            return "up"
        if b in self.peers.get(a, ()):
            return "peer"
        if b in self.customers.get(a, ()):
            return "down"
        return "sibling"

    def known(self, asn: int) -> bool:
        return asn in self.nodes and (asn in self.providers or asn in self.peers or asn in self.customers)

    def fallback_providers(self, region: str | None) -> list[int]:
        cands = REGION_TIER1.get(region or "", []) + list(self.tier1)
        return [a for a in dict.fromkeys(cands) if a in self.nodes][:2]

    def route(self, src: int, dst_candidates: list[int], src_region: str | None = None) -> dict:
        """Best route from src to any of the destination ASNs. Returns {as_path, method, confidence}."""
        base_conf = "medium" if self.relationship_source.startswith("caida") else "low"
        extra = None
        src_known = self.known(src)
        if not src_known:
            extra = {src: self.fallback_providers(src_region)}
        best_path = None
        for dst in dst_candidates:
            if dst == src:
                return {"as_path": [src], "method": "valley-free", "confidence": base_conf}
            p = self.as_path(src, dst, extra)
            if p and (best_path is None or len(p) < len(best_path)):
                best_path = p
        if best_path:
            return {"as_path": best_path, "method": "valley-free" if src_known else "fallback",
                    "confidence": base_conf if src_known else "low"}
        # no valley-free path: go up through a tier-1 to the first destination
        ups = self.fallback_providers(src_region)
        path = [src] + ups[:1] + ([dst_candidates[0]] if dst_candidates else [])
        return {"as_path": [a for a in dict.fromkeys(path)], "method": "fallback", "confidence": "low"}
