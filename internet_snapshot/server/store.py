"""In-memory index over the latest published snapshot, reloaded when ``latest.json`` changes."""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from pathlib import Path

from ..config import SNAPSHOTS_DIR
from ..routing import ASGraph

log = logging.getLogger(__name__)


class Snapshot:
    def __init__(self, root: Path, snapshot_id: str):
        self.id = snapshot_id
        self.dir = root / snapshot_id
        self.manifest = json.loads((self.dir / "manifest.json").read_text())
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        files = [self.dir / lm["file"] for lm in self.manifest["lods"] if "file" in lm]
        for lm in self.manifest["lods"]:
            if "tiling" in lm:
                files += [self.dir / lm["tiling"]["path"].format(order=lm["tiling"]["order"], ipix=t["ipix"])
                          for t in lm["tiles"]]
        for f in files:
            doc = json.loads(f.read_text())
            for n in doc["nodes"]:
                self.nodes[n["id"]] = n
            self.edges.extend(doc["edges"])
        self.edges_by_node: dict[str, list[dict]] = defaultdict(list)
        for e in self.edges:
            self.edges_by_node[e["source"]].append(e)
            self.edges_by_node[e["target"]].append(e)
        self.children: dict[str, list[str]] = defaultdict(list)
        for n in self.nodes.values():
            if n.get("parent"):
                self.children[n["parent"]].append(n["id"])
        self.by_domain = {n["domain"]: n["id"] for n in self.nodes.values() if n.get("domain")}
        dom_file = self.manifest["files"].get("domains")
        if dom_file and (self.dir / dom_file).exists():
            self.by_domain.update(json.loads((self.dir / dom_file).read_text()))
        self.anchors = json.loads((self.dir / self.manifest["files"]["anchors"]).read_text())
        self.asgraph = ASGraph.load(self.dir / self.manifest["files"]["asgraph"])

    def find_node(self, query: str) -> dict | None:
        """Resolve a node id, a domain, a hostname or a URL to a node."""
        q = query.strip()
        if q in self.nodes:
            return self.nodes[q]
        host = q.lower().split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].strip(".")
        if f"as:{host.removeprefix('as')}" in self.nodes and host.removeprefix("as").isdigit():
            return self.nodes[f"as:{host.removeprefix('as')}"]
        labels = host.split(".")
        for i in range(len(labels) - 1):
            cand = ".".join(labels[i:])
            nid = self.by_domain.get(cand)
            if nid:
                return self.nodes[nid]
        return None

    def search(self, q: str, limit: int = 20) -> list[dict]:
        q = q.strip().lower()
        if not q:
            return []
        scored = []
        for n in self.nodes.values():
            label = (n.get("label") or "").lower()
            dom = (n.get("domain") or "").lower()
            if q == label or q == dom:
                s = 0
            elif label.startswith(q) or dom.startswith(q):
                s = 1
            elif q in label or q in dom or q in n["id"]:
                s = 2
            else:
                continue
            scored.append((s, n["lod"], -(n.get("size") or 0), n["id"]))
        scored.sort()
        return [self.nodes[t[3]] for t in scored[:limit]]


class SnapshotStore:
    def __init__(self, root: Path = SNAPSHOTS_DIR):
        self.root = root
        self._lock = threading.Lock()
        self._snap: Snapshot | None = None
        self._latest_mtime = None

    @property
    def latest_path(self) -> Path:
        return self.root / "latest.json"

    def current(self) -> Snapshot:
        mtime = self.latest_path.stat().st_mtime
        if self._snap is None or mtime != self._latest_mtime:
            with self._lock:
                if self._snap is None or mtime != self._latest_mtime:
                    latest = json.loads(self.latest_path.read_text())
                    self._snap = Snapshot(self.root, latest["snapshot_id"])
                    self._latest_mtime = mtime
                    log.info("loaded snapshot %s (%d nodes)", self._snap.id, len(self._snap.nodes))
        return self._snap
