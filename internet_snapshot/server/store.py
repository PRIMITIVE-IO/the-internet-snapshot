"""In-memory index over a published snapshot.

The snapshot is read from local files or from any static base URL, such as GitHub Pages. The
API server and the MCP server share this class.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from pathlib import Path
from typing import Callable

from ..config import SNAPSHOTS_DIR
from ..locate import Locator
from ..routing import ASGraph

log = logging.getLogger(__name__)

Reader = Callable[[str], bytes]   # path relative to the snapshots/ directory -> bytes


def local_reader(root: Path) -> Reader:
    def read(rel: str) -> bytes:
        return (root / rel).read_bytes()
    return read


def http_reader(base_url: str) -> Reader:
    import httpx
    base = base_url.rstrip("/") + "/snapshots/"
    client = httpx.Client(timeout=60.0, follow_redirects=True,
                          headers={"User-Agent": "the-internet-snapshot-client/0.2"})

    def read(rel: str) -> bytes:
        r = client.get(base + rel)
        r.raise_for_status()
        return r.content
    return read


class Snapshot:
    def __init__(self, read: Reader, snapshot_id: str):
        self.id = snapshot_id
        self._read = read
        self.manifest = self.json("manifest.json")
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        rels = [lm["file"] for lm in self.manifest["lods"] if "file" in lm]
        for lm in self.manifest["lods"]:
            if "tiling" in lm:
                rels += [lm["tiling"]["path"].format(order=lm["tiling"]["order"], ipix=t["ipix"]) for t in lm["tiles"]]
        for rel in rels:
            doc = self.json(rel)
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
        files = self.manifest["files"]
        self.by_domain = {n["domain"]: n["id"] for n in self.nodes.values() if n.get("domain")}
        if files.get("domains"):
            self.by_domain.update(self.json(files["domains"]))
        self.anchors = self.json(files["anchors"])
        self.asgraph = ASGraph.load_dict(self.json(files["asgraph"]))
        self.sites_index = self.json(files["sites"])["sites"] if files.get("sites") else []
        self.locator = Locator(self.nodes, self.by_domain, self.sites_index, self.json)

    def json(self, rel: str):
        return json.loads(self._read(f"{self.id}/{rel}"))

    def site(self, site_id: str) -> dict | None:
        doc = self.locator.site(site_id)
        return {k: v for k, v in doc.items() if not k.startswith("_")} if doc else None

    def find_node(self, query: str) -> dict | None:
        """Resolve a node id, a domain, a hostname or a URL to a node."""
        q = query.strip()
        if q in self.nodes:
            return self.nodes[q]
        host = q.lower().split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].strip(".")
        if host.startswith("as") and host[2:].isdigit() and f"as:{host[2:]}" in self.nodes:
            return self.nodes[f"as:{host[2:]}"]
        labels = host.split(".")
        for i in range(len(labels) - 1):
            nid = self.by_domain.get(".".join(labels[i:]))
            if nid and nid in self.nodes:
                return self.nodes[nid]
        return None

    def search(self, q: str, limit: int = 20, kinds: set[str] | None = None) -> list[dict]:
        q = q.strip().lower()
        if not q:
            return []
        scored = []
        for n in self.nodes.values():
            if kinds and n["kind"] not in kinds:
                continue
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
    """The latest snapshot, from a local directory or a base URL. Reloads when latest.json changes."""

    def __init__(self, root: Path | str = SNAPSHOTS_DIR, refresh_seconds: float = 300.0):
        self.root = root
        self.remote = isinstance(root, str) and root.startswith(("http://", "https://"))
        self._read = http_reader(root) if self.remote else local_reader(Path(root))
        self._lock = threading.Lock()
        self._snap: Snapshot | None = None
        self._stamp = None
        self._checked = 0.0
        self.refresh_seconds = refresh_seconds

    @property
    def latest_path(self) -> Path:
        return Path(self.root) / "latest.json"

    def _latest(self) -> dict:
        return json.loads(self._read("latest.json"))

    def current(self) -> Snapshot:
        import time
        now = time.time()
        if self._snap is not None and self.remote and now - self._checked < self.refresh_seconds:
            return self._snap
        stamp = self.latest_path.stat().st_mtime if not self.remote else None
        if self._snap is None or (not self.remote and stamp != self._stamp) or self.remote:
            with self._lock:
                latest = self._latest()
                self._checked = now
                if self._snap is None or latest["snapshot_id"] != self._snap.id:
                    self._snap = Snapshot(self._read, latest["snapshot_id"])
                    log.info("loaded snapshot %s (%d nodes)", self._snap.id, len(self._snap.nodes))
                self._stamp = stamp
        return self._snap
