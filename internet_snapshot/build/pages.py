"""Assemble the GitHub Pages site in public/ (docs/DESIGN.md §9, snapshot-format.md §10, §12, §15).

The Pages-only artefacts are regenerated every build and deployed by Actions; they are not
committed to git:

- icons/   atlases and SVGs for every glyph and brand used by the latest snapshot
- ip2asn/  sharded public-domain prefix→AS table, for server-less home-network lookup
- agent.json, llms.txt   discovery files for AI agents
- index.html, .nojekyll  the reference viewer as the site's landing page
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from collections import defaultdict
from pathlib import Path

from ..config import PUBLIC_DIR, ROOT, SNAPSHOTS_DIR
from ..sources import SOURCES
from ..sources import parsers as P
from .icons import build_icons

# GitHub Pages URL. The PRIMITIVE-IO organisation serves Pages from a custom domain; the workflow passes the
# URL that actions/configure-pages reports (--site-url), so this is only the fallback.
PAGES_BASE = "http://documentation.primitive.io/the-internet-snapshot"
REPO = "https://github.com/PRIMITIVE-IO/the-internet-snapshot"


def _latest() -> tuple[str, Path, dict]:
    latest = json.loads((SNAPSHOTS_DIR / "latest.json").read_text())
    sdir = SNAPSHOTS_DIR / latest["snapshot_id"]
    return latest["snapshot_id"], sdir, json.loads((sdir / "manifest.json").read_text())


def _used_icons(sdir: Path, manifest: dict) -> tuple[set[str], set[str]]:
    glyphs, brands = set(), set()
    files = [sdir / lm["file"] for lm in manifest["lods"] if "file" in lm]
    files += sorted((sdir / "lod3").glob("*.json"))
    files += sorted((sdir / "sites").glob("*.json"))
    for f in files:
        doc = json.loads(f.read_text())
        for n in doc.get("nodes", []):
            if n.get("glyph"):
                glyphs.add(n["glyph"])
            if n.get("icon"):
                brands.add(n["icon"])
    return glyphs, brands


def build_ip2asn(out: Path) -> int:
    table = P.OriginAsnTable.load(SOURCES["originasn"].path)
    shards: dict[int, list] = defaultdict(list)
    for s, e, a in zip(table.starts.tolist(), table.ends.tolist(), table.asns.tolist()):
        for octet in range(s >> 24, (e >> 24) + 1):
            lo, hi = max(s, octet << 24), min(e, (octet << 24) | 0xFFFFFF)
            shards[octet].append([lo, hi, a])
    out.mkdir(parents=True, exist_ok=True)
    for octet, ranges in shards.items():
        ranges.sort()
        (out / f"{octet}.json").write_text(json.dumps({"ranges": ranges}, separators=(",", ":")))
    (out / "index.json").write_text(json.dumps({
        "source": "sapics/ip-location-db origin-asn", "license": "PDDL-1.0",
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "shards": len(shards), "format": "ranges: [[start_uint32, end_uint32, asn], ...] sorted by start"}))
    return len(shards)


def agent_descriptor(manifest: dict, api_base: str | None, base: str = PAGES_BASE) -> dict:
    return {
        "name": "the-internet-snapshot",
        "description": ("A frozen, hierarchical 3D map of the internet built from public datasets: services grouped "
                        "by function, the networks that carry them, per-site endpoint graphs and the GitHub code "
                        "universe. Use it to search the internet's structure, locate URLs, enumerate a service's API "
                        "endpoints and estimate network routes."),
        "data": {"base": base, "latest": "snapshots/latest.json",
                 "snapshot_id": manifest["snapshot_id"],
                 "contract": f"{REPO}/blob/main/docs/snapshot-format.md",
                 "icons": "icons/index.json", "ip2asn": "ip2asn/v4/index.json"},
        "api": {"base": api_base},
        "mcp": {"command": "python", "args": ["-m", "internet_snapshot", "mcp"],
                "install": f"pip install 'internet-snapshot[mcp] @ git+{REPO}'",
                "env": {"SNAPSHOT_BASE_URL": base}},
        "tools": ["search", "describe", "locate", "route", "site_graph", "list_endpoints", "code_universe",
                  "whereami", "activity_overlay"],
        "attribution": manifest.get("attribution"),
    }


LLMS_TXT = """# The Internet Snapshot

> A frozen, hierarchical 3D map of the internet, built only from public datasets (no crawling). It is made for the
> Primitive environment and for AI agents working on a user's behalf.

Data base URL: {base}
Contract: {repo}/blob/main/docs/snapshot-format.md
Current snapshot: {base}/snapshots/{sid}/manifest.json

## What is in it
- About 8.4k services grouped into 10 realms and 38 functional categories, and about 2.6k networks (ASes) on geographic and edge shells.
- Site graphs: per-site endpoint hierarchies (surfaces → products → hosts/APIs → operations), for example
  {base}/snapshots/{sid}/sites/github.json and {base}/snapshots/{sid}/sites/google.json.
  The index is at {base}/snapshots/{sid}/sites/index.json.
- Code universe: top GitHub repositories grouped by package ecosystem, at {base}/snapshots/{sid}/sites/code-universe.json.
- Routing graph: {base}/snapshots/{sid}/asgraph.json. Run a valley-free simulation over it to estimate AS paths.
- Hostname → node map: {base}/snapshots/{sid}/domains.json

## For agents
- MCP server: `pip install 'internet-snapshot[mcp] @ git+{repo}'`, then run `python -m internet_snapshot mcp`
  with SNAPSHOT_BASE_URL={base}.
  Tools: search, describe, locate, route, site_graph, list_endpoints, code_universe, whereami, activity_overlay.
- `locate(url)` tells you which service, site section and API operation a URL belongs to, including the operation's
  documentation link. Use it before calling an unfamiliar API.
- Node ids are stable across snapshots: svc:<domain>, org:<slug>, as:<asn>, site:<id>/....

## Licences
Code: MIT. Data: see `attribution` in the manifest. It includes CC BY sources that require attribution.
"""


def build_pages(api_base: str | None = None, ip2asn: bool = True, site_url: str | None = None) -> dict:
    base = (site_url or PAGES_BASE).rstrip("/")
    sid, sdir, manifest = _latest()
    out = PUBLIC_DIR
    glyphs, brands = _used_icons(sdir, manifest)
    icons_dir = out / "icons"
    if icons_dir.exists():
        shutil.rmtree(icons_dir)
    idx = build_icons(icons_dir, glyphs, brands)
    shards = build_ip2asn(out / "ip2asn" / "v4") if ip2asn and SOURCES["originasn"].available() else 0
    (out / "agent.json").write_text(json.dumps(agent_descriptor(manifest, api_base, base), indent=1))
    (out / "llms.txt").write_text(LLMS_TXT.format(base=base, repo=REPO, sid=sid))
    shutil.copy(ROOT / "viewer" / "index.html", out / "index.html")
    (out / ".nojekyll").write_text("")
    return {"snapshot_id": sid, "icons": len(idx["atlases"][0]["cells"]), "ip2asn_shards": shards}
